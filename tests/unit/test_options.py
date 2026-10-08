"""The config-entry options merge rules, and the drift guards around them.

Three surfaces write ``entry.options`` and they share one coercion table in
``options.py``. Two of them (the ``set_options`` service and the panel's Settings
tab) send a *partial* update, which is merged onto what is stored. The options flow
can't: Home Assistant stores whatever an options flow returns from
``async_create_entry`` as ``entry.options`` **verbatim**, and its form renders only
seven of the ten keys. Returning the submission as-is deleted every saved profile,
notification and dismissed companion on each save — with nothing on screen to say so,
because a missing key reads back as an empty list and notifications simply stopped
arriving. ``merge_flow_input`` turns that submission back into a partial update.

The guards at the bottom are the point: a new option key added to ``const.py`` and
forgotten anywhere else fails here rather than shipping. ``options.py`` imports Home
Assistant only under ``TYPE_CHECKING``, so all of this runs under a bare
``pip install pytest && pytest tests/unit``.
"""

from __future__ import annotations

import ast
import json
import types
from datetime import time
from pathlib import Path
from typing import Any

import hk_const as const  # type: ignore[import-not-found]
import hk_options as opts  # type: ignore[import-not-found]
import pytest

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"
_STRINGS = _COMPONENT / "strings.json"
_INIT_PY = _COMPONENT / "__init__.py"

# Every option key the integration defines, read off ``const.py`` rather than
# restated here — that is what makes the guards below notice a *new* one.
_CONST_OPTION_KEYS = frozenset(
    getattr(const, name) for name in dir(const) if name.startswith("OPTION_")
)

# An entry whose options are fully populated, every key holding a non-default value.
_FULL: dict[str, Any] = {
    const.OPTION_SYNC_PROBLEM_SENSORS: True,
    const.OPTION_ONE_OFF_RETENTION_DAYS: 30,
    const.OPTION_SHOPPING_LIST_ENTITY: "todo.kitchen_list",
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES: ["binary_sensor.sump"],
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES: ["dev-1"],
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS: ["kitchen"],
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS: ["label-1"],
    const.OPTION_DISMISSED_COMPANIONS: ["acme_vacuum"],
    const.OPTION_HIDDEN_PANEL_TABS: ["library"],
    const.OPTION_PROFILES: [
        {
            "id": "p1",
            "name": "My chores",
            "filter": {"status": "overdue"},
            # The to-do list this profile syncs onto rides *inside* the profile,
            # so the options flow has to preserve it along with everything else.
            "sync": {"entity_id": "todo.family", "two_way": False},
        }
    ],
    const.OPTION_NOTIFICATIONS: [
        {"id": "n1", "name": "Walk", "profile_id": "p1", "targets": []}
    ],
}

# What the options form submits when every field is filled in. Deliberately spelled
# out rather than derived, so a reader can see it covers exactly the seven fields the
# Configure dialog renders.
_SUBMISSION: dict[str, Any] = {
    const.OPTION_SYNC_PROBLEM_SENSORS: False,
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES: ["binary_sensor.other"],
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES: [],
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS: ["garage"],
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS: [],
    const.OPTION_ONE_OFF_RETENTION_DAYS: 7,
    const.OPTION_SHOPPING_LIST_ENTITY: "todo.shopping_list",
}


def _entry(options: dict[str, Any]) -> Any:
    """A stand-in config entry — ``options`` is all the helpers read."""
    return types.SimpleNamespace(options=options)


def _normalized() -> dict[str, Any]:
    """``_FULL`` as it reads back: the profile/notification normalizers fill in
    their own defaults, so a preserved value equals the *normalized* one, not the
    raw fixture."""
    return opts.current_options(_entry(_FULL))


# --------------------------------------------------------------------------- merge


def test_merge_flow_input_preserves_the_keys_the_form_does_not_render() -> None:
    """The bug: a save wiped profiles, notifications and dismissed companions."""
    before = opts.current_options(_entry(_FULL))

    merged = opts.merge_flow_input(_entry(_FULL), _SUBMISSION)

    for key in (
        const.OPTION_PROFILES,
        const.OPTION_NOTIFICATIONS,
        const.OPTION_DISMISSED_COMPANIONS,
        const.OPTION_HIDDEN_PANEL_TABS,
    ):
        assert merged[key] == before[key], f"{key} was not preserved"
    assert merged[const.OPTION_PROFILES], "sanity: the fixture must seed profiles"
    # A profile's to-do list sync has no key of its own to be preserved by, so it
    # is spelled out: the form deleting it would silently stop a synced list.
    assert merged[const.OPTION_PROFILES][0]["sync"] == {
        "entity_id": "todo.family",
        "two_way": False,
        "vanish_as_completed": True,
    }
    # ...and the fields the form *does* own took their new values.
    for key, value in _SUBMISSION.items():
        assert merged[key] == value


def test_clearing_the_shopping_picker_turns_the_mirror_off() -> None:
    """A ``FLOW_OPTIONS`` key missing from the submission was cleared, not omitted.

    The picker has no voluptuous ``default``, so clearing it drops the key entirely.
    A plain ``{**current, **user_input}`` merge would resurrect the old entity id and
    the mirror could never be turned off from the Configure dialog.
    """
    submission = {
        k: v for k, v in _SUBMISSION.items() if k != const.OPTION_SHOPPING_LIST_ENTITY
    }

    merged = opts.merge_flow_input(_entry(_FULL), submission)

    assert merged[const.OPTION_SHOPPING_LIST_ENTITY] == ""
    # The distinction is what matters: cleared *is not* the same as unrendered.
    assert merged[const.OPTION_PROFILES] == _normalized()[const.OPTION_PROFILES]


def test_clearing_the_other_flow_fields_resets_them() -> None:
    """Every ``FLOW_OPTIONS`` key follows the same cleared-means-empty rule."""
    merged = opts.merge_flow_input(_entry(_FULL), {})

    for key in opts.FLOW_OPTIONS:
        assert merged[key] == opts.current_options(_entry({}))[key], key
    assert (
        merged[const.OPTION_NOTIFICATIONS] == _normalized()[const.OPTION_NOTIFICATIONS]
    )


def test_merge_flow_input_normalizes_the_number_selector_float() -> None:
    """``NumberSelector`` submits ``7.0``; the stored shape is an int."""
    merged = opts.merge_flow_input(
        _entry(_FULL), {**_SUBMISSION, const.OPTION_ONE_OFF_RETENTION_DAYS: 7.0}
    )

    assert merged[const.OPTION_ONE_OFF_RETENTION_DAYS] == 7
    assert isinstance(merged[const.OPTION_ONE_OFF_RETENTION_DAYS], int)


def test_merge_flow_input_ignores_keys_the_form_does_not_own() -> None:
    """The form can only change what the form renders."""
    merged = opts.merge_flow_input(
        _entry(_FULL),
        {**_SUBMISSION, const.OPTION_PROFILES: [], const.OPTION_NOTIFICATIONS: []},
    )

    assert merged[const.OPTION_PROFILES] == _normalized()[const.OPTION_PROFILES]
    assert merged[const.OPTION_NOTIFICATIONS]


def test_merge_flow_input_returns_every_option_key() -> None:
    """The result replaces ``entry.options`` wholesale, so it must be complete."""
    merged = opts.merge_flow_input(_entry(_FULL), _SUBMISSION)

    assert set(merged) == set(opts.ALL_OPTIONS)


def test_merge_flow_input_normalizes_an_unusable_shopping_target() -> None:
    """A picker value outside the ``todo`` domain collapses to the off switch."""
    merged = opts.merge_flow_input(
        _entry(_FULL),
        {**_SUBMISSION, const.OPTION_SHOPPING_LIST_ENTITY: "sensor.not_a_list"},
    )

    assert merged[const.OPTION_SHOPPING_LIST_ENTITY] == ""


# -------------------------------------------------------------------------- guards


def test_every_option_constant_is_a_known_option() -> None:
    """A new ``OPTION_*`` must reach ``_empty_options``, or it is silently dropped.

    ``current_options`` and ``merge_flow_input`` both build from that factory, so a
    key it doesn't declare is invisible to every reader and deleted by the options
    flow's next save — exactly the class of bug this suite exists to prevent.
    """
    assert set(opts.ALL_OPTIONS) == _CONST_OPTION_KEYS
    assert set(opts.current_options(_entry({}))) == _CONST_OPTION_KEYS


# One non-default value per option key. A new option has no probe here, which fails
# the first assertion below and points at the second one.
_PROBES: dict[str, Any] = {
    const.OPTION_SYNC_PROBLEM_SENSORS: True,
    # These three default *on*, so their non-default probe is False.
    const.OPTION_ALLOW_SNOOZE: False,
    const.OPTION_ALLOW_SKIP: False,
    const.OPTION_ALLOW_DUE_TODAY: False,
    const.OPTION_ONE_OFF_RETENTION_DAYS: 9,
    const.OPTION_SHOPPING_LIST_ENTITY: "todo.somewhere",
    const.OPTION_SHOPPING_LINE_STYLE: "product_only",
    const.OPTION_DUE_TIME_MODE: "set_time",
    const.OPTION_DUE_TIME: "21:30",
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES: ["binary_sensor.x"],
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES: ["dev-x"],
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS: ["area-x"],
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS: ["label-x"],
    const.OPTION_DISMISSED_COMPANIONS: ["some_domain"],
    const.OPTION_HIDDEN_PANEL_TABS: ["library"],
    const.OPTION_PROFILES: [{"id": "px", "name": "X", "filter": {"status": "all"}}],
    const.OPTION_NOTIFICATIONS: [{"id": "nx", "name": "X", "profile_id": "px"}],
}


def test_every_option_has_a_probe() -> None:
    """Forces a new option to be considered by the coercion guard below."""
    assert set(_PROBES) == _CONST_OPTION_KEYS, "add a probe for the new option"


@pytest.mark.parametrize("key", sorted(_PROBES))
def test_every_option_has_a_normalize_branch(key: str) -> None:
    """An option with no coercion branch is ignored by every write path."""
    empty = opts.current_options(_entry({}))

    merged = opts.current_options(_entry({key: _PROBES[key]}))

    assert merged[key] != empty[key], f"_normalize ignores {key}"


def test_flow_options_are_real_options() -> None:
    """``FLOW_OPTIONS`` names actual option keys, once each."""
    assert set(opts.FLOW_OPTIONS) <= set(opts.ALL_OPTIONS)
    assert len(set(opts.FLOW_OPTIONS)) == len(opts.FLOW_OPTIONS)


def test_strings_json_covers_exactly_the_flow_form() -> None:
    """The form's labels and the form's fields are the same set.

    This is the drift guard that needs no Home Assistant: a field added to the
    Configure dialog needs a label, so eight labels against seven ``FLOW_OPTIONS``
    fails here — and so does the reverse, a tuple key with no field, which
    ``merge_flow_input`` would *clear* on every save.
    ``test_translations_parity.py`` extends the same check to every locale.
    """
    data = json.loads(_STRINGS.read_text("utf-8"))["options"]["step"]["init"]["data"]

    assert set(data) == set(opts.FLOW_OPTIONS)


def test_current_options_is_idempotent() -> None:
    """Reading back what a write stored must not change it again.

    ``async_set_options`` skips the write (and the reload) when ``merged == base``,
    which is only trustworthy while reading and writing agree on every key's shape.
    """
    once = opts.current_options(_entry(_FULL))

    assert opts.current_options(_entry(once)) == once


def test_current_options_coerces_stored_garbage() -> None:
    """Whatever is on disk, callers get the declared shape."""
    stored = {
        const.OPTION_SYNC_PROBLEM_SENSORS: "yes",
        const.OPTION_ONE_OFF_RETENTION_DAYS: "not-a-number",
        const.OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS: None,
        const.OPTION_DISMISSED_COMPANIONS: [1, 2],
    }

    result = opts.current_options(_entry(stored))

    assert result[const.OPTION_SYNC_PROBLEM_SENSORS] is True
    assert result[const.OPTION_ONE_OFF_RETENTION_DAYS] == 0
    assert result[const.OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS] == []
    assert result[const.OPTION_DISMISSED_COMPANIONS] == ["1", "2"]


def test_id_lists_drop_empty_entries() -> None:
    """No registry id is falsy, so a falsy entry is junk — and would stringify badly.

    Without the filter a ``None`` in an exclusion list is stored as the literal
    ``"None"``, which then sits in the entry forever matching nothing.
    """
    stored = {
        const.OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES: [
            "binary_sensor.real",
            None,
            "",
        ],
    }

    result = opts.current_options(_entry(stored))

    assert result[const.OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES] == [
        "binary_sensor.real"
    ]


def test_current_options_hands_out_fresh_lists() -> None:
    """Callers mutating a returned list must not corrupt the next read."""
    first = opts.current_options(_entry(_FULL))
    first[const.OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS].append("mutated")

    assert (
        "mutated"
        not in opts.current_options(_entry(_FULL))[
            const.OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS
        ]
    )


def _set_options_schema_keys() -> set[str]:
    """The option keys ``SET_OPTIONS_SCHEMA`` accepts, read out of ``__init__.py``.

    Parsed rather than imported: ``__init__.py`` pulls in the whole of Home
    Assistant, and this guard belongs in the tier that runs without it. Every entry
    is ``vol.Optional(OPTION_*)``, so the constant name is enough.
    """
    tree = ast.parse(_INIT_PY.read_text("utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "SET_OPTIONS_SCHEMA"
            for t in node.targets
        ):
            continue
        return {
            getattr(const, key.args[0].id)
            for key in ast.walk(node.value)
            if isinstance(key, ast.Call)
            and isinstance(key.func, ast.Attribute)
            and key.func.attr in {"Optional", "Required"}
            and key.args
            and isinstance(key.args[0], ast.Name)
        }
    raise AssertionError("SET_OPTIONS_SCHEMA not found in __init__.py")


def test_the_set_options_service_accepts_every_option() -> None:
    """The service is the canonical write path, so it must reach every key.

    An option the schema omits can't be set by an automation or a script at all —
    the panel's websocket command is only a UI shortcut, never the substitute.
    """
    assert _set_options_schema_keys() == _CONST_OPTION_KEYS


def test_the_defaults_change_nothing_for_an_unconfigured_entry() -> None:
    """An entry that has never been configured gets no surprises in either direction.

    Spelled out rather than compared against ``_empty_options``, which would be
    tautological. Each of these is a user-visible promise: syncing is opt-in, ``0``
    retention days keeps completed one-offs forever (any other number would start
    deleting them for people who never touched the setting), an empty shopping
    target leaves the sync off, a line keeps the reminder's own name, and a floating
    task keeps the time of its completion (the ``completion`` due time mode, #438).

    ``allow_snooze`` / ``allow_skip`` / ``allow_due_today`` are the ones that
    default **on**, and for the same reason the rest default off: nothing changes
    for someone who never opened the setting. All three verbs predate their switch,
    so defaulting any of them off would silently withdraw a feature from every
    existing install.
    """
    assert opts.current_options(_entry({})) == {
        "sync_problem_sensors": False,
        "allow_snooze": True,
        "allow_skip": True,
        "allow_due_today": True,
        "due_time_mode": "completion",
        "due_time": "08:00",
        "one_off_retention_days": 0,
        "shopping_list_entity": "",
        "shopping_line_style": "with_verb",
        "profiles": [],
        "notifications": [],
        "problem_sensor_exclude_entities": [],
        "problem_sensor_exclude_devices": [],
        "problem_sensor_exclude_areas": [],
        "problem_sensor_exclude_labels": [],
        "dismissed_companions": [],
        "hidden_panel_tabs": [],
    }


# ------------------------------------------------- the profile-in-use write guard


def _opts(profiles: list[Any], notifications: list[Any]) -> dict[str, Any]:
    """A normalized options document holding just the two lists the guard reads."""
    return opts.current_options(
        _entry(
            {const.OPTION_PROFILES: profiles, const.OPTION_NOTIFICATIONS: notifications}
        )
    )


_P1 = {"id": "p1", "name": "My chores", "filter": {"status": "overdue"}}
_P2 = {"id": "p2", "name": "Garden", "filter": {"status": "all"}}
_N_ON_P1 = {"id": "n1", "name": "Walk", "profile_id": "p1", "targets": []}
_N_ON_P2 = {"id": "n2", "name": "Weekend", "profile_id": "p2", "targets": []}


def test_removing_a_profile_a_notification_names_is_blocked() -> None:
    """The whole point: the save that would leave the notification with nothing.

    ``notifier._notification_profile`` reads a dangling ``profile_id`` back as "send
    nothing", so this save used to succeed and quietly stop the notification. The
    result names both sides, because the message has to say which profile and which
    notification.
    """
    base = _opts([_P1], [_N_ON_P1])
    merged = _opts([], [_N_ON_P1])
    assert opts.profile_removals_in_use(base, merged) == [("My chores", "Walk")]


def test_removing_a_profile_with_its_notifications_in_one_save_is_allowed() -> None:
    """Deleting both together is the *supported* way to get rid of a profile.

    The references are read out of ``merged``, never ``base`` — a notification the
    same save removes cannot be stranded by it. Three e2e specs tear down with
    exactly this call, so reading ``base`` here would break them.
    """
    base = _opts([_P1], [_N_ON_P1])
    merged = _opts([], [])
    assert opts.profile_removals_in_use(base, merged) == []


def test_a_save_that_does_not_send_profiles_removes_nothing() -> None:
    """``_normalize`` carries the stored list over, so nothing is missing from it."""
    base = _opts([_P1], [_N_ON_P1])
    merged = opts._normalize({const.OPTION_SYNC_PROBLEM_SENSORS: True}, base)
    assert opts.profile_removals_in_use(base, merged) == []


def test_renaming_a_profile_is_not_a_removal() -> None:
    """A rename keeps the id, and an id reference still resolves."""
    base = _opts([_P1], [_N_ON_P1])
    merged = _opts([{**_P1, "name": "House chores"}], [_N_ON_P1])
    assert opts.profile_removals_in_use(base, merged) == []


def test_a_profile_id_that_already_dangles_does_not_block_an_unrelated_save() -> None:
    """The state is designed, documented and reachable, so it must stay writable.

    A notification can already name a profile that is not there — options restored
    from a backup, or a service call that wrote notifications alone. That document
    has to keep saving, or the person can never edit their way out of it. Only a
    profile *this save* removes counts.
    """
    base = _opts([_P1], [_N_ON_P1, {"id": "n3", "name": "Ghost", "profile_id": "gone"}])
    merged = opts._normalize({const.OPTION_SYNC_PROBLEM_SENSORS: True}, base)
    assert opts.profile_removals_in_use(base, merged) == []


def test_a_notification_with_no_profile_is_never_a_blocker() -> None:
    """``profile_id: None`` means "every due task", so it names no profile."""
    base = _opts(
        [_P1], [{"id": "n1", "name": "All", "profile_id": None, "targets": []}]
    )
    merged = _opts([], [{"id": "n1", "name": "All", "profile_id": None, "targets": []}])
    assert opts.profile_removals_in_use(base, merged) == []


def test_removing_one_profile_of_two_reports_only_that_one() -> None:
    """A notification on a profile the save keeps is not in the way."""
    base = _opts([_P1, _P2], [_N_ON_P1, _N_ON_P2])
    merged = _opts([_P2], [_N_ON_P1, _N_ON_P2])
    assert opts.profile_removals_in_use(base, merged) == [("My chores", "Walk")]


def test_every_blocking_notification_is_reported_in_list_order() -> None:
    """Two notifications on one removed profile both belong in the message."""
    second = {"id": "n2", "name": "Evening", "profile_id": "p1", "targets": []}
    base = _opts([_P1], [_N_ON_P1, second])
    merged = _opts([], [_N_ON_P1, second])
    assert opts.profile_removals_in_use(base, merged) == [
        ("My chores", "Walk"),
        ("My chores", "Evening"),
    ]


def test_the_error_joins_and_de_duplicates_both_sides() -> None:
    """Both callers fill in the same two placeholders from these attributes.

    The profile name appears once however many notifications hold it, because the
    message reads "profile X is used by A, B", not "X, X". Both sides are joined the
    same way, so one save that clears two held profiles still reads as a list.
    """
    err = opts.ProfileInUseError([("My chores", "Walk"), ("My chores", "Evening")])
    assert err.profiles == "My chores"
    assert err.notifications == "Walk, Evening"

    two = opts.ProfileInUseError([("My chores", "Walk"), ("Garden", "Weekend")])
    assert two.profiles == "My chores, Garden"
    assert two.notifications == "Walk, Weekend"
    # The exception's own text carries both, for a log line or an unhandled raise —
    # the translated message the two callers build is separate from this.
    assert str(two) == "My chores, Garden: Walk, Weekend"


def test_removing_two_held_profiles_at_once_reports_both() -> None:
    """One save can clear several profiles, and each blocker belongs in the message."""
    base = _opts([_P1, _P2], [_N_ON_P1, _N_ON_P2])
    merged = _opts([], [_N_ON_P1, _N_ON_P2])
    assert opts.profile_removals_in_use(base, merged) == [
        ("My chores", "Walk"),
        ("Garden", "Weekend"),
    ]


def test_adding_a_profile_in_the_same_save_is_not_a_removal() -> None:
    """A profile only *merged* has was never in the before-set, so it drops out.

    Renaming by delete-and-add is the shape this has to get right: the new row is not
    a removal, and the old row still is.
    """
    base = _opts([_P1], [_N_ON_P1])
    merged = _opts([_P2], [_N_ON_P1])
    assert opts.profile_removals_in_use(base, merged) == [("My chores", "Walk")]


def test_a_profile_sent_without_an_id_reads_as_a_removal() -> None:
    """``normalize_profile`` mints a fresh uuid when ``id`` is missing.

    So a hand-written service call that re-sends its profiles without their ids reads
    as remove-then-add, and is refused. This narrows the ``set_options`` contract, and
    it is the case that used to strand the notification silently.
    """
    base = _opts([_P1], [_N_ON_P1])
    merged = _opts([{"name": "My chores", "filter": {"status": "overdue"}}], [_N_ON_P1])
    assert opts.profile_removals_in_use(base, merged) == [("My chores", "Walk")]


_N_BY_NAME = {"id": "n1", "name": "Walk", "profile_id": "My chores", "targets": []}


def test_b19_3_removing_a_profile_a_notification_names_by_name_is_blocked() -> None:
    """The notifier resolves a stored name too, so the guard must see that use."""
    base = _opts([_P1, _P2], [_N_BY_NAME])
    merged = _opts([_P2], [_N_BY_NAME])
    assert opts.profile_removals_in_use(base, merged) == [("My chores", "Walk")]


def test_b19_3_renaming_a_profile_a_notification_names_by_name_is_blocked() -> None:
    base = _opts([_P1], [_N_BY_NAME])
    merged = _opts([{**_P1, "name": "House chores"}], [_N_BY_NAME])
    assert opts.profile_removals_in_use(base, merged) == [("My chores", "Walk")]


def test_b19_3_a_name_reference_that_still_resolves_is_not_blocked() -> None:
    base = _opts([_P1, _P2], [_N_BY_NAME])
    # Another profile is removed, and the named one keeps its name.
    merged = _opts([_P1], [_N_BY_NAME])
    assert opts.profile_removals_in_use(base, merged) == []
    # Re-sent without its id: a new id, but the name still resolves.
    resent = _opts(
        [{"name": "My chores", "filter": {"status": "overdue"}}], [_N_BY_NAME]
    )
    assert opts.profile_removals_in_use(base, resent) == []


def test_the_options_flow_cannot_remove_a_profile() -> None:
    """``profiles`` is not in ``FLOW_OPTIONS``, so the Configure dialog never sends it.

    That is why the guard lives on ``async_set_options`` alone: a flow submission
    cannot reach it.
    """
    assert const.OPTION_PROFILES not in opts.FLOW_OPTIONS
    base = opts.current_options(_entry(_FULL))
    merged = opts.merge_flow_input(_entry(_FULL), _SUBMISSION)
    assert merged[const.OPTION_PROFILES] == base[const.OPTION_PROFILES]
    assert opts.profile_removals_in_use(base, merged) == []


# ------------------------------------------------------- retention bounds (B19-1)


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (0, 0),
        (-5, 0),
        (1, 1),
        (30.9, 30),
        (const.MAX_ONE_OFF_RETENTION_DAYS, const.MAX_ONE_OFF_RETENTION_DAYS),
        (const.MAX_ONE_OFF_RETENTION_DAYS + 1, const.MAX_ONE_OFF_RETENTION_DAYS),
        (9999999, const.MAX_ONE_OFF_RETENTION_DAYS),
        (float("inf"), 0),
        ("junk", 0),
        (None, 0),
    ],
)
def test_b19_1_retention_reads_back_inside_its_bounds(
    stored: Any, expected: int
) -> None:
    """B19-1: a retention of millions of days overflowed the purge's date arithmetic
    and stopped the entry from loading. The read path clamps it, so a value stored
    before the clamp existed loads again with no user action."""
    result = opts.current_options(_entry({const.OPTION_ONE_OFF_RETENTION_DAYS: stored}))
    assert result[const.OPTION_ONE_OFF_RETENTION_DAYS] == expected


def test_b19_1_the_maximum_is_ten_years() -> None:
    """B19-1: the options flow offered at most 3650. The other paths now agree."""
    assert const.MAX_ONE_OFF_RETENTION_DAYS == 3650


# --------------------------------------------- lowered retention grace (X12-1)


@pytest.mark.parametrize(
    ("old", "new", "lowered"),
    [
        (0, 3, True),  # forever -> 3 days deletes more
        (0, 1, True),  # the smallest positive value counts too
        (5, 1, True),
        (30, 3, True),
        (30, 29, True),
        (3, 30, False),
        (30, 30, False),
        (30, 0, False),  # back to forever deletes nothing
        (0, 0, False),
    ],
)
def test_x12_1_retention_lowered(old: int, new: int, lowered: bool) -> None:
    """X12-1: only a change that can delete more tasks waits for a tick."""
    assert opts.retention_lowered(old, new) is lowered


def test_x12_1_the_grace_is_taken_once() -> None:
    opts._RETENTION_GRACE.add("grace-entry")
    assert opts.take_retention_grace("grace-entry") is True
    assert opts.take_retention_grace("grace-entry") is False
    assert opts.take_retention_grace("other-entry") is False


# ── X03-8: device ids after the Home Assistant 2026.8 device split ────────────
DEAD = "dead_composite"
LIVE = "live_device"


def _device_options() -> dict[str, Any]:
    return {
        const.OPTION_SYNC_PROBLEM_SENSORS: True,
        const.OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES: [DEAD, "keep"],
        const.OPTION_PROFILES: [
            {"id": "p1", "filter": {"devices": [DEAD], "exclude_devices": ["x"]}},
            {"id": "p2", "filter": {"devices": [], "exclude_devices": [DEAD, LIVE]}},
            {"id": "p3"},  # no filter block
            "not a profile",
        ],
    }


def test_x03_8_device_ids_in_options_finds_every_device_reference():
    assert opts.device_ids_in_options(_device_options()) == {DEAD, "keep", "x", LIVE}
    assert opts.device_ids_in_options({}) == set()


def test_x03_8_repoint_device_ids_moves_exclusions_and_profile_filters():
    stored = _device_options()
    before = json.dumps(stored, sort_keys=True)
    new = opts.repoint_device_ids(stored, {DEAD: LIVE})
    assert new == {
        const.OPTION_SYNC_PROBLEM_SENSORS: True,
        const.OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES: [LIVE, "keep"],
        const.OPTION_PROFILES: [
            {"id": "p1", "filter": {"devices": [LIVE], "exclude_devices": ["x"]}},
            # The dead id and the live id are one device now: listed once.
            {"id": "p2", "filter": {"devices": [], "exclude_devices": [LIVE]}},
            {"id": "p3"},
            "not a profile",
        ],
    }
    # The stored options are not changed in place.
    assert json.dumps(stored, sort_keys=True) == before


def test_x03_8_repoint_device_ids_reports_no_change():
    assert opts.repoint_device_ids(_device_options(), {"other": LIVE}) is None
    assert opts.repoint_device_ids({}, {DEAD: LIVE}) is None


def test_x03_8_repoint_device_ids_moves_only_a_profile_filter():
    stored = {
        const.OPTION_PROFILES: [{"id": "p", "filter": {"exclude_devices": [DEAD]}}]
    }
    assert opts.repoint_device_ids(stored, {DEAD: LIVE}) == {
        const.OPTION_PROFILES: [{"id": "p", "filter": {"exclude_devices": [LIVE]}}]
    }


def test_x03_8_repoint_device_ids_moves_only_the_exclusions():
    stored = {const.OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES: [DEAD]}
    assert opts.repoint_device_ids(stored, {DEAD: LIVE}) == {
        const.OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES: [LIVE]
    }


def test_x03_8_device_ids_in_options_reads_past_a_bad_profile():
    stored = {
        const.OPTION_PROFILES: [
            "not a profile",
            {"id": "p0"},
            {"id": "p", "filter": {"devices": [DEAD]}},
        ]
    }
    assert opts.device_ids_in_options(stored) == {DEAD}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("07:30", "07:30"),
        ("7:05", "07:05"),
        ("21:30:59", "21:30"),
        ("23:59", "23:59"),
        ("00:00", "00:00"),
        ("24:00", "08:00"),
        ("12:60", "08:00"),
        ("noon", "08:00"),
        ("12", "08:00"),
        ("1:2:3:4", "08:00"),
        ("-1:30", "08:00"),
        ("", "08:00"),
        (None, "08:00"),
    ],
)
def test_normalize_due_time(raw: Any, expected: str) -> None:
    """A due time reads as ``HH:MM``; anything that is not a time reads as 08:00."""
    assert opts.normalize_due_time(raw) == expected


def test_normalize_due_time_accepts_a_time_object() -> None:
    assert opts.normalize_due_time(time(6, 5, 30)) == "06:05"


def test_an_unknown_due_time_mode_reads_as_completion() -> None:
    merged = opts.current_options(_entry({const.OPTION_DUE_TIME_MODE: "sometimes"}))
    assert merged[const.OPTION_DUE_TIME_MODE] == "completion"


def test_due_time_of() -> None:
    """Only the ``set_time`` mode gives a due time; ``completion`` gives ``None``."""
    assert (
        opts.due_time_of({"due_time_mode": "completion", "due_time": "07:15"}) is None
    )
    assert opts.due_time_of({}) is None
    assert opts.due_time_of({"due_time_mode": "set_time", "due_time": "07:15"}) == time(
        7, 15
    )
    assert opts.due_time_of({"due_time_mode": "set_time", "due_time": "x"}) == time(8)
