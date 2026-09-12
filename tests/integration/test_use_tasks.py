"""Integration tests for counted wear items, against the real Home Assistant container.

The unit tier proves the pure arithmetic. This tier is the one that can see the Home
Assistant contracts the feature actually rides on — the service call that records a
use, the settle step that arms the replacement task, the to-do entity that lists the
use task, and the calendar that must not. Per the #183 lesson, anything resting on a
framework contract needs an assertion at this level; a unit test mocks the framework
and cannot see it change.
"""

import time
import uuid

from conftest import call_service, list_states

# The Home Assistant container keeps its store between runs, so a fixed appliance name
# matches whatever a previous run left behind — and the helper below would then find
# that appliance and read *its* completions instead of this run's. One suffix per run
# keeps every test working on records it created itself.
RUN = uuid.uuid4().hex[:8]


def _assets(ha):
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    return resp.get("service_response", resp)["assets"]


def _tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _find(items, predicate, *, tries=20):
    """Poll for a record the reconciler creates asynchronously."""
    for _ in range(tries):
        match = next((item for item in items() if predicate(item)), None)
        if match is not None:
            return match
        time.sleep(1)
    return None


def _counted_appliance(ha, name, *, target=3, **part):
    """Add an appliance with 1 counted wear item and return its 2 derived tasks."""
    name = f"{name} {RUN}"
    call_service(
        ha,
        "home_keeper",
        "add_asset",
        {
            "name": name,
            "parts": [
                {
                    "name": "Coating",
                    "type": "wear",
                    "replace_interval": target,
                    "replace_unit": "uses",
                    "use_noun": "wears",
                    **part,
                }
            ],
        },
    )
    asset = _find(lambda: _assets(ha), lambda a: a["name"] == name)
    assert asset, f"appliance {name!r} was never listed"

    def _derived(role):
        def match(task):
            src = (task.get("source") or {}).get("part") or {}
            if src.get("asset_id") != asset["id"]:
                return False
            return (src.get("role") or "replace") == role

        return _find(lambda: _tasks(ha), match)

    use_task = _derived("use")
    replace_task = _derived("replace")
    assert use_task, "no use task was generated for the counted wear item"
    assert replace_task, "no replacement task was generated for the counted wear item"
    return asset, use_task, replace_task


def _reload(ha, task_id):
    return next(task for task in _tasks(ha) if task["id"] == task_id)


def _complete(ha, task_id):
    call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})


def test_a_counted_wear_item_generates_both_tasks(ha):
    _asset, use_task, replace_task = _counted_appliance(ha, "Counted jacket")
    assert use_task["recurrence_type"] == "use"
    assert replace_task["recurrence_type"] == "triggered"


def test_both_tasks_start_off_every_time_surface(ha):
    """A counted wear item has earned nothing when it is created.

    ``build_task`` arms a triggered task, so without the reconciler's explicit reset
    every counted wear item would ship overdue the moment its part is saved.
    """
    _asset, use_task, replace_task = _counted_appliance(ha, "Dormant jacket")
    assert use_task["next_due"] is None
    assert replace_task["next_due"] is None


def test_completing_the_use_task_counts_and_arms_nothing_early(ha):
    _asset, use_task, replace_task = _counted_appliance(ha, "Early jacket", target=3)
    _complete(ha, use_task["id"])
    time.sleep(2)
    assert len(_reload(ha, use_task["id"])["completions"]) == 1
    # Still dormant: 1 of 3.
    assert _reload(ha, use_task["id"])["next_due"] is None
    assert _reload(ha, replace_task["id"])["next_due"] is None


def test_the_replacement_task_arms_at_the_target(ha):
    _asset, use_task, replace_task = _counted_appliance(ha, "Armed jacket", target=3)
    for _ in range(3):
        _complete(ha, use_task["id"])
        time.sleep(1)
    armed = _find(
        lambda: _tasks(ha),
        lambda task: task["id"] == replace_task["id"] and task["next_due"] is not None,
    )
    assert armed, "the replacement task did not arm at its target"
    # The use task itself is still dateless, and still counting.
    assert _reload(ha, use_task["id"])["next_due"] is None


def test_completing_the_replacement_restarts_the_count(ha):
    _asset, use_task, replace_task = _counted_appliance(ha, "Restart jacket", target=2)
    for _ in range(2):
        _complete(ha, use_task["id"])
        time.sleep(1)
    assert _find(
        lambda: _tasks(ha),
        lambda task: task["id"] == replace_task["id"] and task["next_due"] is not None,
    )
    _complete(ha, replace_task["id"])
    time.sleep(2)
    # Dormant again, and the next cycle starts from zero — the completion log is
    # untouched, so the reset is the moving boundary rather than a wiped list.
    assert _reload(ha, replace_task["id"])["next_due"] is None
    assert len(_reload(ha, use_task["id"])["completions"]) == 2


def test_a_use_completion_consumes_no_spare(ha):
    """``_stamp_part_replacement`` fires on any part source, so this needs a gate.

    Without it every wear of the jacket would draw a spare out of inventory and stamp
    the maintenance as done — the count would arm a reminder for work that never
    happened while the stock quietly emptied.
    """
    asset, use_task, _replace = _counted_appliance(
        ha, "Stocked jacket", target=5, stock=4, reorder_at=1
    )
    _complete(ha, use_task["id"])
    time.sleep(2)
    after = next(a for a in _assets(ha) if a["id"] == asset["id"])
    part = after["parts"][0]
    assert part["stock"] == 4, "a use drew down the spare stock"
    assert not part.get("last_replaced"), "a use stamped the part as replaced"


def test_completing_the_replacement_does_consume_a_spare(ha):
    """The other half of the gate: the replacement still behaves as it always did."""
    asset, use_task, replace_task = _counted_appliance(
        ha, "Consuming jacket", target=1, stock=4, reorder_at=1
    )
    _complete(ha, use_task["id"])
    assert _find(
        lambda: _tasks(ha),
        lambda task: task["id"] == replace_task["id"] and task["next_due"] is not None,
    )
    _complete(ha, replace_task["id"])
    time.sleep(2)
    after = next(a for a in _assets(ha) if a["id"] == asset["id"])
    part = after["parts"][0]
    assert part["stock"] == 3, "completing the replacement did not consume a spare"
    assert part["last_replaced"], "completing the replacement did not stamp the date"


def test_the_use_task_is_on_the_todo_list_as_an_undated_item(ha):
    """The one-tap surface a household already has on its phone."""
    _asset, use_task, _replace = _counted_appliance(ha, "Listed jacket")
    # Home Keeper's **own** to-do entity, by id. The seed also carries the household
    # shopping list and a profile-synced list, so picking the first `todo.` entity
    # found the shopping list instead — a test that passed or failed on entity order.
    todo = _find(
        lambda: list_states(ha),
        lambda s: s["entity_id"] == "todo.home_keeper_tasks",
    )
    assert todo, "the Home Keeper to-do entity was not found"
    resp = call_service(
        ha,
        "todo",
        "get_items",
        {"entity_id": todo["entity_id"]},
        return_response=True,
    )
    payload = resp.get("service_response", resp)
    items = next(iter(payload.values()))["items"]
    match = next((i for i in items if i["uid"] == use_task["id"]), None)
    assert match, "the use task is not on the to-do list"
    assert not match.get("due"), "the use task should be an undated item"


def test_the_use_task_yields_no_calendar_event(ha):
    """The calendar builds events from ``next_due``. No date, no event."""
    _asset, use_task, _replace = _counted_appliance(ha, "Uncalendared jacket")
    calendar = _find(
        lambda: list_states(ha), lambda s: s["entity_id"].startswith("calendar.")
    )
    assert calendar, "no Home Keeper calendar entity was found"
    resp = call_service(
        ha,
        "calendar",
        "get_events",
        {
            "entity_id": calendar["entity_id"],
            "start_date_time": "2020-01-01 00:00:00",
            "end_date_time": "2040-01-01 00:00:00",
        },
        return_response=True,
    )
    payload = resp.get("service_response", resp)
    events = next(iter(payload.values()))["events"]
    assert not any(e.get("summary") == use_task["name"] for e in events)


def test_the_time_backstop_arms_without_any_use(ha):
    """A part last replaced long ago is due on the clock alone.

    The count and the backstop share their anchor, so 1 completion resets both. Here
    nothing has been used at all — only the backstop can bring this due.
    """
    _asset, _use_task, replace_task = _counted_appliance(
        ha,
        "Backstop jacket",
        target=99,
        last_replaced="2020-01-01",
        replace_also_every={"interval": 1, "unit": "months"},
    )
    armed = _find(
        lambda: _tasks(ha),
        lambda task: task["id"] == replace_task["id"] and task["next_due"] is not None,
        tries=30,
    )
    assert armed, "the time backstop did not arm the replacement task"
