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


# ── a spec change waits for its reload ───────────────────────────────────────
class _ReloadHass:
    """The part of Home Assistant a pass and its reload touch."""

    def __init__(self, log):
        self.log = log
        self.states = _States({})
        self.config_entries = SimpleNamespace(async_reload=self._reload)

    def async_create_task(self, coro):
        return asyncio.get_running_loop().create_task(coro)

    async def _reload(self, entry_id):
        self.log.append(("reload start", entry_id))
        await asyncio.sleep(0.01)
        self.log.append(("reload end", entry_id))


def _spec_sync(log, *, changed=True):
    sync = sync_mod.DeclarativeCompanionSync.__new__(sync_mod.DeclarativeCompanionSync)
    sync._hass = _ReloadHass(log)
    sync._entry = SimpleNamespace(entry_id="entry1")
    sync._pass_lock = asyncio.Lock()
    sync._spec_pass = None
    sync._reload_task = None
    sync._stopped = False

    async def _refresh():
        log.append(("refresh",))

    sync._coordinator = SimpleNamespace(async_request_refresh=_refresh)

    async def _reconcile_all():
        log.append(("pass start",))
        await asyncio.sleep(0)
        log.append(("pass end",))
        return changed, []

    sync._reconcile_all = _reconcile_all
    return sync


def test_a_spec_change_waits_for_its_pass_and_the_reload_it_asks_for(monkeypatch):
    # The service answered before the reload its pass asked for, so the next call of
    # the same script came during the reload and failed as "not loaded".
    monkeypatch.setattr(sync_mod.sensor_watcher, "async_mark_tasks_new", lambda *a: 0)
    log = []

    async def _scenario():
        sync = _spec_sync(log)
        sync._handle_specs_changed()
        await sync.async_wait_for_spec_change()
        log.append(("answered",))

    asyncio.run(_scenario())
    assert log == [
        ("pass start",),
        ("pass end",),
        ("reload start", "entry1"),
        ("reload end", "entry1"),
        ("answered",),
    ]


def test_a_spec_change_without_a_reload_answers_after_its_pass():
    log = []

    async def _scenario():
        sync = _spec_sync(log, changed=False)
        sync._handle_specs_changed()
        await sync.async_wait_for_spec_change()
        log.append(("answered",))

    asyncio.run(_scenario())
    assert log == [("pass start",), ("pass end",), ("refresh",), ("answered",)]


def test_a_spec_change_does_not_go_through_the_debouncer():
    # The debouncer drops a call while a pass runs and holds one for its cooldown,
    # so a spec saved then had no pass, or a late one.
    log = []

    async def _scenario():
        sync = _spec_sync(log, changed=False)
        sync._reconcile_debouncer = SimpleNamespace(
            async_call=lambda: pytest.fail("a spec change went to the debouncer")
        )
        sync._handle_specs_changed()
        await sync.async_wait_for_spec_change()

    asyncio.run(_scenario())
    assert ("pass start",) in log


def test_passes_run_one_at_a_time():
    log = []

    async def _scenario():
        sync = _spec_sync(log, changed=False)
        await asyncio.gather(
            sync._async_reconcile_and_maybe_reload(),
            sync._async_reconcile_and_maybe_reload(),
        )

    asyncio.run(_scenario())
    assert log == [
        ("pass start",),
        ("pass end",),
        ("refresh",),
        ("pass start",),
        ("pass end",),
        ("refresh",),
    ]


def test_a_pass_after_the_unload_does_nothing():
    log = []

    async def _scenario():
        sync = _spec_sync(log)
        sync._stop()
        sync._handle_specs_changed()
        await sync.async_wait_for_spec_change()

    asyncio.run(_scenario())
    assert log == []


def test_one_reload_for_passes_that_overlap_it(monkeypatch):
    monkeypatch.setattr(sync_mod.sensor_watcher, "async_mark_tasks_new", lambda *a: 0)
    log = []

    async def _scenario():
        sync = _spec_sync(log)
        await sync._async_reconcile_and_maybe_reload()
        await sync._async_reconcile_and_maybe_reload()
        await sync.async_wait_for_spec_change()

    asyncio.run(_scenario())
    assert log.count(("reload start", "entry1")) == 1


def test_a_failed_reload_is_logged_and_the_wait_ends(caplog):
    log = []

    async def _fail(entry_id):
        raise RuntimeError("entry is in the wrong state")

    async def _scenario():
        sync = _spec_sync(log)
        sync._hass.config_entries.async_reload = _fail
        sync._reload_task = asyncio.get_running_loop().create_task(sync._async_reload())
        await sync.async_wait_for_spec_change()

    with caplog.at_level(logging.ERROR, logger=sync_mod.__name__):
        asyncio.run(_scenario())
    assert "after a companion change" in caplog.text


def test_settle_waits_on_the_sync_of_the_coordinator():
    calls = []

    class _Sync:
        async def async_wait_for_spec_change(self):
            calls.append("waited")

    asyncio.run(sync_mod.async_settle(SimpleNamespace(declarative_sync=_Sync())))
    asyncio.run(sync_mod.async_settle(SimpleNamespace(declarative_sync=None)))
    assert calls == ["waited"]
