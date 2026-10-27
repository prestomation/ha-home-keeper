"""Harness for the noise-budget tier.

Each scenario in ``test_noise_budget.py`` resets the probe, does 1 action, waits until
Home Keeper is quiet, and compares what it wrote with ``baseline.json``. Read
``.amazonq/rules/testing.md`` ("Noise budget") for how to run it and how to change a
budget on purpose.

The scenarios share 1 Home Assistant and run in file order. A later scenario uses what
an earlier one made, so run the file whole.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import requests
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

HA_URL = "http://localhost:8123"
BASELINE = Path(__file__).with_name("baseline.json")
UPDATE = os.environ.get("HK_NOISE_UPDATE") == "1"
UPDATE_HINT = "HK_NOISE_UPDATE=1 bash ci/test-noise.sh"

# The counters that have a budget. The probe counts more; the failure message prints
# them all, because they help to find the cause.
COUNTERS = (
    "logbook_rows",
    "unavailable_flips",
    "events",
    "storage_writes",
    "entry_reloads",
)
# Home Keeper refreshes its entities through a debouncer with a 10 second cooldown,
# and the declarative companion sync waits 5 seconds after a registry event. A
# scenario is over when no counter has moved for longer than both, so a deferred
# write cannot land in the next scenario.
QUIET_SECONDS = 11.0
SETTLE_LIMIT = 120.0


class HomeAssistantClient:
    """REST and websocket access to the Home Assistant under test."""

    def __init__(self) -> None:
        self._wait_for_api()
        self.token = _token()
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {self.token}"
        self.wait_running()

    @staticmethod
    def _wait_for_api(timeout: float = 180) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if requests.get(f"{HA_URL}/api/", timeout=5).status_code in (200, 401):
                    return
            except requests.RequestException:
                pass
            time.sleep(2)
        raise TimeoutError(f"Home Assistant did not answer within {timeout}s")

    def wait_running(self, timeout: float = 180) -> None:
        """Wait until HA is RUNNING and the probe is set up."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                r = self.http.get(f"{HA_URL}/api/config", timeout=5)
                if r.status_code == 200 and r.json().get("state") == "RUNNING":
                    services = self.http.get(f"{HA_URL}/api/services", timeout=5).json()
                    if any(s["domain"] == "hk_noise_probe" for s in services):
                        return
            except requests.RequestException:
                pass
            time.sleep(2)
        raise TimeoutError("Home Assistant with the noise probe did not start")

    def call(
        self, domain: str, service: str, data: dict[str, Any] | None = None
    ) -> Any:
        """Call a service and return its response, if it gives one."""
        url = f"{HA_URL}/api/services/{domain}/{service}?return_response"
        r = self.http.post(url, json=data or {}, timeout=120)
        if r.status_code == 400 and "return_response" in r.text:
            r = self.http.post(url.split("?")[0], json=data or {}, timeout=120)
        if r.status_code >= 400:
            raise AssertionError(f"{domain}.{service} failed: {r.status_code} {r.text}")
        body = r.json()
        return body.get("service_response") if isinstance(body, dict) else body

    def ws(self, message: dict[str, Any]) -> Any:
        """Send 1 websocket command and return its result."""
        url = f"{HA_URL.replace('http', 'ws')}/api/websocket"
        try:
            with connect(url, open_timeout=10) as sock:
                sock.recv(timeout=10)
                sock.send(json.dumps({"type": "auth", "access_token": self.token}))
                sock.recv(timeout=10)
                sock.send(json.dumps({"id": 1, **message}))
                while True:
                    reply = json.loads(sock.recv(timeout=120))
                    if reply.get("id") == 1 and reply.get("type") == "result":
                        break
        except (OSError, TimeoutError, ValueError, ConnectionClosed) as err:
            raise AssertionError(
                f"websocket {message['type']} failed: {err!r}"
            ) from err
        if not reply.get("success"):
            raise AssertionError(f"{message['type']}: {reply.get('error')}")
        return reply.get("result")

    def snapshot(self) -> dict[str, Any]:
        return self.call("hk_noise_probe", "snapshot")

    def settle(self) -> dict[str, Any]:
        """Wait until no counter moved for QUIET_SECONDS; return the snapshot."""
        deadline = time.monotonic() + SETTLE_LIMIT
        snap = self.snapshot()
        while snap["quiet_seconds"] < QUIET_SECONDS:
            if time.monotonic() > deadline:
                raise AssertionError(
                    f"Home Keeper did not go quiet within {SETTLE_LIMIT:.0f}s. "
                    f"Something writes without end: {snap['counts']}"
                )
            time.sleep(max(0.5, QUIET_SECONDS - snap["quiet_seconds"]))
            snap = self.snapshot()
        return snap

    def logbook_rows(
        self, start: dt.datetime, entities: list[str]
    ) -> list[dict[str, Any]]:
        """Home Keeper's logbook rows since *start*."""
        watched = set(entities)
        r = self.http.get(
            f"{HA_URL}/api/logbook/{start.isoformat()}",
            params={"end_time": dt.datetime.now(dt.UTC).isoformat()},
            timeout=60,
        )
        r.raise_for_status()
        return [
            row
            for row in r.json()
            if row.get("entity_id") in watched or row.get("domain") == "home_keeper"
        ]


def _token() -> str:
    """Make the onboarding user, or log in when onboarding is done."""
    r = requests.post(
        f"{HA_URL}/api/onboarding/users",
        json={
            "client_id": f"{HA_URL}/",
            "name": "Test",
            "username": "test",
            "password": "testtest1",
            "language": "en",
        },
        timeout=10,
    )
    if r.status_code == 200:
        token = _exchange(r.json()["auth_code"])
        headers = {"Authorization": f"Bearer {token}"}
        for step, payload in (
            ("core_config", {}),
            ("analytics", {}),
            (
                "integration",
                {
                    "client_id": f"{HA_URL}/",
                    "redirect_uri": f"{HA_URL}/?auth_callback=1",
                },
            ),
        ):
            requests.post(
                f"{HA_URL}/api/onboarding/{step}",
                headers=headers,
                json=payload,
                timeout=10,
            )
        return token
    flow = requests.post(
        f"{HA_URL}/auth/login_flow",
        json={
            "client_id": f"{HA_URL}/",
            "handler": ["homeassistant", None],
            "redirect_uri": f"{HA_URL}/?auth_callback=1",
        },
        timeout=10,
    ).json()["flow_id"]
    result = requests.post(
        f"{HA_URL}/auth/login_flow/{flow}",
        json={"username": "test", "password": "testtest1", "client_id": f"{HA_URL}/"},
        timeout=10,
    ).json()["result"]
    return _exchange(result)


def _exchange(code: str) -> str:
    r = requests.post(
        f"{HA_URL}/auth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": f"{HA_URL}/",
        },
        timeout=10,
    )
    r.raise_for_status()
    return str(r.json()["access_token"])


# --- Measurement ---------------------------------------------------------------------


def measure(
    ha: HomeAssistantClient,
    action: Callable[[], Any] | None,
    *,
    reset: bool = True,
    since: dt.datetime | None = None,
) -> tuple[dict[str, Any], Any]:
    """Do *action*, wait until quiet, and return the counts and the action's result."""
    if reset:
        ha.call("hk_noise_probe", "reset")
    start = since or dt.datetime.now(dt.UTC)
    result = action() if action is not None else None
    snap = ha.settle()
    rows = ha.logbook_rows(start, snap["entities"])
    counts = {**snap["counts"], "logbook_rows": len(rows)}
    snap["logbook"] = collections_count(
        f"{row.get('entity_id') or row.get('domain')}: "
        f"{row.get('message') or row.get('state')}"
        for row in rows
    )
    return {"counts": counts, "snapshot": snap}, result


def collections_count(items: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1])[:15])


# --- Budgets -------------------------------------------------------------------------


class Baseline:
    """The budgets in baseline.json, and the writer for the update mode."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = json.loads(BASELINE.read_text())
        self.changed = False

    def scenario(self, name: str) -> dict[str, Any]:
        try:
            return dict(self.data["scenarios"][name])
        except KeyError:
            raise AssertionError(
                f"Scenario '{name}' has no budget in {BASELINE.name}. "
                f"Run {UPDATE_HINT} to add it, and review the numbers."
            ) from None

    def record(self, name: str, counts: dict[str, int]) -> None:
        """Update mode: write the measured numbers as the new budget.

        A pinned counter stays at its value, and a known bug keeps its entry. Both
        change only by hand, because a change there is a decision, not a measurement.
        """
        entry = self.data["scenarios"].setdefault(name, {"budget": {}})
        pinned = set(entry.get("pinned", []))
        known = entry.get("known", {}).get("counters", {})
        for counter in COUNTERS:
            if counter in pinned or counter in known:
                continue
            value = counts.get(counter, 0)
            if entry["budget"].get(counter) != value:
                entry["budget"][counter] = value
                self.changed = True

    def write(self) -> None:
        if self.changed:
            BASELINE.write_text(json.dumps(self.data, indent=2) + "\n")


def check(baseline: Baseline, name: str, measured: dict[str, Any]) -> None:
    """Fail when a counter is over its budget. Report a known bug as xfail.

    A ``known`` entry is a bug that is in the code now. Its counters have a ``target``
    (the right number) and a ``now`` (what the bug makes). It behaves like a strict
    xfail, but for each counter, and ``now`` is exact: only a count equal to ``now``
    is an expected failure. Above ``now`` the bug got worse. Between ``target`` and
    ``now`` the bug is fixed in part, so the entry must say the new ``now``, or a
    later regression up to the old value would stay hidden. At or below ``target``
    the counter is fixed, so the PR that fixes it must take it out of the entry.
    """
    counts = measured["counts"]
    if UPDATE:
        baseline.record(name, counts)
        return
    entry = baseline.scenario(name)
    budget: dict[str, int] = entry["budget"]
    known = entry.get("known", {})
    known_counters: dict[str, dict[str, int]] = known.get("counters", {})
    over = [
        c
        for c in COUNTERS
        if c not in known_counters and counts.get(c, 0) > budget.get(c, 0)
    ]
    worse = [c for c, k in known_counters.items() if counts.get(c, 0) > k["now"]]
    if over or worse:
        pytest.fail(_report(name, measured, entry, over + worse), pytrace=False)
    fixed = [c for c, k in known_counters.items() if counts.get(c, 0) <= k["target"]]
    if fixed:
        what = (
            "Delete the 'known' entry of this scenario"
            if len(fixed) == len(known_counters)
            else f"Take {', '.join(fixed)} out of the 'known' entry of this scenario"
        )
        pytest.fail(
            f"{known['bug']} looks fixed in '{name}': {_pairs(counts, fixed)} is at "
            f"its target now. {what} in {BASELINE.name}, and set the budget to the "
            f"new numbers.\n" + _report(name, measured, entry, fixed),
            pytrace=False,
        )
    partial = [c for c, k in known_counters.items() if counts.get(c, 0) < k["now"]]
    if partial:
        pytest.fail(
            f"{known['bug']} is fixed in part in '{name}': {_pairs(counts, partial)} "
            f"is below the 'now' value of its 'known' entry. Set 'now' to these "
            f"numbers in {BASELINE.name}, so a later regression cannot hide below "
            f"the old value.\n" + _report(name, measured, entry, partial),
            pytrace=False,
        )
    if known_counters:
        pytest.xfail(f"{known['bug']}: {known['reason']}")


def _pairs(counts: dict[str, int], names: list[str]) -> str:
    return ", ".join(f"{n}={counts.get(n, 0)}" for n in names)


def _report(
    name: str, measured: dict[str, Any], entry: dict[str, Any], flagged: list[str]
) -> str:
    counts = measured["counts"]
    snap = measured["snapshot"]
    known = entry.get("known", {}).get("counters", {})
    lines = [
        f"Noise budget exceeded in scenario '{name}'.",
        "",
        f"  {'counter':<26}{'measured':>9}{'budget':>8}",
    ]
    for counter in COUNTERS:
        limit = (
            known[counter]["now"]
            if counter in known
            else entry["budget"].get(counter, 0)
        )
        mark = "   <-- over" if counter in flagged else ""
        lines.append(f"  {counter:<26}{counts.get(counter, 0):>9}{limit:>8}{mark}")
    extra = {k: v for k, v in counts.items() if k not in COUNTERS}
    lines += ["", f"  other counts: {json.dumps(extra, sort_keys=True)}"]
    for key in ("events", "storage_writes", "entry_reloads", "unavailable_flips"):
        if snap["detail"].get(key):
            top = dict(list(snap["detail"][key].items())[:8])
            lines.append(f"  {key}: {json.dumps(top)}")
    if snap.get("logbook"):
        lines.append(f"  logbook rows: {json.dumps(snap['logbook'])}")
    lines += [
        "",
        "If the new number is right, update the budget on purpose and commit the diff:",
        f"  {UPDATE_HINT}",
    ]
    return "\n".join(lines)


# --- Fixtures ------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ha() -> HomeAssistantClient:
    return HomeAssistantClient()


@pytest.fixture(scope="session")
def baseline() -> Iterator[Baseline]:
    data = Baseline()
    yield data
    if UPDATE:
        data.write()


@pytest.fixture(scope="session")
def shared() -> dict[str, Any]:
    """Ids that a scenario makes and a later scenario uses."""
    return {}
