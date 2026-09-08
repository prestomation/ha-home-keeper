"""Input strategies shared by the property-based tests.

Import this only from a module that has already run
``pytest.importorskip("hypothesis")``. It imports Hypothesis at the top level, so on a
bare ``pip install pytest`` it raises ``ImportError`` rather than skipping politely.

**Everything is built through the real builders.** ``tasks()`` calls
``models.build_task`` and ``assets()`` calls ``assets.build_asset`` rather than
assembling dicts by hand. A hand-rolled task would be a second description of what a
task is, sitting next to the first one and free to drift from it — the exact failure
``transfer.py`` warns about when it argues for a denylist over an allowlist. The cost
is that a strategy cannot produce an *invalid* record; that is the right trade, because
the properties here are about what the code does with records it accepts.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import hk_assets as assets_model
import hk_models as models
from hypothesis import strategies as st

# The offset the rest of the recurrence suite uses, so a property that fails can be
# compared against the example-based tests without a timezone difference in the way.
TZ = timezone(timedelta(hours=-4))

# Real zones, named rather than drawn from `st.timezones()`. Three reasons: the system
# tzdb version differs between a contributor's machine and the runner, which would make
# the domain environment-dependent and defeat `derandomize`; the full set is ~600 mostly
# aliases, which adds shrink noise; and a written list is a statement of coverage a
# reviewer can read and extend.
_ZONE_NAMES = (
    "America/New_York",  # 1 h DST, transition at 02:00 local
    # transition at 01:00, so 00:30 and 01:30 are the interesting local times
    "Europe/London",
    "Australia/Lord_Howe",  # 30-minute DST — catches "a shift is an hour" assumptions
    "Pacific/Chatham",  # +12:45 / +13:45, a quarter-hour base offset
    "America/Santiago",  # transition at midnight — bites anything doing replace(hour=0)
    "Asia/Kolkata",  # +05:30, no DST — a half-hour offset control
    "UTC",
)


def available_zones() -> list[ZoneInfo]:
    """The zones above that this machine actually has data for.

    A stripped container can ship Python without a tzdb. Returning what is present lets
    the caller skip cleanly instead of failing on an unrelated packaging difference.
    """
    found = []
    for name in _ZONE_NAMES:
        try:
            found.append(ZoneInfo(name))
        except ZoneInfoNotFoundError:  # pragma: no cover - depends on the image
            continue
    return found


def zones() -> st.SearchStrategy[ZoneInfo]:
    """One of the named real zones."""
    return st.sampled_from(available_zones())


# Local times chosen to land on and around the transitions rather than by luck: the
# gap hour, the ambiguous hour, midnight, and a late-evening control.
_TRANSITION_TIMES = (
    time(0, 0),
    time(0, 30),
    time(1, 30),
    time(2, 30),
    time(3, 0),
    time(23, 30),
)


def aware_datetimes(
    *,
    min_year: int = 1970,
    max_year: int = 2035,
    tz: timezone = TZ,
) -> st.SearchStrategy[datetime]:
    """Timezone-aware datetimes on a fixed offset.

    A fixed offset on purpose: R1 compares against a reference implementation, and a
    reference that has to agree about DST is a second implementation of the thing under
    test rather than an oracle for it. The real zones live in `zoned_datetimes`.
    """
    return st.datetimes(
        min_value=datetime(min_year, 1, 1),
        max_value=datetime(max_year, 12, 31, 23, 59),
    ).map(lambda d: d.replace(tzinfo=tz))


def zoned_datetimes() -> st.SearchStrategy[datetime]:
    """Aware datetimes in a real zone, aimed at the DST transitions."""
    return st.builds(
        lambda d, t, z: datetime.combine(d, t, tzinfo=z),
        st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
        st.sampled_from(_TRANSITION_TIMES),
        zones(),
    )


def _mmdd(*, always_exists: bool = False) -> st.SearchStrategy[str]:
    """A ``MM-DD`` string.

    ``always_exists`` drops ``02-29``, the one date that is absent from 3 years in 4.
    A season boundary on it is a real and separately recorded defect (the season code
    clamps it to Feb 28 when it starts a window, but ``in_season`` does not clamp when
    it checks one), so a property that wants to talk about *anything else* has to be
    able to exclude it.
    """
    fixed = ["12-31", "01-01", "10-01", "04-30"]
    if not always_exists:
        fixed = ["02-29", *fixed]
    return st.one_of(
        st.sampled_from(fixed),
        st.builds(
            lambda m, d: f"{m:02d}-{d:02d}",
            st.integers(1, 12),
            st.integers(1, 28),
        ),
    )


def seasons(*, always_exists: bool = False) -> st.SearchStrategy[list[dict]]:
    """1 to 3 season windows, wrap-around included.

    A window whose start is after its end (``10-01`` to ``04-30``) runs across new year.
    That is the case the season code has to special-case, so the generator must be able
    to produce it — `_mmdd` draws both ends independently, which it does naturally.
    """
    day = _mmdd(always_exists=always_exists)
    return st.lists(
        st.builds(lambda s, e: {"start": s, "end": e}, day, day),
        min_size=1,
        max_size=3,
    )


def floating_tasks(*, now: datetime) -> st.SearchStrategy[dict]:
    """Floating tasks, the shape most of the schedule code is written for."""
    return st.builds(
        lambda name, interval, unit: models.build_task(
            {"name": name, "interval": interval, "unit": unit}, now=now
        ),
        st.text(min_size=1, max_size=40).filter(lambda s: s.strip()),
        st.integers(1, 36),
        st.sampled_from(["days", "weeks", "months"]),
    )


def _task_payload() -> st.SearchStrategy[dict]:
    """One payload per recurrence type, so every shape is reachable."""
    names = st.text(min_size=1, max_size=40).filter(lambda s: s.strip())
    anchors = aware_datetimes(min_year=2020, max_year=2030).map(lambda d: d.isoformat())
    return st.one_of(
        st.builds(
            lambda n, i, u: {"name": n, "interval": i, "unit": u},
            names,
            st.integers(1, 36),
            st.sampled_from(["days", "weeks", "months"]),
        ),
        st.builds(
            lambda n, i, f, a: {
                "name": n,
                "recurrence_type": "fixed",
                "interval": i,
                "freq": f,
                "anchor": a,
            },
            names,
            st.integers(1, 12),
            st.sampled_from(["DAILY", "WEEKLY", "MONTHLY"]),
            anchors,
        ),
        st.builds(
            lambda n, d: {"name": n, "recurrence_type": "one-off", "due": d},
            names,
            anchors,
        ),
        st.builds(
            lambda n: {"name": n, "recurrence_type": "triggered"},
            names,
        ),
        st.builds(
            lambda n, t: {
                "name": n,
                "recurrence_type": "sensor",
                "sensor": {
                    "entity_id": "sensor.probe",
                    "mode": "usage",
                    "target": t,
                },
            },
            names,
            st.integers(1, 5000),
        ),
    )


def tasks(*, now: datetime) -> st.SearchStrategy[dict]:
    """A task of any recurrence type, built through ``models.build_task``.

    Half carry an ``external_id``. Both halves matter: without one, the export branch
    that writes the key never runs; with one always set, the branch that omits it never
    runs. A maximal fixture can only ever cover the first case.
    """
    keys = st.one_of(
        st.just(""), st.text(min_size=1, max_size=20).filter(lambda s: s.strip())
    )
    return st.builds(
        lambda payload, key: models.build_task(
            {**payload, **({"external_id": key} if key else {})}, now=now
        ),
        _task_payload(),
        keys,
    )


def assets(*, now: datetime) -> st.SearchStrategy[dict]:
    """An appliance, built through ``assets.build_asset``."""
    text = st.text(min_size=1, max_size=30).filter(lambda s: s.strip())
    return st.builds(
        lambda name, maker, model_name: assets_model.build_asset(
            {"name": name, "manufacturer": maker, "model": model_name}, now=now
        ),
        text,
        st.one_of(st.just(""), text),
        st.one_of(st.just(""), text),
    )


def timestamp_pool(*, now: datetime, size: int = 6) -> list[str]:
    """A small pool of ISO timestamps, so generated histories collide on ``ts``.

    Duplicate timestamps are the whole point. Every existing history test uses distinct
    ones, which is exactly why the ``sort(key=None)`` mutant in
    ``transfer.apply_history`` is alive: with distinct keys the tuple comparison never
    reaches the second element.
    """
    return [(now - timedelta(days=7 * i)).isoformat() for i in range(size)]


def history_entries(
    pool: list[str], *, with_reading: bool = False
) -> st.SearchStrategy[list[dict]]:
    """Completion entries drawn from *pool*, so duplicates happen on purpose."""

    def _entry(ts: str, note: str, reading: int | None) -> dict:
        entry: dict = {"completed_at": ts}
        if note:
            entry["note"] = note
        if reading is not None:
            entry["reading"] = reading
        return entry

    return st.lists(
        st.builds(
            _entry,
            st.sampled_from(pool),
            st.one_of(st.just(""), st.text(max_size=20)),
            st.integers(1, 9999) if with_reading else st.none(),
        ),
        max_size=8,
    )


def skip_entries(pool: list[str]) -> st.SearchStrategy[list[dict]]:
    """Skip entries drawn from the same pool as the completions."""
    return st.lists(
        st.builds(
            lambda ts, note: (
                {"skipped_at": ts, "note": note} if note else {"skipped_at": ts}
            ),
            st.sampled_from(pool),
            st.one_of(st.just(""), st.text(max_size=20)),
        ),
        max_size=6,
    )


def parent_graphs() -> st.SearchStrategy[tuple[int, list[tuple[int, int | None]]]]:
    """A parent edge per appliance, as ``(count, [(child_index, parent_index)])``.

    ``parent_index`` is ``None`` for a root, may equal ``child_index`` (a self-parent),
    and may point either way, so cycles of every length are reachable — including the
    two-appliance loop whose halves each look harmless on their own, which is the case
    ``transfer._looping_parents`` exists for.
    """
    return st.integers(2, 6).flatmap(
        lambda n: st.tuples(
            st.just(n),
            st.lists(
                st.tuples(
                    st.integers(0, n - 1), st.one_of(st.none(), st.integers(0, n - 1))
                ),
                min_size=1,
                max_size=n,
                unique_by=lambda pair: pair[0],
            ),
        )
    )
