"""Two-phase Home Assistant upgrade harness.

Boots a **pre-split** Home Assistant against a throwaway config dir, seeds the
scenarios, shuts it down, then boots the **current** Home Assistant against the same
dir so HA performs its own device-registry migration in between. Tests then assert
what survived.

Why a real upgrade rather than a hand-written post-split fixture: the thing under
test is what Home Assistant *actually does* to devices Home Keeper attached to. A
fixture would encode our guess at that, and a wrong guess produces a green suite and
broken users — which is precisely how #183 reached a release.

Cost control: every scenario is seeded into **one** config dir and the upgrade runs
**once**, so a full pass is two Home Assistant cold starts rather than two per
scenario. The scenarios use distinct devices and tasks, so they don't interact.

Run it with::

    bash ci/fetch-glues.sh          # stage the glues + upstream stubs (once)
    python -m pytest tests/upgrade -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
import requests
import websockets.sync.client

HERE = Path(__file__).parent
COMPOSE_FILE = HERE / "docker-compose.yml"
FIXTURE_CONFIG = HERE / "fixtures" / "ha_config"

#: The last Home Assistant release **before** devices were split per config entry.
#: This is a FROZEN pin, not a version to keep current: it defines "the world users
#: are upgrading from". Bumping it changes what the test means. See
#: https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/
OLD_HA_TAG = os.environ.get("UPGRADE_OLD_HA_TAG", "2026.7")

#: The version being upgraded *to*. `stable` on PRs, `beta` in the nightly.
NEW_HA_TAG = os.environ.get("HA_TAG", "stable")

HA_PORT = os.environ.get("HA_PORT", "8124")
HA_URL = f"http://localhost:{HA_PORT}"
WS_URL = f"ws://localhost:{HA_PORT}/api/websocket"

BOOT_TIMEOUT = 240
SETTLE_SECONDS = 20


# ── container control ────────────────────────────────────────────────────────


def _compose(*args: str, config_dir: Path, ha_tag: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "HA_TAG": ha_tag,
        "HA_CONFIG": str(config_dir),
        "HA_PORT": HA_PORT,
    }
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        env=env,
        cwd=str(HERE),
        capture_output=True,
        text=True,
        check=False,
    )


def _wait_for_running(timeout: int = BOOT_TIMEOUT) -> str:
    """Block until HA answers, then return an access token.

    Onboarding is only needed on the first boot; the second boot reuses the auth
    written into the (persistent) config dir, so this logs in instead.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            code = requests.get(f"{HA_URL}/api/", timeout=5).status_code
            if code in (200, 401):
                break
        except requests.RequestException:
            pass
        time.sleep(2)
    else:
        raise RuntimeError(f"Home Assistant did not respond within {timeout}s")

    token = _onboard_or_login()

    # Answering on /api/ is not the same as having set every integration up.
    deadline = time.monotonic() + timeout
    session = _session(token)
    while time.monotonic() < deadline:
        try:
            state = session.get(f"{HA_URL}/api/config", timeout=5).json().get("state")
            if state == "RUNNING":
                return token
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError("Home Assistant never reached state RUNNING")


def _onboard_or_login() -> str:
    """Complete onboarding (first boot) or log in (second boot); return a token."""
    resp = requests.post(
        f"{HA_URL}/api/onboarding/users",
        json={
            "client_id": HA_URL + "/",
            "name": "Upgrade Test",
            "username": "test",
            "password": "testtest1",
            "language": "en",
        },
        timeout=30,
    )
    if resp.status_code == 200:
        code = resp.json()["auth_code"]
    elif resp.status_code in (403, 404):
        # Already onboarded — the second boot's normal path.
        code = _login_auth_code()
    else:
        raise RuntimeError(f"onboarding failed: {resp.status_code} {resp.text}")

    tok = requests.post(
        f"{HA_URL}/auth/token",
        data={
            "client_id": HA_URL + "/",
            "grant_type": "authorization_code",
            "code": code,
        },
        timeout=30,
    )
    tok.raise_for_status()
    return tok.json()["access_token"]


def _login_auth_code() -> str:
    """Drive the username/password login flow and return an authorization code."""
    s = requests.Session()
    start = s.post(
        f"{HA_URL}/auth/login_flow",
        json={
            "client_id": HA_URL + "/",
            "handler": ["homeassistant", None],
            "redirect_uri": HA_URL + "/",
        },
        timeout=30,
    )
    start.raise_for_status()
    flow_id = start.json()["flow_id"]
    step = s.post(
        f"{HA_URL}/auth/login_flow/{flow_id}",
        json={
            "client_id": HA_URL + "/",
            "username": "test",
            "password": "testtest1",
        },
        timeout=30,
    )
    step.raise_for_status()
    return step.json()["result"]


def _session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    return s


# ── registry access ──────────────────────────────────────────────────────────


def ws_command(token: str, command_type: str):
    """Run one no-argument websocket command and return its result."""
    with websockets.sync.client.connect(WS_URL) as ws:
        assert json.loads(ws.recv())["type"] == "auth_required"
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        assert json.loads(ws.recv())["type"] == "auth_ok"
        ws.send(json.dumps({"id": 1, "type": command_type}))
        msg = json.loads(ws.recv())
        assert msg.get("success"), f"{command_type} failed: {msg}"
        return msg["result"]


def snapshot(token: str) -> dict:
    """Devices, entities and Home Keeper tasks, as one comparable blob."""
    session = _session(token)
    resp = session.post(
        f"{HA_URL}/api/services/home_keeper/list_tasks?return_response",
        json={},
        timeout=30,
    )
    tasks = []
    if resp.ok:
        body = resp.json()
        tasks = body.get("service_response", body).get("tasks", [])
    return {
        "devices": ws_command(token, "config/device_registry/list"),
        "entities": ws_command(token, "config/entity_registry/list"),
        "tasks": tasks,
    }


# ── the fixture ──────────────────────────────────────────────────────────────


class UpgradeRun:
    """What the two boots produced, for tests to assert against."""

    def __init__(self, before: dict, after: dict, token: str, config_dir: Path):
        self.before = before
        self.after = after
        self.token = token
        self.config_dir = config_dir

    @property
    def session(self) -> requests.Session:
        return _session(self.token)

    # -- lookup helpers, over the *post-upgrade* registries ------------------

    def devices_with_identifier(self, domain: str, value: str) -> list[dict]:
        return [
            d
            for d in self.after["devices"]
            if any(list(i) == [domain, value] for i in d.get("identifiers", []))
        ]

    def device(self, device_id: str) -> dict | None:
        return next((d for d in self.after["devices"] if d["id"] == device_id), None)

    def entities_on(self, device_id: str) -> list[dict]:
        return [e for e in self.after["entities"] if e.get("device_id") == device_id]

    def tasks_named(self, substring: str) -> list[dict]:
        return [
            t for t in self.after["tasks"] if substring.lower() in t["name"].lower()
        ]

    def tasks_from(self, source_ns: str) -> list[dict]:
        return [
            t for t in self.after["tasks"] if (t.get("source") or {}).get(source_ns)
        ]


@pytest.fixture(scope="session")
def upgrade_run() -> UpgradeRun:
    """Boot pre-split HA, seed, upgrade to current HA, and hand back both snapshots."""
    staged = HERE / "custom_components"
    if not (staged / "home_keeper").is_dir():
        pytest.fail(
            "tests/upgrade/custom_components is not staged — "
            "run `bash ci/fetch-glues.sh` first"
        )

    tmp = Path(tempfile.mkdtemp(prefix="hk-upgrade-"))
    config_dir = tmp / "ha_config"
    shutil.copytree(FIXTURE_CONFIG, config_dir)

    try:
        # ── phase 1: the world before the split ──────────────────────────────
        up = _compose("up", "-d", config_dir=config_dir, ha_tag=OLD_HA_TAG)
        if up.returncode != 0:
            pytest.fail(f"could not start HA {OLD_HA_TAG}: {up.stderr}")
        token = _wait_for_running()

        # The glues create their tasks from a reconcile pass on setup. Wait for the
        # registry to stop changing rather than sleeping a fixed interval — a slow
        # runner would otherwise snapshot a half-built registry and produce a
        # before/after diff that looks like a migration effect but isn't.
        _wait_until_settled(token)
        _seed_home_keeper_scenarios(token)
        _wait_until_settled(token)
        before = snapshot(token)

        # `down` without `-v`: the config dir is a bind mount and must survive.
        _compose("down", config_dir=config_dir, ha_tag=OLD_HA_TAG)

        # ── phase 2: Home Assistant migrates on boot ─────────────────────────
        up = _compose("up", "-d", config_dir=config_dir, ha_tag=NEW_HA_TAG)
        if up.returncode != 0:
            pytest.fail(f"could not start HA {NEW_HA_TAG}: {up.stderr}")
        token = _wait_for_running()
        _wait_until_settled(token)
        after = snapshot(token)

        # Guard against the failure mode that would make every assertion in this
        # suite vacuous: if phase 2 somehow started from a fresh config dir, the
        # "after" world is a clean install rather than a migrated one, and each
        # test would compare two unrelated systems while looking perfectly healthy.
        _assert_phase_two_continued_phase_one(before, after)

        yield UpgradeRun(before, after, token, config_dir)
    finally:
        logs = _compose(
            "logs", "--tail", "400", config_dir=config_dir, ha_tag=NEW_HA_TAG
        )
        (tmp / "ha.log").write_text(logs.stdout or "")
        print(f"\n[upgrade] Home Assistant logs: {tmp / 'ha.log'}")
        _compose("down", "-v", config_dir=config_dir, ha_tag=NEW_HA_TAG)


def _wait_until_settled(token: str, quiet_for: int = 8, timeout: int = 120) -> None:
    """Poll until devices, entities and tasks stop changing for *quiet_for* seconds.

    Replaces a fixed sleep: integrations finish setting up at wildly different rates
    on a loaded CI runner, and a snapshot of a half-built registry produces a
    before/after diff that reads like a migration effect.
    """
    deadline = time.monotonic() + timeout
    previous: tuple[int, int, int] | None = None
    stable_since: float | None = None
    while time.monotonic() < deadline:
        snap = snapshot(token)
        current = (len(snap["devices"]), len(snap["entities"]), len(snap["tasks"]))
        if current == previous:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= quiet_for:
                return
        else:
            previous, stable_since = current, None
        time.sleep(2)
    # Not fatal: the assertions still run, but say so, because a timeout here is the
    # most likely explanation for a confusing result downstream.
    print(f"\n[upgrade] WARNING: registry never went quiet within {timeout}s")


def _assert_phase_two_continued_phase_one(before: dict, after: dict) -> None:
    """Fail loudly if phase 2 booted a fresh config rather than the migrated one."""
    if not before["tasks"]:
        pytest.fail("phase 1 produced no tasks — the fixture never seeded")
    if not after["tasks"]:
        pytest.fail(
            "phase 2 has no tasks at all: it almost certainly started from a fresh "
            "config dir, which would make every assertion in this suite vacuous"
        )
    # Task ids are generated per creation, so a shared id proves continuity in a way
    # that names (which a fresh seed would recreate identically) cannot.
    before_ids = {t["id"] for t in before["tasks"]}
    if not before_ids & {t["id"] for t in after["tasks"]}:
        pytest.fail(
            "no task id survived into phase 2 — the config dir was not carried over, "
            "so the 'after' world is a clean install rather than a migrated one"
        )


def _seed_home_keeper_scenarios(token: str) -> None:
    """Create the Home Keeper-side scenarios that aren't produced by a glue.

    The glue scenarios seed themselves — each glue's reconcile runs at setup and
    creates its task. These are the plain Home Keeper cases: a task attached to a
    foreign device, an asset decorating a foreign device, and a virtual asset that
    Home Keeper owns outright.
    """
    session = _session(token)
    devices = ws_command(token, "config/device_registry/list")

    def device_id_for(domain: str, value: str) -> str:
        for d in devices:
            if any(list(i) == [domain, value] for i in d.get("identifiers", [])):
                return d["id"]
        raise AssertionError(f"fixture device ({domain}, {value}) missing pre-upgrade")

    kitchen = device_id_for("hk_upgrade_source", "kitchen_sensor")
    heater = device_id_for("hk_upgrade_source", "water_heater")

    def call(service: str, payload: dict) -> None:
        resp = session.post(
            f"{HA_URL}/api/services/home_keeper/{service}", json=payload, timeout=30
        )
        assert resp.ok, f"{service} failed: {resp.status_code} {resp.text}"

    # Scenario 1 — a plain task attached to a device Home Keeper does not own.
    call(
        "add_task",
        {
            "name": "Upgrade probe foreign task",
            "recurrence_type": "floating",
            "interval": 6,
            "unit": "months",
            "device_id": kitchen,
        },
    )
    # Scenario 2 — an asset decorating a foreign device (existing-kind).
    call(
        "add_asset",
        {
            "name": "Upgrade probe existing asset",
            "kind": "existing",
            "device_id": heater,
        },
    )
    # Scenario 3 — a virtual asset, whose device Home Keeper owns outright.
    call("add_asset", {"name": "Upgrade probe virtual asset", "kind": "virtual"})
