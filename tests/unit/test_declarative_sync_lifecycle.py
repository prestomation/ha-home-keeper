"""The HA-bound half of the declarative-companion reconcile pass (B12-1/2/3).

The diff itself is pure and tested in ``test_declarative_companions.py``. What is
under test here is what ``DeclarativeCompanionSync`` hands the store: the keys of
disabled entities (B12-1), a failure in one spec that must not stop the other specs
or the setup (B12-2), and the keys whose entity had no live state when the templates
rendered (B12-3). The registry and the renderer are fakes. The import guard is the
one ``test_template_error_log.py`` explains.
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest

try:
    from custom_components.home_keeper import declarative_companion_sync as sync_mod
except ImportError as err:  # pragma: no cover - the lane without a real HA
    pytest.skip(
        f"declarative_companion_sync needs a real Home Assistant: {err}",
        allow_module_level=True,
    )


def _entity(entity_id, *, disabled=False):
    return {
        "entity_registry_id": f"reg_{entity_id}",
        "entity_id": entity_id,
        "platform": "device_pulse",
        "domain": "sensor",
        "disabled": disabled,
        "labels": set(),
    }


def _spec(spec_id, *, enabled=True):
    return {
        "id": spec_id,
        "name": f"Spec {spec_id}",
        "enabled": enabled,
        "selection": {"target_integration": "device_pulse"},
        "trigger": {"mode": "state", "state": "on"},
        "task_template": {"name_template": "{{ friendly_name }}"},
    }


class _States:
    def __init__(self, states):
        self._states = states

    def get(self, entity_id):
        return self._states.get(entity_id)


class _Store:
    def __init__(self, specs, *, fail_on=()):
        self._specs = specs
        self._fail_on = set(fail_on)
        self.calls = []
        self.paused = []

    def get_declarative_companions(self):
        return self._specs

    async def pause_declarative_companion_tasks(self, spec_id):
        self.paused.append(spec_id)

    async def reconcile_declarative_companion_tasks(
        self, spec, matches, rendered, *, config_entry_id, dormant, stale
    ):
        if spec["id"] in self._fail_on:
            raise ValueError("missing required field: 'name'")
        self.calls.append(
            {
                "spec": spec["id"],
                "rendered": rendered,
                "dormant": set(dormant),
                "stale": set(stale),
            }
        )
        return True, [f"task_{spec['id']}"]


def _sync(store, entities, states, names=None):
    obj = sync_mod.DeclarativeCompanionSync.__new__(sync_mod.DeclarativeCompanionSync)
    obj._hass = SimpleNamespace(states=_States(states))
    obj._entry = SimpleNamespace(entry_id="entry1")
    obj._coordinator = SimpleNamespace(store=store)
    obj._render_errors = {}
    obj._blank_names = set()
    obj._registry_snapshot = lambda: {"entities": entities}
    names = names or {}
    obj._render_match = lambda spec, match: (
        names.get(match["entity"]["entity_id"], "Name"),
        "",
    )
    return obj


def _live(**attributes):
    return SimpleNamespace(state="on", attributes=attributes)


def test_b12_2_one_failing_spec_does_not_stop_the_others(caplog):
    # The failure used to leave the pass, so every spec after it was never
    # reconciled, and at setup the raise failed Home Keeper's setup.
    store = _Store({"a": _spec("a"), "b": _spec("b")}, fail_on={"a"})
    sync = _sync(store, [_entity("sensor.x")], {"sensor.x": _live()})
    with caplog.at_level(logging.ERROR, logger=sync_mod.__name__):
        changed, created = asyncio.run(sync._reconcile_all())
    assert (changed, created) == (True, ["task_b"])
    assert [call["spec"] for call in store.calls] == ["b"]
    assert "Spec a" in caplog.text


def test_b12_2_a_disabled_spec_pauses_and_the_pass_goes_on():
    store = _Store({"a": _spec("a", enabled=False), "b": _spec("b")})
    sync = _sync(store, [_entity("sensor.x")], {"sensor.x": _live()})
    changed, created = asyncio.run(sync._reconcile_all())
    assert store.paused == ["a"]
    assert [call["spec"] for call in store.calls] == ["b"]
    assert (changed, created) == (True, ["task_b"])


def test_b12_2_a_blank_name_is_logged_once(caplog):
    store = _Store({"a": _spec("a")})
    sync = _sync(
        store,
        [_entity("sensor.x"), _entity("sensor.y")],
        {"sensor.x": _live(), "sensor.y": _live()},
        names={"sensor.x": " "},
    )
    with caplog.at_level(logging.WARNING, logger=sync_mod.__name__):
        asyncio.run(sync._reconcile_all())
        asyncio.run(sync._reconcile_all())
    warnings = [r.getMessage() for r in caplog.records if "blank" in r.getMessage()]
    assert len(warnings) == 1
    assert "sensor.x" in warnings[0]
    assert "Spec a" in warnings[0]


def test_b12_1_disabled_entities_go_to_the_store_as_dormant():
    store = _Store({"a": _spec("a")})
    sync = _sync(
        store,
        [_entity("sensor.x"), _entity("sensor.off", disabled=True)],
        {"sensor.x": _live()},
    )
    asyncio.run(sync._reconcile_all())
    assert store.calls[0]["dormant"] == {("a", "reg_sensor.off")}
    assert list(store.calls[0]["rendered"]) == [("a", "reg_sensor.x")]


def test_b12_3_a_match_without_live_state_goes_to_the_store_as_stale():
    store = _Store({"a": _spec("a")})
    sync = _sync(
        store,
        [_entity("sensor.live"), _entity("sensor.none"), _entity("sensor.restored")],
        {
            "sensor.live": _live(friendly_name="Live"),
            "sensor.restored": _live(restored=True),
        },
    )
    asyncio.run(sync._reconcile_all())
    assert store.calls[0]["stale"] == {
        ("a", "reg_sensor.none"),
        ("a", "reg_sensor.restored"),
    }


def test_the_blank_name_record_stays_bounded(monkeypatch):
    monkeypatch.setattr(sync_mod, "_RENDER_ERRORS_MAX", 2)
    sync = _sync(_Store({}), [], {})
    for n in range(5):
        sync._warn_blank_name({"id": "a", "name": "A"}, f"sensor.e{n}")
    assert len(sync._blank_names) <= 2
