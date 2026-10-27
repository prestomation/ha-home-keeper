"""The caller's context on the events that the store fires (#467).

``caller.py`` keeps the ``Context`` of the service call, websocket command or entity
action that changes Home Keeper data. ``store._fire`` reads it, so the event carries
the user and the service call, and the logbook shows who made the change. A change
that Home Keeper makes on its own has no caller, and its event gets a new context.

The source checks make sure that each path into the store sets the caller, and that
each store event goes through ``_fire``.
"""

from __future__ import annotations

import ast
import asyncio
import types
from pathlib import Path

import hk_caller as caller
import pytest
from test_store_consumable import _FakeHass, _FakeStore, _run, _task, store_mod

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"


def _tree(name: str) -> ast.Module:
    return ast.parse((_COMPONENT / name).read_text(encoding="utf-8"))


class _Ctx:
    def __init__(self, user_id: str | None = None) -> None:
        self.user_id = user_id


# ── the context variable ─────────────────────────────────────────────────────


def test_there_is_no_caller_outside_a_call():
    assert caller.current() is None


def test_the_caller_is_set_in_the_block_and_reset_after_it():
    ctx = _Ctx("ann")
    with caller.caller(ctx):
        assert caller.current() is ctx
        inner = _Ctx("bob")
        with caller.caller(inner):
            assert caller.current() is inner
        assert caller.current() is ctx
    assert caller.current() is None


def test_the_caller_is_reset_when_the_block_raises():
    with pytest.raises(RuntimeError), caller.caller(_Ctx("ann")):
        raise RuntimeError
    assert caller.current() is None


# ── services ─────────────────────────────────────────────────────────────────


def test_a_service_handler_runs_with_the_context_of_its_call():
    seen = []

    async def handle(call):
        seen.append(caller.current())
        return {"ok": call.data}

    wrapped = caller.service(handle)
    ctx = _Ctx("ann")
    call = types.SimpleNamespace(context=ctx, data=1)

    assert asyncio.run(wrapped(call)) == {"ok": 1}
    assert seen == [ctx]
    assert caller.current() is None
    assert wrapped.__name__ == "handle"


class _Services:
    def __init__(self) -> None:
        self.registered: list[tuple] = []

    def async_register(self, domain, name, handler, schema=None, **kwargs):
        self.registered.append((domain, name, handler, schema, kwargs))


def test_the_registrar_wraps_each_handler_and_keeps_the_arguments():
    seen = []

    async def handle(call):
        seen.append(caller.current())

    services = _Services()
    caller.ContextServices(services).async_register(
        "home_keeper", "add_task", handle, "SCHEMA", supports_response="optional"
    )

    [(domain, name, wrapped, schema, kwargs)] = services.registered
    assert (domain, name, schema, kwargs) == (
        "home_keeper",
        "add_task",
        "SCHEMA",
        {"supports_response": "optional"},
    )
    ctx = _Ctx("ann")
    asyncio.run(wrapped(types.SimpleNamespace(context=ctx)))
    assert seen == [ctx]


def test_the_registrar_passes_no_schema_when_none_is_given():
    async def handle(call):
        return None

    services = _Services()
    caller.ContextServices(services).async_register("home_keeper", "x", handle)
    assert services.registered[0][3] is None


def test_every_service_registers_through_the_context_registrar():
    """A handler registered on ``hass.services`` would fire events with no user."""
    direct = [
        ast.unparse(node)
        for node in ast.walk(_tree("__init__.py"))
        if isinstance(node, ast.Attribute)
        and node.attr == "async_register"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "services"
        and ast.unparse(node.value) == "hass.services"
    ]
    assert direct == []


# ── websocket commands ───────────────────────────────────────────────────────


def test_a_websocket_handler_runs_with_the_context_of_its_message():
    seen = []
    ctx = _Ctx("ann")

    def handler(hass, connection, msg):
        seen.append((caller.current(), msg))
        return "scheduled"

    handler._ws_command = "home_keeper/get_tasks"
    handler._ws_schema = "SCHEMA"
    connection = types.SimpleNamespace(
        context=lambda msg: ctx if msg == {"id": 1} else None
    )

    wrapped = caller.websocket(handler)

    assert wrapped("hass", connection, {"id": 1}) == "scheduled"
    assert seen == [(ctx, {"id": 1})]
    assert caller.current() is None
    # Home Assistant reads the command and the schema off the registered handler.
    assert wrapped._ws_command == "home_keeper/get_tasks"
    assert wrapped._ws_schema == "SCHEMA"


def test_every_websocket_command_registers_with_the_caller():
    register = next(
        node
        for node in ast.walk(_tree("websocket_api.py"))
        if isinstance(node, ast.FunctionDef) and node.name == "async_register"
    )
    calls = [
        node
        for node in ast.walk(register)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func) == "websocket_api.async_register_command"
    ]
    assert calls
    bare = [
        ast.unparse(call)
        for call in calls
        if not (
            isinstance(call.args[1], ast.Call)
            and ast.unparse(call.args[1].func) == "caller.websocket"
        )
    ]
    assert bare == []


# ── the store ────────────────────────────────────────────────────────────────


class _ContextBus:
    def __init__(self) -> None:
        self.fired: list[tuple[str, dict, object]] = []

    def async_fire(self, event, data, context=None):
        self.fired.append((event, data, context))


@pytest.fixture
def store():
    prior = store_mod.Store
    store_mod.Store = _FakeStore
    try:
        hass = _FakeHass()
        hass.bus = _ContextBus()
        yield store_mod.HomeKeeperStore(hass)
    finally:
        store_mod.Store = prior


def test_a_store_event_carries_the_context_of_the_caller(store):
    task = _task(store)
    ctx = _Ctx("ann")

    async def _complete():
        with caller.caller(ctx):
            await store.complete_task(task["id"])

    _run(_complete())

    completed = [f for f in store._hass.bus.fired if f[0].endswith("task_completed")]
    assert len(completed) == 1
    assert completed[0][2] is ctx


def test_a_store_event_with_no_caller_gets_no_context(store):
    task = _task(store)
    _run(store.complete_task(task["id"]))
    assert store._hass.bus.fired
    assert {context for _, _, context in store._hass.bus.fired} == {None}


def test_every_store_event_fires_through_fire():
    """A direct ``bus.async_fire`` in the store would drop the caller."""
    tree = _tree("store.py")
    fire = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_fire"
    )
    inside = {id(node) for node in ast.walk(fire)}
    direct = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "async_fire"
        and id(node) not in inside
    ]
    assert direct == []


# ── entity actions ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("module", "function"),
    [
        ("todo.py", "async_update_todo_item"),
        ("button.py", "async_press"),
    ],
)
def test_an_entity_action_changes_the_store_with_the_entity_context(module, function):
    """Home Assistant sets the context of the service call on the entity first."""
    node = next(
        n
        for n in ast.walk(_tree(module))
        if isinstance(n, ast.AsyncFunctionDef) and n.name == function
    )
    withs = [
        ast.unparse(item.context_expr)
        for n in ast.walk(node)
        if isinstance(n, ast.With)
        for item in n.items
    ]
    assert "caller.caller(self._context)" in withs


def test_every_upload_view_posts_with_the_user_as_the_caller():
    """An upload changes the store, so its event names the user who sent it."""
    posts = {
        cls.name: [ast.unparse(d) for d in node.decorator_list]
        for cls in ast.walk(_tree("manuals.py"))
        if isinstance(cls, ast.ClassDef)
        for node in cls.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "post"
    }
    assert len(posts) == 3
    assert {
        name for name, decorators in posts.items() if "_as_caller" not in decorators
    } == set()


def test_an_import_upload_runs_with_the_user_as_the_caller():
    body = ast.unparse(_tree("transfer_http.py"))
    assert body.count("with caller.caller(context):") == 2


def test_entry_setup_runs_with_no_caller():
    """The timers that a reload starts must not keep the user of the reload."""
    setup = next(
        node
        for node in ast.walk(_tree("__init__.py"))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry"
    )
    [statement] = [s for s in setup.body if not isinstance(s, ast.Expr)]
    assert isinstance(statement, ast.With)
    assert ast.unparse(statement.items[0].context_expr) == "caller.caller(None)"
    assert ast.unparse(statement.body[0]) == (
        "return await _async_setup_entry(hass, entry)"
    )


def test_the_store_keeps_the_caller_of_the_last_change_to_each_task(store):
    task = _task(store)
    ctx = _Ctx("ann")

    async def _complete():
        with caller.caller(ctx):
            await store.complete_task(task["id"])

    _run(_complete())
    assert store.caller_of(task["id"]) is ctx

    _run(store.skip_task(task["id"]))
    assert store.caller_of(task["id"]) is None

    async def _delete():
        with caller.caller(ctx):
            await store.delete_task(task["id"])

    _run(_delete())
    assert task["id"] not in store._task_callers
    assert store.caller_of("unknown") is None
