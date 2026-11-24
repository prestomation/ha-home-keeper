"""The life of the companion presets as a state machine.

The machine does what companions and a user do: a companion registers, registers
again with a new set or the same set, unregisters, or unloads. Home Keeper's entry
reloads, and each companion registers again. A companion tries to use the id of a
shipped preset, or sends too many rows. A user accepts a companion preset, which copies
its spec into a declarative companion, and later deletes that declarative companion.

The real code is ``preset_registry.transition`` and ``preset_registry.merged_presets``.
The model is a plain dict of companion domain to its preset ids, and a dict of the
specs that the user accepted. It does not read the code under test. After each step:

1. The shipped presets come first, the same and in the same order.
2. Each id is unique. A companion id is ``<domain>/<id>`` with 1 separator.
3. The merged ids are the shipped ids, then the model's ids in order of registration.
4. A spec that a user accepted stays until the user deletes it.
5. A companion that unloaded has no presets.
6. Each step fires exactly the events that the model expects.

Run just these: `pytest tests/unit -m property`.
"""

from __future__ import annotations

import copy
import os
from typing import Any

import hk_declarative_companions as dc
import hk_declarative_presets as presets
import hk_preset_registry as pr
import pytest
from hk_const import EVENT_PRESETS_REGISTERED, EVENT_PRESETS_REMOVED
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    consumes,
    invariant,
    rule,
)

pytestmark = pytest.mark.property

_SHIPPED_IDS = [p["id"] for p in presets.CATALOG_PRESETS]
_SHIPPED_SPECS = copy.deepcopy([p["default_spec"] for p in presets.CATALOG_PRESETS])
_DOMAINS = ("car_keeper", "boat_keeper", "bike_keeper")
_TARGETS = ("tesla_fleet", "roborock", "device_pulse", "kia_uvo")
_NAMES = {"change_engine_oil": {"en": "Change the engine oil"}}


def _rows(targets: list[str], shapes: list[str]) -> list[dict[str, Any]]:
    """1 row per target, with 1 duty for each of *shapes*."""
    rows = []
    for target in targets:
        duties = []
        for index, shape in enumerate(shapes):
            duty: dict[str, Any] = {
                "duty": "change_engine_oil",
                "shape": shape,
                "keys": [f"key_{index}"],
            }
            if shape == "alert":
                duty["state"] = "on"
            else:
                duty["limit"] = 10
            duties.append(duty)
        rows.append(
            {"domain": target, "brand": "Brand", "icon": "mdi:car", "duties": duties}
        )
    return rows


def _expected_ids(domain: str, rows: list[dict[str, Any]]) -> list[str]:
    """The ids the model expects: the rule of the id format, written out here."""
    ids = []
    for row in rows:
        for duty in row["duties"]:
            parts = [row["domain"], duty["shape"], duty.get("state", "")]
            ids.append(domain + "/" + "_".join(p for p in parts if p))
    return ids


class PresetLife(RuleBasedStateMachine):
    accepted_specs = Bundle("accepted_specs")

    def __init__(self) -> None:
        super().__init__()
        self.registry = pr.PresetRegistry()
        # The model.
        self.model: dict[str, list[str]] = {}
        self.model_rows: dict[str, list[dict[str, Any]]] = {}
        self.store: dict[int, dict[str, Any]] = {}
        self.next_spec = 0
        self.unloaded: set[str] = set()

    def _step(self, action: Any) -> tuple[tuple[str, dict[str, Any]], ...]:
        result = pr.transition(self.registry, action)
        self.registry = result.registry
        return result.events

    # ── Companions ───────────────────────────────────────────────────────────

    @rule(
        domain=st.sampled_from(_DOMAINS),
        integrations=st.lists(
            st.sampled_from(_TARGETS), min_size=1, max_size=3, unique=True
        ),
        shapes=st.lists(
            st.sampled_from(sorted(presets.SHAPES)), min_size=1, max_size=3, unique=True
        ),
    )
    def register(self, domain: str, integrations: list[str], shapes: list[str]) -> None:
        rows = _rows(integrations, shapes)
        events = self._step(pr.Register(pr.build_registration(domain, rows, _NAMES)))
        ids = _expected_ids(domain, rows)
        changed = self.model.get(domain) != ids or self.model_rows.get(domain) != rows
        if changed:
            assert events == (
                (EVENT_PRESETS_REGISTERED, {"domain": domain, "preset_ids": ids}),
            )
        else:
            assert events == ()
        self.model[domain] = ids
        self.model_rows[domain] = rows
        self.unloaded.discard(domain)

    @rule(domain=st.sampled_from(_DOMAINS))
    def register_the_same_again(self, domain: str) -> None:
        if domain not in self.model:
            return
        rows = self.model_rows[domain]
        events = self._step(pr.Register(pr.build_registration(domain, rows, _NAMES)))
        assert events == ()

    @rule(domain=st.sampled_from(_DOMAINS))
    def unregister(self, domain: str) -> None:
        events = self._step(pr.Unregister(domain))
        if domain in self.model:
            ids = self.model.pop(domain)
            self.model_rows.pop(domain)
            assert events == (
                (EVENT_PRESETS_REMOVED, {"domain": domain, "preset_ids": ids}),
            )
        else:
            assert events == ()

    @rule(domain=st.sampled_from(_DOMAINS))
    def companion_unloads(self, domain: str) -> None:
        # The companion calls unregister_presets from its unload, or Home Keeper's
        # config entry listener does it for the companion.
        self.unregister(domain)
        self.unloaded.add(domain)

    @rule()
    def home_keeper_reloads(self) -> None:
        # The registry is memory for the run and survives the reload. Each companion
        # answers home_keeper_register_companions with the same set: no event.
        for domain, rows in list(self.model_rows.items()):
            reg = pr.build_registration(domain, rows, _NAMES)
            assert self._step(pr.Register(reg)) == ()

    @rule(domain=st.sampled_from(_DOMAINS), shipped=st.sampled_from(_SHIPPED_IDS))
    def try_a_shipped_id(self, domain: str, shipped: str) -> None:
        # A row whose target and shape spell a shipped id gets the companion prefix.
        before = self.registry
        target, _, rest = shipped.partition("_")
        shape = next((s for s in presets.SHAPES if rest.startswith(s)), "percent_low")
        rows = _rows([target], [shape])
        try:
            reg = pr.build_registration(domain, rows, _NAMES)
        except pr.PresetRowError:
            assert self.registry is before
            return
        assert all(i.startswith(domain + "/") for i in reg.preset_ids)
        self.register(domain, [target], [shape])

    @rule(domain=st.sampled_from(_DOMAINS), extra=st.integers(1, 5))
    def too_many_rows(self, domain: str, extra: int) -> None:
        before = self.registry
        targets = [f"t{i}" for i in range(pr.MAX_ROWS + extra)]
        with pytest.raises(pr.PresetRowError):
            pr.build_registration(domain, _rows(targets, ["alert"]), _NAMES)
        assert self.registry is before

    # ── A user ───────────────────────────────────────────────────────────────

    @rule(target=accepted_specs, pick=st.integers(0, 50))
    def accept_a_companion_preset(self, pick: int) -> int:
        companion = [
            p
            for p in pr.merged_presets(self.registry)
            if p.get("source") == "companion"
        ]
        spec_id = self.next_spec
        self.next_spec += 1
        if not companion:
            return spec_id
        preset = companion[pick % len(companion)]
        # The add path copies the spec. The registry keeps no link to it.
        spec = dc.normalize_declarative_companion(copy.deepcopy(preset["default_spec"]))
        self.store[spec_id] = spec
        return spec_id

    @rule(spec_id=consumes(accepted_specs))
    def delete_the_declarative_companion(self, spec_id: int) -> None:
        self.store.pop(spec_id, None)

    # ── Invariants ───────────────────────────────────────────────────────────

    @invariant()
    def shipped_presets_never_change(self) -> None:
        merged = pr.merged_presets(self.registry)
        head = merged[: len(_SHIPPED_IDS)]
        assert [p["id"] for p in head] == _SHIPPED_IDS
        assert [p["default_spec"] for p in head] == _SHIPPED_SPECS
        assert all(p["source"] == "builtin" for p in head)

    @invariant()
    def ids_are_unique_and_namespaced(self) -> None:
        merged = pr.merged_presets(self.registry)
        ids = [p["id"] for p in merged]
        assert len(ids) == len(set(ids))
        for preset in merged[len(_SHIPPED_IDS) :]:
            domain, sep, rest = preset["id"].partition(pr.ID_SEPARATOR)
            assert sep and rest and pr.ID_SEPARATOR not in rest
            assert domain == preset["provided_by"]
            assert preset["default_spec"]["preset_id"] == preset["id"]

    @invariant()
    def merged_is_shipped_plus_the_model(self) -> None:
        ids = [p["id"] for p in pr.merged_presets(self.registry)]
        assert ids == _SHIPPED_IDS + [i for d in self.model for i in self.model[d]]
        assert list(self.registry.registrations) == list(self.model)

    @invariant()
    def accepted_specs_survive_the_companion(self) -> None:
        for spec in self.store.values():
            assert spec["preset_id"].count(pr.ID_SEPARATOR) == 1
            assert spec["selection"]["translation_keys"]

    @invariant()
    def an_unloaded_companion_has_no_presets(self) -> None:
        for domain in self.unloaded:
            assert domain not in self.registry.registrations
            assert not any(
                p.get("provided_by") == domain for p in pr.merged_presets(self.registry)
            )


PresetLife.TestCase.settings = settings(
    # Fixed in CI. `HK_STATEFUL_EXAMPLES` lets a developer search longer by hand.
    max_examples=int(os.environ.get("HK_STATEFUL_EXAMPLES", "600")),
    stateful_step_count=15,
    deadline=None,
    # `HK_STATEFUL_SEARCH=1` draws new sequences on each run for a long search.
    derandomize=not os.environ.get("HK_STATEFUL_SEARCH"),
    database=None,
)
TestPresetLife = PresetLife.TestCase


# ── Sequences as plain tests ─────────────────────────────────────────────────


def test_an_accepted_spec_survives_unregister_and_unload():
    machine = PresetLife()
    machine.register("car_keeper", ["tesla_fleet"], ["percent_low"])
    spec_id = machine.accept_a_companion_preset(0)
    machine.companion_unloads("car_keeper")
    assert machine.store[spec_id]["preset_id"] == "car_keeper/tesla_fleet_percent_low"
    machine.an_unloaded_companion_has_no_presets()
    machine.merged_is_shipped_plus_the_model()


def test_a_reload_fires_nothing_and_keeps_every_set():
    machine = PresetLife()
    machine.register("car_keeper", ["tesla_fleet"], ["alert"])
    machine.register("bike_keeper", ["kia_uvo"], ["wear_high"])
    machine.home_keeper_reloads()
    machine.merged_is_shipped_plus_the_model()
    assert list(machine.registry.registrations) == ["car_keeper", "bike_keeper"]


def test_a_companion_that_unloads_and_registers_again_fires_both_events():
    machine = PresetLife()
    machine.register("car_keeper", ["tesla_fleet"], ["percent_low"])
    machine.companion_unloads("car_keeper")
    machine.an_unloaded_companion_has_no_presets()
    # register() checks that this registration fires 1 registered event again.
    machine.register("car_keeper", ["tesla_fleet"], ["percent_low"])
    assert "car_keeper" not in machine.unloaded
    machine.merged_is_shipped_plus_the_model()
    machine.ids_are_unique_and_namespaced()
