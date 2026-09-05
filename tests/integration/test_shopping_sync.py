"""Integration coverage for the shopping-list mirror, against a real to-do list.

The unit tier proves the planner and the driver in isolation; what only a real
Home Assistant can show is that ``todo.get_items`` / ``add_item`` /
``update_item`` / ``remove_item`` behave the way the driver assumes, and that a
tick-off on somebody else's list actually reaches the store. The container's
onboarding already sets up the built-in ``shopping_list``, so ``todo.shopping_list``
is here to mirror onto.

Each test owns the state it creates: the appliance is deleted, the option is put
back to off, and the items this suite left on the shopping list are cleared, so
the committed fixture is unchanged afterwards.
"""

import time

import pytest
from conftest import call_service

SHOPPING_LIST = "todo.shopping_list"
APPLIANCE = "Mirror test appliance"
# The line as it reads on the shopper's list. The part below restocks four at a
# time and is not measured in anything, so the mirror appends the multiplier; the
# task itself keeps its own plain name.
REMINDER = "Buy Mirror cartridge (×4)"


def _list_tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _list_assets(ha):
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    return resp.get("service_response", resp)["assets"]


def _items(ha, status=None):
    """The shopping list's items, optionally filtered by status."""
    data = {"entity_id": SHOPPING_LIST}
    if status is not None:
        data["status"] = status
    resp = call_service(ha, "todo", "get_items", data, return_response=True)
    body = resp.get("service_response", resp)
    return body[SHOPPING_LIST]["items"]


def _summaries(ha, status=None):
    return [item["summary"] for item in _items(ha, status)]


def _poll(fn, *, timeout=40):
    """First truthy ``fn()`` within *timeout*, tolerating mid-reload 500s.

    Creating or retiring a buy reminder settles through a **deferred** entry
    reload, so a read taken right after a stock change can transiently hit "No
    active coordinator" (same reason ``test_events._poll`` exists).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = fn()
            if value:
                return value
        except Exception:
            pass
        time.sleep(1)
    return None


def _call(ha, service, data):
    """Call a Home Keeper service, retrying through the deferred-reload window.

    Creating or retiring a buy reminder that owns device entities schedules an
    entry reload; a service call landing in that window 400s because there is no
    active coordinator yet. Retrying is what the rest of the suite does (see
    ``test_events._poll(_complete)``).
    """
    assert _poll(lambda: call_service(ha, "home_keeper", service, data) or True), (
        f"home_keeper.{service} never succeeded"
    )


def _set_target(ha, entity_id):
    _call(ha, "set_options", {"shopping_list_entity": entity_id})


def _clear_list(ha):
    """Remove everything this suite may have left on the shopping list."""
    leftovers = [
        item["uid"] for item in _items(ha) if item["summary"].startswith("Buy ")
    ]
    if leftovers:
        call_service(
            ha,
            "todo",
            "remove_item",
            {"entity_id": SHOPPING_LIST, "item": leftovers},
        )


@pytest.fixture
def mirrored(ha):
    """An appliance whose part is one step from low, mirroring onto the shopping list.

    Yields ``(asset_id, part_id, buy_task_getter)``.
    """
    call_service(
        ha,
        "home_keeper",
        "add_asset",
        {
            "name": APPLIANCE,
            "parts": [
                {
                    "name": "Mirror cartridge",
                    "type": "consumable",
                    "stock": 2,
                    "reorder_at": 1,
                    "create_buy_task": True,
                    "restock_quantity": 4,
                }
            ],
        },
    )
    asset = next(a for a in _list_assets(ha) if a["name"] == APPLIANCE)
    asset_id, part_id = asset["id"], asset["parts"][0]["id"]
    _set_target(ha, SHOPPING_LIST)

    def buy_task():
        for task in _list_tasks(ha):
            buy = (task.get("source") or {}).get("buy") or {}
            if buy.get("asset_id") == asset_id:
                return task
        return None

    try:
        yield asset_id, part_id, buy_task
    finally:
        _set_target(ha, "")
        try:
            call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset_id})
        except Exception:
            pass
        _clear_list(ha)


def _adjust_stock(ha, asset_id, part_id, delta):
    _call(
        ha,
        "adjust_part_stock",
        {"asset_id": asset_id, "part_id": part_id, "delta": delta},
    )


def test_a_low_part_reaches_the_shopping_list(ha, mirrored):
    asset_id, part_id, buy_task = mirrored
    # Nothing is on the list while the part is stocked above its threshold.
    assert REMINDER not in _summaries(ha)

    _adjust_stock(ha, asset_id, part_id, -1)
    assert _poll(buy_task), "expected a buy reminder once the part went low"
    assert _poll(lambda: REMINDER in _summaries(ha, ["needs_action"])), (
        "the reminder should have been mirrored onto the shopping list"
    )


def test_ticking_it_off_at_the_shop_restocks_the_part(ha, mirrored):
    """The whole point of the feature: the loop closes from the shopping list."""
    asset_id, part_id, buy_task = mirrored
    _adjust_stock(ha, asset_id, part_id, -1)
    assert _poll(buy_task), "expected a buy reminder once the part went low"
    item = _poll(
        lambda: next(
            (i for i in _items(ha, ["needs_action"]) if i["summary"] == REMINDER),
            None,
        )
    )
    assert item, "expected the mirrored item"

    # Tick it off the way the shopper would — on their own list, not in Home Keeper.
    call_service(
        ha,
        "todo",
        "update_item",
        {"entity_id": SHOPPING_LIST, "item": item["uid"], "status": "completed"},
    )

    def _restocked_and_cleared():
        asset = next((a for a in _list_assets(ha) if a["id"] == asset_id), None)
        return bool(asset) and asset["parts"][0]["stock"] == 5 and buy_task() is None

    assert _poll(_restocked_and_cleared), (
        "ticking the item off should have completed the reminder, restocked the "
        "part by its restock quantity (1 + 4), and retired the reminder"
    )
    # The line they ticked off is theirs — it stays on the list as their record,
    # and no fresh copy is put back while Home Keeper catches up.
    completed = _summaries(ha, ["completed"])
    assert REMINDER in completed
    assert REMINDER not in _summaries(ha, ["needs_action"])


def test_a_part_restocked_in_home_keeper_takes_its_line_off_the_list(ha, mirrored):
    asset_id, part_id, buy_task = mirrored
    _adjust_stock(ha, asset_id, part_id, -1)
    assert _poll(lambda: REMINDER in _summaries(ha, ["needs_action"]))

    # Topped up by hand: nothing was bought, so the line is not "done" — it goes.
    _adjust_stock(ha, asset_id, part_id, 5)
    assert _poll(lambda: buy_task() is None), "expected the reminder to retire"
    assert _poll(lambda: REMINDER not in _summaries(ha)), (
        "an unbought reminder must take its shopping-list line with it"
    )


def test_turning_the_mirror_off_clears_what_it_put_there(ha, mirrored):
    asset_id, part_id, _buy_task = mirrored
    _adjust_stock(ha, asset_id, part_id, -1)
    assert _poll(lambda: REMINDER in _summaries(ha, ["needs_action"]))

    _set_target(ha, "")
    assert _poll(lambda: REMINDER not in _summaries(ha)), (
        "switching the mirror off should clear the lines it added"
    )


def test_home_keepers_own_todo_list_is_refused_as_a_target(ha, mirrored):
    """Mirroring our own list onto itself is a loop; the option must not take."""
    asset_id, part_id, buy_task = mirrored
    _set_target(ha, "todo.home_keeper_tasks")
    _adjust_stock(ha, asset_id, part_id, -1)
    assert _poll(buy_task), "the reminder itself should still be created"
    # It lives on Home Keeper's own list as an ordinary task, but the mirror added
    # nothing — and, crucially, setting up did not error the entry.
    time.sleep(3)
    assert REMINDER not in _summaries(ha)
