"""Doubles shared by the unit suites that drive HA-coupled modules.

Only what genuinely coincides between suites lives here. A fake with one caller
stays in the file that uses it, and a suite that needs an extra attribute or an
extra method subclasses the shared shape rather than widening it — a double
carrying warts for a suite that never touches them is harder to read than two
honest ones.

What that leaves shared, and who shares it:

* :class:`FakeTaskSnapshotStore` — ``get_tasks()`` handing back a *copy*
  (``test_coordinator_purge``, ``test_notifier_blocking``).
* :class:`FakeSyncStore`, :class:`FakeSyncCoordinator`,
  :class:`FakeTodoServices`, :class:`FakeTodoHass` — the harness both to-do
  sync drivers run against (``test_shopping_sync``, ``test_todo_list_sync``).

Deliberately *not* here: ``test_device_heal``'s registry/store doubles (a
device-registry vocabulary nothing else speaks), ``test_todo``'s store (the
entity reads one task at a time and completes without an origin, so it shares no
method with the drivers' store), and the per-suite hass/entry/bus doubles that
have a single caller each.
"""

from __future__ import annotations

import types


class FakeTaskSnapshotStore:
    """A task table whose ``get_tasks()`` hands back a **copy**.

    The copy is the contract rather than an incidental detail:
    ``coordinator.py``'s purge deletes tasks while walking what ``get_tasks()``
    returned, which would raise on the live dict.
    """

    def __init__(self, tasks: dict) -> None:
        self._tasks = tasks

    def get_tasks(self) -> dict:
        return dict(self._tasks)


class FakeSyncStore:
    """The slice of ``store.py`` both to-do sync drivers touch.

    Tasks are handed out live here (the drivers only read them) and a completion
    records its origin, which is what proves a tick-off travelled inbound from
    somebody's list rather than from the panel. ``complete_error`` is how a test
    makes Home Keeper refuse a completion.

    The bookkeeping each driver persists — mirrored shopping items on one side,
    tracked to-do list entries on the other — is a differently named pair of
    methods, so each suite's subclass supplies those and bumps :attr:`writes`.
    """

    def __init__(self, tasks: dict | None = None) -> None:
        self._tasks = tasks or {}
        self.completed: list[tuple[str, str | None]] = []
        self.complete_error: Exception | None = None
        self.writes = 0

    def get_tasks(self) -> dict:
        return self._tasks

    async def complete_task(self, task_id, *, origin=None):
        if self.complete_error is not None:
            raise self.complete_error
        self.completed.append((task_id, origin))
        self._tasks.pop(task_id, None)
        return {}


class FakeSyncCoordinator:
    """The coordinator a to-do sync driver settles through."""

    def __init__(self, store) -> None:
        self.store = store
        self.settles = 0

    async def async_settle_buy_tasks(self) -> None:
        self.settles += 1


class FakeTodoServices:
    """Records ``todo.*`` calls and answers ``get_items`` from canned lists."""

    def __init__(self, lists):
        self._lists = lists
        self.calls: list[tuple[str, dict]] = []
        # Reads are counted separately from writes: "did this pass touch a to-do
        # list at all" is its own claim, and a test that only watched writes
        # would pass whether or not the read gate worked.
        self.reads: list[str] = []
        self.fail: set[str] = set()
        self.get_items_error: Exception | None = None

    async def async_call(self, domain, service, data, blocking=False, **kwargs):
        assert domain == "todo"
        if service == "get_items":
            self.reads.append(data["entity_id"])
            if self.get_items_error is not None:
                raise self.get_items_error
            entity_id = data["entity_id"]
            return {entity_id: {"items": list(self._lists.get(entity_id, []))}}
        self.calls.append((service, data))
        if service in self.fail:
            raise RuntimeError(f"{service} refused")
        return None


class FakeTodoHass:
    """The ``hass`` surface both to-do sync drivers reach for.

    ``_states`` is left empty for the subclass in each suite to fill: what a list
    advertises in ``supported_features`` is the thing those suites vary, and only
    the to-do list sync models an entity going ``unavailable``.
    """

    def __init__(self, lists) -> None:
        self.services = FakeTodoServices(lists)
        self._states: dict[str, object] = {}
        self.tasks: list = []

    @property
    def states(self):
        return types.SimpleNamespace(get=self._states.get)

    def async_create_task(self, coro) -> None:
        self.tasks.append(coro)
        coro.close()
