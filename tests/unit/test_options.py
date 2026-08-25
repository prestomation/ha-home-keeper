"""The config-entry options merge rules, and the drift guards around them.

Three surfaces write ``entry.options`` and they share one coercion table in
``options.py``. Two of them (the ``set_options`` service and the panel's Settings
tab) send a *partial* update, which is merged onto what is stored. The options flow
can't: Home Assistant stores whatever an options flow returns from
``async_create_entry`` as ``entry.options`` **verbatim**, and its form renders only
seven of the eleven keys. Returning the submission as-is deleted every saved profile,
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
    const.OPTION_PROFILES: [
        {"id": "p1", "name": "My chores", "filter": {"status": "overdue"}}
    ],
    const.OPTION_NOTIFICATIONS: [
        {"id": "n1", "name": "Walk", "profile_id": "p1", "targets": []}
    ],
    const.OPTION_TASK_MIRRORS: [
        {"id": "m1", "entity_id": "todo.family", "profile_id": "p1"}
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
    ):
        assert merged[key] == before[key], f"{key} was not preserved"
    assert merged[const.OPTION_PROFILES], "sanity: the fixture must seed profiles"
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
    const.OPTION_ONE_OFF_RETENTION_DAYS: 9,
    const.OPTION_SHOPPING_LIST_ENTITY: "todo.somewhere",
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES: ["binary_sensor.x"],
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES: ["dev-x"],
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS: ["area-x"],
    const.OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS: ["label-x"],
    const.OPTION_DISMISSED_COMPANIONS: ["some_domain"],
    const.OPTION_PROFILES: [{"id": "px", "name": "X", "filter": {"status": "all"}}],
    const.OPTION_NOTIFICATIONS: [{"id": "nx", "name": "X", "profile_id": "px"}],
    const.OPTION_TASK_MIRRORS: [{"id": "mx", "entity_id": "todo.family"}],
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


def test_the_defaults_are_all_off() -> None:
    """An entry that has never been configured behaves as if nothing is enabled.

    Spelled out rather than compared against ``_empty_options``, which would be
    tautological. Each of these is a user-visible promise: syncing is opt-in, ``0``
    retention days keeps completed one-offs forever (any other number would start
    deleting them for people who never touched the setting), and an empty shopping
    target leaves the mirror off.
    """
    assert opts.current_options(_entry({})) == {
        "sync_problem_sensors": False,
        "one_off_retention_days": 0,
        "shopping_list_entity": "",
        "profiles": [],
        "notifications": [],
        "task_mirrors": [],
        "problem_sensor_exclude_entities": [],
        "problem_sensor_exclude_devices": [],
        "problem_sensor_exclude_areas": [],
        "problem_sensor_exclude_labels": [],
        "dismissed_companions": [],
    }
