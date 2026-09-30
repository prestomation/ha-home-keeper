"""Lifecycle handlers that sit on Home Assistant events and reloads.

* B18-2: an entity-registry rename of a problem sensor moves its mirror before the
  reconcile runs, so the reconcile keeps the task.
* B03-2: deleting a declarative companion reloads the entry when a removed task had
  device-page entities, in the websocket command and in the service.

The rename handler runs against fakes. The import guard is the one
``test_template_error_log.py`` explains. The delete handlers are checked on the
source, as ``test_api_surface.py`` checks the service registrations: they are
closures and decorated websocket commands with no unit entry point, and
``tests/integration/test_declarative_companion_sync.py`` drives them for real.
"""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"


# ── B18-2 ────────────────────────────────────────────────────────────────────
class _Store:
    def __init__(self):
        self.log = []

    async def async_rename_problem_sensor(self, old, new):
        self.log.append(("rename", old, new))
        return True

    async def reconcile_problem_sensor_tasks(self, eligible, *, config_entry_id):
        self.log.append(("reconcile",))
        return False


class _Hass:
    def __init__(self):
        self.tasks = []

    def async_create_task(self, coro):
        self.tasks.append(coro)


def _problem_sync():
    problem_sync = pytest.importorskip(
        "custom_components.home_keeper.problem_sync",
        reason="problem_sync needs a real Home Assistant",
    )
    store = _Store()
    refreshes = []

    async def _refresh():
        refreshes.append(True)

    sync = problem_sync.ProblemSensorSync.__new__(problem_sync.ProblemSensorSync)
    sync._hass = _Hass()
    sync._entry = SimpleNamespace(entry_id="entry1", options={})
    sync._coordinator = SimpleNamespace(store=store, async_request_refresh=_refresh)
    sync._reload_scheduled = False
    sync._resubscribe_state = lambda: None
    return sync, store


def _run(sync):
    for coro in sync._hass.tasks:
        asyncio.run(coro)


def test_b18_2_a_rename_moves_the_mirror_before_the_reconcile():
    sync, store = _problem_sync()
    sync._handle_registry_update(
        SimpleNamespace(
            data={
                "action": "update",
                "entity_id": "binary_sensor.sump_pump_problem",
                "old_entity_id": "binary_sensor.node_5_problem",
                "changes": {"entity_id": "binary_sensor.node_5_problem"},
            }
        )
    )
    _run(sync)
    assert store.log == [
        (
            "rename",
            "binary_sensor.node_5_problem",
            "binary_sensor.sump_pump_problem",
        ),
        ("reconcile",),
    ]


def test_b18_2_an_update_without_a_rename_only_reconciles():
    sync, store = _problem_sync()
    sync._handle_registry_update(
        SimpleNamespace(
            data={
                "action": "update",
                "entity_id": "binary_sensor.sump_pump_problem",
                "changes": {"labels": set()},
            }
        )
    )
    sync._handle_registry_update(
        SimpleNamespace(
            data={"action": "create", "entity_id": "binary_sensor.new_problem"}
        )
    )
    _run(sync)
    assert store.log == [("reconcile",), ("reconcile",)]


# ── B03-2 ────────────────────────────────────────────────────────────────────
def _function(tree: ast.AST, name: str) -> ast.AsyncFunctionDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


def _reloads_when_delete_says_so(func: ast.AsyncFunctionDef) -> bool:
    """Whether *func* reloads the entry under a test of the delete's result."""
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        test = ast.unparse(node.test)
        body = ast.unparse(ast.Module(body=node.body, type_ignores=[]))
        if ("async_delete_declarative_companion" in test or test == "removed") and (
            "config_entries.async_reload" in body
        ):
            return True
    return False


@pytest.mark.parametrize(
    ("module", "handler"),
    [
        ("websocket_api.py", "ws_delete_declarative_companion"),
        ("__init__.py", "handle_delete_declarative_companion"),
    ],
)
def test_b03_2_deleting_a_companion_reloads_when_the_entity_set_changed(
    module: str, handler: str
) -> None:
    # The store returns whether a removed task had device-page entities. The
    # handlers ignored it, so those entities stayed until an unrelated reload.
    tree = ast.parse((_COMPONENT / module).read_text(encoding="utf-8"))
    assert _reloads_when_delete_says_so(_function(tree, handler))
