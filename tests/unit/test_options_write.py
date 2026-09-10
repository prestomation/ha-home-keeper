"""``async_set_options`` — the one write path for the config-entry options.

Every surface that changes options goes through here: the ``set_options`` service,
the panel's websocket command, and (indirectly) the Configure dialog. So this is
where the profile-in-use guard sits, and where the awaited-reload contract is kept.

``options.py`` imports Home Assistant only under ``TYPE_CHECKING``, so a fake entry
and a fake ``hass`` are enough — the same trick ``test_coordinator_purge.py`` and
``test_device_heal.py`` use. Keeping this in the unit tier is not a convenience:
``ci/mutation_scope.py`` maps a changed line to its whole enclosing function, and
mutmut runs ``tests/unit`` only, so without these the mutants in ``async_set_options``
would all survive.
"""

from __future__ import annotations

import asyncio
from typing import Any

import hk_const as const  # type: ignore[import-not-found]
import hk_options as opts  # type: ignore[import-not-found]
import pytest


class _FakeConfigEntries:
    """Records the two calls ``async_set_options`` makes, in order."""

    def __init__(self, on_reload: Any = None) -> None:
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self.reloaded: list[str] = []
        # Called inside ``async_reload``, so a test can look at the reloading flag
        # while the reload is in flight rather than only after it.
        self._on_reload = on_reload

    def async_update_entry(self, entry: Any, *, options: dict[str, Any]) -> None:
        self.updated.append((entry.entry_id, options))
        entry.options = options

    async def async_reload(self, entry_id: str) -> None:
        self.reloaded.append(entry_id)
        if self._on_reload is not None:
            self._on_reload()


class _FakeHass:
    def __init__(self, on_reload: Any = None) -> None:
        self.config_entries = _FakeConfigEntries(on_reload)


class _FakeEntry:
    def __init__(self, options: dict[str, Any]) -> None:
        self.entry_id = "entry-1"
        self.options = options


_P1 = {"id": "p1", "name": "My chores", "filter": {"status": "overdue"}}
_N_ON_P1 = {"id": "n1", "name": "Walk", "profile_id": "p1", "targets": []}


def _set(hass: Any, entry: Any, updates: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(opts.async_set_options(hass, entry, updates))


# ------------------------------------------------------------------ the write itself


def test_a_real_change_is_written_and_its_reload_awaited() -> None:
    """The merged document is persisted, then the entry reload is awaited.

    The await is the contract: the caller has to see the reconciled task set by the
    time this returns, rather than racing the update listener's own reload.
    """
    hass, entry = _FakeHass(), _FakeEntry({})
    merged = _set(hass, entry, {const.OPTION_SYNC_PROBLEM_SENSORS: True})
    assert merged[const.OPTION_SYNC_PROBLEM_SENSORS] is True
    assert hass.config_entries.updated == [("entry-1", merged)]
    assert hass.config_entries.reloaded == ["entry-1"]


def test_a_save_that_changes_nothing_writes_nothing() -> None:
    """No write, and no reload — reloading an entry is expensive and visible.

    The panel saves a whole card on every keystroke it debounces, so most saves that
    reach here are already what is stored.
    """
    hass = _FakeHass()
    entry = _FakeEntry({const.OPTION_SYNC_PROBLEM_SENSORS: True})
    merged = _set(hass, entry, {const.OPTION_SYNC_PROBLEM_SENSORS: True})
    assert merged == opts.current_options(entry)
    assert hass.config_entries.updated == []
    assert hass.config_entries.reloaded == []


def test_the_caller_reloading_flag_is_set_during_the_reload_and_cleared_after() -> None:
    """The update listener reads this flag to skip its own overlapping reload.

    Asserted from *inside* the fake reload, because a check after the call cannot
    tell a flag that was set from one that never was.
    """
    seen: list[bool] = []
    hass = _FakeHass(on_reload=lambda: seen.append(opts.caller_is_reloading("entry-1")))
    entry = _FakeEntry({})
    _set(hass, entry, {const.OPTION_SYNC_PROBLEM_SENSORS: True})
    assert seen == [True]
    assert opts.caller_is_reloading("entry-1") is False


def test_the_flag_is_cleared_even_when_the_reload_raises() -> None:
    """Otherwise one failed reload leaves the listener muted for the rest of the run."""

    def boom() -> None:
        raise RuntimeError("reload failed")

    hass = _FakeHass(on_reload=boom)
    entry = _FakeEntry({})
    with pytest.raises(RuntimeError):
        _set(hass, entry, {const.OPTION_SYNC_PROBLEM_SENSORS: True})
    assert opts.caller_is_reloading("entry-1") is False


# -------------------------------------------------------- the profile-in-use guard


def test_removing_a_profile_a_notification_uses_is_refused() -> None:
    """And nothing is written: a refused save leaves the stored options as they were.

    This is what the panel, the ``set_options`` service and the websocket command all
    sit behind, so the guard has to be here rather than in any one of them.
    """
    hass = _FakeHass()
    entry = _FakeEntry(
        {const.OPTION_PROFILES: [_P1], const.OPTION_NOTIFICATIONS: [_N_ON_P1]}
    )
    with pytest.raises(opts.ProfileInUseError) as caught:
        _set(hass, entry, {const.OPTION_PROFILES: []})
    assert caught.value.profiles == "My chores"
    assert caught.value.notifications == "Walk"
    assert hass.config_entries.updated == []
    assert hass.config_entries.reloaded == []
    assert entry.options[const.OPTION_PROFILES] == [_P1]


def test_removing_a_profile_with_its_notifications_is_written() -> None:
    """One call carrying both empty lists is the supported way to clear a profile."""
    hass = _FakeHass()
    entry = _FakeEntry(
        {const.OPTION_PROFILES: [_P1], const.OPTION_NOTIFICATIONS: [_N_ON_P1]}
    )
    merged = _set(
        hass, entry, {const.OPTION_PROFILES: [], const.OPTION_NOTIFICATIONS: []}
    )
    assert merged[const.OPTION_PROFILES] == []
    assert merged[const.OPTION_NOTIFICATIONS] == []
    assert hass.config_entries.reloaded == ["entry-1"]


def test_a_save_that_leaves_a_dangling_profile_id_alone_still_writes() -> None:
    """The guard fires on a profile *this save* removes, not on one already missing.

    A notification can already name a profile that is not there. That document has to
    keep saving, or the person can never edit their way out of it.
    """
    hass = _FakeHass()
    entry = _FakeEntry(
        {
            const.OPTION_PROFILES: [],
            const.OPTION_NOTIFICATIONS: [
                {"id": "n1", "name": "Ghost", "profile_id": "gone", "targets": []}
            ],
        }
    )
    _set(hass, entry, {const.OPTION_SYNC_PROBLEM_SENSORS: True})
    assert hass.config_entries.reloaded == ["entry-1"]


def test_the_guard_does_not_fire_on_a_save_that_changes_nothing() -> None:
    """It sits after the no-op short-circuit, so re-sending what is stored is safe.

    Without that order, an install that already holds a dangling id could not save
    even a document identical to the one it has.
    """
    hass = _FakeHass()
    stored = opts.current_options(
        _FakeEntry(
            {const.OPTION_PROFILES: [_P1], const.OPTION_NOTIFICATIONS: [_N_ON_P1]}
        )
    )
    entry = _FakeEntry(stored)
    merged = _set(hass, entry, stored)
    assert merged == stored
    assert hass.config_entries.updated == []
