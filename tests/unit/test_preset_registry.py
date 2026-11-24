"""The check of a catalog row, and the registry of companion presets.

``preset_registry.validate_row`` is the 1 check of the catalog format. The shipped
catalog passes it here, and a companion's rows pass it at registration. The property
tests at the end draw valid rows and broken rows.

Run just the property tests: `pytest tests/unit -m property`.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import hk_declarative_companions as dc
import hk_declarative_presets as presets
import hk_declarative_presets_catalog as catalog
import hk_events as events
import hk_preset_registry as pr
import pytest
from asserts import raises_exactly
from hk_const import (
    EVENT_PRESETS_REGISTERED,
    EVENT_PRESETS_REMOVED,
    MAX_COMPANIONS,
)
from hypothesis import example, given, settings
from hypothesis import strategies as st


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "domain": "tesla_fleet",
        "brand": "Tesla",
        "icon": "mdi:car-wrench",
        "duties": [
            {
                "duty": "change_engine_oil",
                "shape": "percent_low",
                "keys": ["oil_life"],
                "limit": 15,
            },
            {
                "duty": "change_engine_oil",
                "shape": "alert",
                "platform": "binary_sensor",
                "keys": ["service_due"],
                "state": "on",
            },
        ],
    }
    row.update(over)
    return row


_NAMES = {
    "change_engine_oil": {"en": "Change the engine oil", "de": "Motoröl wechseln"}
}


def _register(rows: list[dict[str, Any]] | None = None, **kw: Any) -> pr.Registration:
    return pr.build_registration(
        kw.get("domain", "car_keeper"),
        [_row()] if rows is None else rows,
        kw.get("duty_names", _NAMES),
    )


# ── The shipped catalog passes the same check ────────────────────────────────


def test_every_shipped_row_passes_the_one_check():
    for index, row in enumerate(catalog.INTEGRATIONS):
        assert pr.validate_row(row, f"catalog[{index}]", builtin=True) == row


def test_a_shipped_row_without_its_pin_is_still_a_valid_companion_row():
    row = {
        k: v
        for k, v in catalog.INTEGRATIONS[0].items()
        if k not in {"source", "verified"}
    }
    assert pr.validate_row(row) == row


def test_a_companion_row_cannot_carry_the_upstream_pin():
    row = dict(catalog.INTEGRATIONS[0])
    with raises_exactly(pr.PresetRowError, "row.source: is not a known key"):
        pr.validate_row(row)


# ── A registration ───────────────────────────────────────────────────────────


def test_a_registration_builds_namespaced_presets_with_the_shipped_builder():
    reg = _register()
    assert reg.preset_ids == [
        "car_keeper/tesla_fleet_percent_low",
        "car_keeper/tesla_fleet_alert_binary_sensor_on",
    ]
    low, alert = reg.presets
    assert low["source"] == "companion"
    assert low["provided_by"] == "car_keeper"
    assert low["requires_integration"] == "tesla_fleet"
    assert low["brand"] == "Tesla"
    assert low["name_args"] == {"integration": "Tesla"}
    assert low["limit"] == {"kind": "percent", "value": 15, "above": False}
    spec = low["default_spec"]
    assert spec["preset_id"] == "car_keeper/tesla_fleet_percent_low"
    assert spec["name"] == "Tesla: parts and supplies running low"
    assert spec["selection"]["target_integration"] == "tesla_fleet"
    assert spec["selection"]["translation_keys"] == ["oil_life"]
    assert spec["trigger"] == {
        "mode": "threshold",
        "comparison": "<",
        "value": 15,
        "clear_on_recover": True,
    }
    assert spec["task_template"]["task_names"] == {"oil_life": "Change the engine oil"}
    assert alert["default_spec"]["trigger"] == {
        "mode": "state",
        "state": "on",
        "clear_on_recover": True,
    }
    assert alert["default_spec"]["selection"]["domain"] == "binary_sensor"


def test_a_registration_text_falls_back_to_english_per_language():
    reg = _register()
    names = reg.texts["car_keeper/tesla_fleet_percent_low"]["task_names"]
    assert sorted(names) == sorted(presets.LANGS)
    assert names["de"] == {"oil_life": "Motoröl wechseln"}
    assert names["fr"] == {"oil_life": "Change the engine oil"}


def test_a_companion_name_wins_only_for_its_own_rows():
    from hk_declarative_preset_text import DUTY_NAMES

    before = copy.deepcopy(DUTY_NAMES["replace_filter"])
    reg = _register(
        [
            _row(
                duties=[
                    {
                        "duty": "replace_filter",
                        "shape": "percent_low",
                        "keys": ["f"],
                        "limit": 5,
                    }
                ]
            )
        ],
        duty_names={"replace_filter": {"en": "Swap the cabin filter"}},
    )
    names = reg.presets[0]["default_spec"]["task_template"]["task_names"]
    assert names == {"f": "Swap the cabin filter"}
    assert DUTY_NAMES["replace_filter"] == before
    shipped = next(p for p in presets.CATALOG_PRESETS if p["id"] == "dreo_percent_low")
    assert shipped["default_spec"]["task_template"]["task_names"] == {
        "filter_life": before["en"]
    }


def test_a_shipped_duty_needs_no_duty_names():
    reg = _register(
        [
            _row(
                duties=[
                    {
                        "duty": "replace_filter",
                        "shape": "percent_low",
                        "keys": ["f"],
                        "limit": 5,
                    }
                ]
            )
        ],
        duty_names=None,
    )
    tables = reg.texts[reg.preset_ids[0]]["task_names"]
    from hk_declarative_preset_text import DUTY_NAMES

    assert tables["de"] == {"f": DUTY_NAMES["replace_filter"]["de"]}


def test_every_built_preset_is_a_spec_the_add_service_takes():
    for preset in _register().presets:
        dc.normalize_declarative_companion(preset["default_spec"])


def test_a_companion_id_never_has_the_id_of_a_shipped_preset():
    shipped = {p["id"] for p in presets.CATALOG_PRESETS}
    assert not any(pr.ID_SEPARATOR in i for i in shipped)
    # A row for an integration that the catalog has, with the same shape.
    row = _row(
        domain="roborock",
        duties=[
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["k"],
                "limit": 5,
            }
        ],
    )
    reg = _register([row])
    assert reg.preset_ids == ["car_keeper/roborock_percent_low"]
    assert "roborock_percent_low" not in reg.preset_ids


# ── Each refusal names its field ─────────────────────────────────────────────


def _duty(**over: Any) -> dict[str, Any]:
    duty: dict[str, Any] = {
        "duty": "change_engine_oil",
        "shape": "percent_low",
        "keys": ["oil_life"],
        "limit": 15,
    }
    duty.update(over)
    return {k: v for k, v in duty.items() if v is not _DROP}


_DROP = object()

_BAD_ROWS: list[tuple[Any, str]] = [
    ("not a row", "rows[0]: must be a mapping"),
    (_row(extra=1), "rows[0].extra: is not a known key"),
    (_row(domain="Tesla"), "rows[0].domain: must match [a-z0-9_]{1,50}"),
    (_row(domain="a" * 51), "rows[0].domain: must match [a-z0-9_]{1,50}"),
    (_row(domain=None), "rows[0].domain: must match [a-z0-9_]{1,50}"),
    (_row(brand=""), "rows[0].brand: must be text"),
    (_row(brand=" "), "rows[0].brand: must be text"),
    (_row(brand=3), "rows[0].brand: must be text"),
    (_row(brand="b" * 51), "rows[0].brand: must be at most 50 characters"),
    (
        _row(brand="{{ x }}"),
        "rows[0].brand: must not hold braces or control characters",
    ),
    (_row(brand="a\nb"), "rows[0].brand: must not hold braces or control characters"),
    (_row(icon="car"), "rows[0].icon: must match mdi:[a-z0-9-]{1,60}"),
    (_row(icon="mdi:" + "a" * 61), "rows[0].icon: must match mdi:[a-z0-9-]{1,60}"),
    (_row(duties=[]), "rows[0].duties: must be a list that is not empty"),
    (_row(duties={}), "rows[0].duties: must be a list that is not empty"),
    (
        _row(duties=[_duty(keys=[f"k{i}"]) for i in range(pr.MAX_DUTIES + 1)]),
        "rows[0].duties: must have at most 20 items",
    ),
    (_row(duties=["x"]), "rows[0].duties[0]: must be a mapping"),
    (_row(duties=[_duty(extra=1)]), "rows[0].duties[0].extra: is not a known key"),
    (
        _row(duties=[_duty(duty="nope")]),
        "rows[0].duties[0].duty: must name a known duty",
    ),
    (
        _row(duties=[_duty(duty=["x"])]),
        "rows[0].duties[0].duty: must name a known duty",
    ),
    (
        _row(duties=[_duty(shape="distance")]),
        "rows[0].duties[0].shape: must be one of " + ", ".join(presets.SHAPES),
    ),
    (
        _row(duties=[_duty(platform="number")]),
        "rows[0].duties[0].platform: must be sensor or binary_sensor",
    ),
    (
        _row(duties=[_duty(keys=[])]),
        "rows[0].duties[0].keys: must be a list that is not empty",
    ),
    (
        _row(duties=[_duty(keys="oil")]),
        "rows[0].duties[0].keys: must be a list that is not empty",
    ),
    (
        _row(duties=[_duty(keys=[f"k{i}" for i in range(pr.MAX_KEYS + 1)])]),
        "rows[0].duties[0].keys: must have at most 20 items",
    ),
    (
        _row(duties=[_duty(keys=["Oil"])]),
        "rows[0].duties[0].keys[0]: must match [a-z0-9_]{1,64}",
    ),
    (
        _row(duties=[_duty(keys=["ok", "x'}}"])]),
        "rows[0].duties[0].keys[1]: must match [a-z0-9_]{1,64}",
    ),
    (
        _row(duties=[_duty(keys=["a", "a"])]),
        "rows[0].duties[0].keys: must not repeat a key",
    ),
    (
        _row(duties=[_duty(keys=["a"]), _duty(keys=["a"], shape="reading_high")]),
        "rows[0].duties[1].keys: key a is in 2 duties",
    ),
    (_row(duties=[_duty(limit=_DROP)]), "rows[0].duties[0].limit: must be a number"),
    (_row(duties=[_duty(limit="5")]), "rows[0].duties[0].limit: must be a number"),
    (_row(duties=[_duty(limit=True)]), "rows[0].duties[0].limit: must be a number"),
    (
        _row(duties=[_duty(limit=0)]),
        "rows[0].duties[0].limit: must be above 0 and 1000000 at most",
    ),
    (
        _row(duties=[_duty(limit=-1)]),
        "rows[0].duties[0].limit: must be above 0 and 1000000 at most",
    ),
    (
        _row(duties=[_duty(limit=math.nan)]),
        "rows[0].duties[0].limit: must be above 0 and 1000000 at most",
    ),
    (
        _row(duties=[_duty(limit=math.inf, shape="wear_high")]),
        "rows[0].duties[0].limit: must be above 0 and 1000000 at most",
    ),
    (
        _row(duties=[_duty(limit=1_000_001, shape="wear_high")]),
        "rows[0].duties[0].limit: must be above 0 and 1000000 at most",
    ),
    (
        _row(duties=[_duty(limit=100)]),
        "rows[0].duties[0].limit: a percentage must be below 100",
    ),
    (
        _row(duties=[_duty(shape="alert", state="on")]),
        "rows[0].duties[0].limit: an alert has no limit",
    ),
    (
        _row(duties=[_duty(shape="alert", limit=_DROP)]),
        "rows[0].duties[0].state: must match [A-Za-z0-9_-]{1,32}",
    ),
    (
        _row(duties=[_duty(shape="alert", limit=_DROP, state=True)]),
        "rows[0].duties[0].state: must match [A-Za-z0-9_-]{1,32}",
    ),
    (
        _row(duties=[_duty(shape="alert", limit=_DROP, state="a b")]),
        "rows[0].duties[0].state: must match [A-Za-z0-9_-]{1,32}",
    ),
    (
        _row(duties=[_duty(state="on")]),
        "rows[0].duties[0].state: only an alert has a state",
    ),
    (
        _row(duties=[_duty(device_class="Enum")]),
        "rows[0].duties[0].device_class: must match [a-z0-9_]{1,32}",
    ),
    (
        _row(duties=[_duty(counted="yes")]),
        "rows[0].duties[0].counted: must be true or false",
    ),
    (
        _row(duties=[_duty(per_instance=1)]),
        "rows[0].duties[0].per_instance: must be true or false",
    ),
]


@pytest.mark.parametrize(("row", "message"), _BAD_ROWS)
def test_each_bad_row_is_refused_with_its_path(row, message):
    with raises_exactly(pr.PresetRowError, message):
        _register([row])


@pytest.mark.parametrize(
    ("domain", "rows", "names", "message"),
    [
        ("Car", [_row()], _NAMES, "domain: must match [a-z0-9_]{1,50}"),
        ("car/x", [_row()], _NAMES, "domain: must match [a-z0-9_]{1,50}"),
        (None, [_row()], _NAMES, "domain: must match [a-z0-9_]{1,50}"),
        ("car", [], _NAMES, "rows: must be a list that is not empty"),
        ("car", None, _NAMES, "rows: must be a list that is not empty"),
        (
            "car",
            [_row(domain=f"d{i}") for i in range(pr.MAX_ROWS + 1)],
            _NAMES,
            "rows: must have at most 20 items",
        ),
        ("car", [_row(), _row()], _NAMES, "rows[1].domain: must not repeat a domain"),
        ("car", [_row()], [], "duty_names: must be a mapping"),
        (
            "car",
            [_row()],
            {"Bad": {"en": "x"}},
            "duty_names.Bad: must match [a-z0-9_]{1,50}",
        ),
        ("car", [_row()], {"d": "x"}, "duty_names.d: must be a mapping"),
        ("car", [_row()], {"d": {"de": "x"}}, "duty_names.d.en: is required"),
        (
            "car",
            [_row()],
            {"d": {"en": "x", "xx": "y"}},
            "duty_names.d.xx: is not a known language",
        ),
        ("car", [_row()], {"d": {"en": ""}}, "duty_names.d.en: must be text"),
        (
            "car",
            [_row()],
            {"d": {"en": "x" * 101}},
            "duty_names.d.en: must be at most 100 characters",
        ),
        (
            "car",
            [_row()],
            {"d": {"en": "{{ states('x') }}"}},
            "duty_names.d.en: must not hold braces or control characters",
        ),
        (
            "car",
            [_row()],
            {f"d{i}": {"en": "x"} for i in range(pr.MAX_DUTY_NAMES + 1)},
            "duty_names: must have at most 50 duties",
        ),
    ],
)
def test_each_bad_registration_is_refused_with_its_path(domain, rows, names, message):
    with raises_exactly(pr.PresetRowError, message):
        pr.build_registration(domain, rows, names)


def test_a_duty_named_only_by_the_companion_needs_its_duty_names():
    with raises_exactly(
        pr.PresetRowError, "rows[0].duties[0].duty: must name a known duty"
    ):
        _register(duty_names=None)


def test_an_id_over_the_spec_field_is_refused():
    row = _row(
        domain="d" * 50, duties=[_duty(shape="alert", limit=_DROP, state="s" * 32)]
    )
    message = (
        "rows: preset id "
        + "car_keeper_long_name_abc/"
        + "d" * 50
        + "_alert_"
        + "s" * 32
        + " is over 100 characters"
    )
    with raises_exactly(pr.PresetRowError, message):
        pr.build_registration("car_keeper_long_name_abc", [row], _NAMES)


def test_2_groups_that_make_1_id_are_refused():
    row = _row(
        duties=[
            _duty(keys=["a"], device_class="enum"),
            _duty(keys=["b"], device_class="battery"),
        ]
    )
    with raises_exactly(
        pr.PresetRowError,
        "rows: preset id car_keeper/tesla_fleet_percent_low is made twice",
    ):
        _register([row])


def test_a_preset_that_the_spec_check_refuses_is_refused():
    # 6 duties of 20 keys in 1 group: 120 keys, over the spec limit of 100.
    duties = [_duty(keys=[f"k{d}_{i}" for i in range(20)]) for d in range(6)]
    with pytest.raises(pr.PresetRowError) as info:
        _register([_row(duties=duties)])
    assert info.value.path == "rows"
    assert str(info.value).startswith(
        "rows: preset car_keeper/tesla_fleet_percent_low: "
    )


def test_the_error_keeps_the_path_and_the_reason():
    err = pr.PresetRowError("rows[0].icon", "bad")
    assert (err.path, err.reason, str(err)) == (
        "rows[0].icon",
        "bad",
        "rows[0].icon: bad",
    )


def test_the_check_does_not_change_its_input():
    rows = [_row()]
    names = copy.deepcopy(_NAMES)
    before = copy.deepcopy((rows, names))
    _register(rows, duty_names=names)
    assert (rows, names) == before


def test_validate_duty_keeps_only_the_keys_it_was_given():
    clean = pr.validate_duty(
        {"duty": "replace_filter", "shape": "wear_high", "keys": ["k"], "limit": 5},
        "d",
        {"replace_filter": {}},
    )
    assert clean == {
        "duty": "replace_filter",
        "shape": "wear_high",
        "keys": ["k"],
        "limit": 5,
    }


# ── A config entry change of a companion ─────────────────────────────────────


@pytest.mark.parametrize(
    ("removed", "state", "other_loaded", "drops"),
    [
        (False, "loaded", False, False),
        (False, "setup_in_progress", False, False),
        (False, "setup_retry", False, False),
        (False, "not_loaded", False, True),
        (False, "setup_error", False, True),
        (False, "failed_unload", False, True),
        (True, "loaded", False, True),
        (True, "not_loaded", False, True),
        (True, "not_loaded", True, False),
        (False, "not_loaded", True, False),
    ],
)
def test_an_entry_change_drops_the_presets_only_when_the_companion_is_gone(
    removed, state, other_loaded, drops
):
    assert pr.drops_on_entry_change(removed, state, other_loaded) is drops


# ── The transition function ──────────────────────────────────────────────────


def test_a_first_registration_fires_registered_with_its_ids():
    reg = _register()
    result = pr.transition(pr.PresetRegistry(), pr.Register(reg))
    assert list(result.registry.registrations) == ["car_keeper"]
    assert result.events == (
        (
            EVENT_PRESETS_REGISTERED,
            {"domain": "car_keeper", "preset_ids": reg.preset_ids},
        ),
    )


def test_the_same_registration_again_fires_nothing():
    state = pr.transition(pr.PresetRegistry(), pr.Register(_register())).registry
    again = pr.transition(state, pr.Register(_register()))
    assert again.events == ()
    assert again.registry is state


def test_a_new_set_replaces_the_old_one_and_fires_registered():
    state = pr.transition(pr.PresetRegistry(), pr.Register(_register())).registry
    smaller = _register([_row(duties=[_duty()])])
    result = pr.transition(state, pr.Register(smaller))
    assert result.registry.registrations["car_keeper"] is smaller
    assert result.events == (
        (
            EVENT_PRESETS_REGISTERED,
            {
                "domain": "car_keeper",
                "preset_ids": ["car_keeper/tesla_fleet_percent_low"],
            },
        ),
    )


def test_unregister_fires_removed_with_the_old_ids():
    reg = _register()
    state = pr.transition(pr.PresetRegistry(), pr.Register(reg)).registry
    result = pr.transition(state, pr.Unregister("car_keeper"))
    assert result.registry.registrations == {}
    assert result.events == (
        (EVENT_PRESETS_REMOVED, {"domain": "car_keeper", "preset_ids": reg.preset_ids}),
    )


def test_unregister_of_an_unknown_domain_changes_nothing():
    state = pr.PresetRegistry()
    result = pr.transition(state, pr.Unregister("nobody"))
    assert result.registry is state
    assert result.events == ()


def test_a_new_domain_past_the_companion_limit_is_refused():
    state = pr.PresetRegistry()
    for i in range(MAX_COMPANIONS):
        state = pr.transition(state, pr.Register(_register(domain=f"c{i}"))).registry
    with raises_exactly(pr.PresetRowError, "domain: the 50-companion limit is reached"):
        pr.transition(state, pr.Register(_register(domain="one_more")))
    # A registered domain can still change its set at the limit.
    smaller = _register([_row(duties=[_duty()])], domain="c0")
    assert (
        pr.transition(state, pr.Register(smaller)).registry.registrations["c0"]
        is smaller
    )


def test_the_transition_never_changes_the_old_state():
    state = pr.transition(pr.PresetRegistry(), pr.Register(_register())).registry
    pr.transition(state, pr.Unregister("car_keeper"))
    assert list(state.registrations) == ["car_keeper"]


def test_the_event_payload_is_the_shared_builder():
    assert events.presets_event_data("a", ["a/x"]) == {
        "domain": "a",
        "preset_ids": ["a/x"],
    }
    ids = ["a/x"]
    assert events.presets_event_data("a", ids)["preset_ids"] is not ids


# ── The merged list ──────────────────────────────────────────────────────────


def test_the_merged_list_is_the_shipped_list_then_each_companion_in_order():
    state = pr.PresetRegistry()
    first = _register(domain="zeta")
    second = _register(domain="alpha")
    state = pr.transition(state, pr.Register(first)).registry
    state = pr.transition(state, pr.Register(second)).registry
    merged = pr.merged_presets(state)
    shipped = presets.CATALOG_PRESETS
    assert [p["id"] for p in merged] == (
        [p["id"] for p in shipped] + first.preset_ids + second.preset_ids
    )
    assert all(p["source"] == "builtin" for p in merged[: len(shipped)])
    assert all("source" not in p for p in shipped)
    assert merged[0]["default_spec"] is shipped[0]["default_spec"]


def test_an_empty_registry_merges_to_the_shipped_list():
    merged = pr.merged_presets(pr.PresetRegistry())
    assert [p["id"] for p in merged] == [p["id"] for p in presets.CATALOG_PRESETS]


# ── Properties ───────────────────────────────────────────────────────────────

_KEYS = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)
_NUMBERS = st.floats(min_value=0.5, max_value=99, allow_nan=False) | st.integers(1, 99)


@st.composite
def duties(draw: st.DrawFn, keys_used: set[str]) -> dict[str, Any]:
    shape = draw(st.sampled_from(sorted(presets.SHAPES)))
    keys = draw(
        st.lists(
            _KEYS.filter(lambda k: k not in keys_used),
            min_size=1,
            max_size=3,
            unique=True,
        )
    )
    keys_used.update(keys)
    duty: dict[str, Any] = {
        "duty": draw(st.sampled_from(["change_engine_oil", "replace_filter"])),
        "shape": shape,
        "keys": keys,
    }
    if shape == "alert":
        duty["state"] = draw(st.from_regex(r"[A-Za-z0-9_-]{1,8}", fullmatch=True))
    else:
        duty["limit"] = draw(_NUMBERS)
    if draw(st.booleans()):
        duty["platform"] = draw(st.sampled_from(pr.PLATFORMS))
    for flag in ("counted", "per_instance"):
        if draw(st.booleans()):
            duty[flag] = draw(st.booleans())
    return duty


@st.composite
def rows(draw: st.DrawFn) -> list[dict[str, Any]]:
    domains = draw(st.lists(_KEYS, min_size=1, max_size=3, unique=True))
    out = []
    for domain in domains:
        used: set[str] = set()
        # 1 duty per shape keeps each built id unique.
        shapes = draw(
            st.lists(
                st.sampled_from(sorted(presets.SHAPES)),
                min_size=1,
                max_size=3,
                unique=True,
            )
        )
        row_duties = []
        for shape in shapes:
            duty = draw(duties(used))
            duty["shape"] = shape
            if shape == "alert":
                duty.pop("limit", None)
                duty.setdefault("state", "on")
            else:
                duty.pop("state", None)
                duty.setdefault("limit", 10)
            row_duties.append(duty)
        out.append(
            {
                "domain": domain,
                "brand": draw(
                    st.text(
                        st.characters(categories=("L", "N", "Zs")),
                        min_size=1,
                        max_size=20,
                    ).filter(str.strip)
                ),
                "icon": "mdi:"
                + draw(st.from_regex(r"[a-z0-9-]{1,10}", fullmatch=True)),
                "duties": row_duties,
            }
        )
    return out


@pytest.mark.property
@settings(max_examples=150, deadline=None)
@given(rows())
def test_property_every_valid_registration_is_accepted(raw):
    reg = pr.build_registration("car_keeper", raw, _NAMES)
    assert len(reg.preset_ids) == len(set(reg.preset_ids))
    for preset in reg.presets:
        assert preset["id"].startswith("car_keeper/")
        assert preset["id"].count(pr.ID_SEPARATOR) == 1
        assert preset["source"] == "companion"
        dc.normalize_declarative_companion(preset["default_spec"])
    built = {p["default_spec"]["selection"]["target_integration"] for p in reg.presets}
    assert built == {row["domain"] for row in raw}


_JUNK = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=5),
    lambda inner: (
        st.lists(inner, max_size=3)
        | st.dictionaries(st.text(max_size=5), inner, max_size=3)
    ),
    max_leaves=10,
)


@pytest.mark.property
@settings(max_examples=300, deadline=None)
@given(_JUNK, _JUNK, _JUNK)
@example("car", [{"domain": "x"}], None)
@example("car", [_row()], {"change_engine_oil": {"en": 1}})
def test_property_junk_raises_only_the_row_error(domain, raw, names):
    try:
        pr.build_registration(domain, raw, names)
    except pr.PresetRowError:
        pass


@pytest.mark.property
@settings(max_examples=150, deadline=None)
@given(rows(), st.text(min_size=1, max_size=8).filter(lambda k: k not in pr._ROW_KEYS))
def test_property_an_unknown_row_key_is_refused(raw, key):
    raw[0][key] = 1
    with pytest.raises(pr.PresetRowError) as info:
        pr.build_registration("car_keeper", raw, _NAMES)
    assert info.value.path == f"rows[0].{key}"


@pytest.mark.property
@settings(max_examples=150, deadline=None)
@given(rows(), st.text(min_size=1, max_size=8).filter(lambda k: k not in pr._DUTY_KEYS))
def test_property_an_unknown_duty_key_is_refused(raw, key):
    raw[0]["duties"][0][key] = 1
    with pytest.raises(pr.PresetRowError) as info:
        pr.build_registration("car_keeper", raw, _NAMES)
    assert info.value.path == f"rows[0].duties[0].{key}"


@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(rows(), st.sampled_from(["brand", "icon", "domain"]), st.integers(1, 40))
def test_property_a_field_over_its_cap_is_refused(raw, field, extra):
    # The icon cap is on the part after "mdi:".
    caps = {"brand": pr.MAX_BRAND_LEN, "icon": 60, "domain": 50}
    raw[0][field] = ("mdi:" if field == "icon" else "") + "a" * (caps[field] + extra)
    with pytest.raises(pr.PresetRowError) as info:
        pr.build_registration("car_keeper", raw, _NAMES)
    assert info.value.path == f"rows[0].{field}"
