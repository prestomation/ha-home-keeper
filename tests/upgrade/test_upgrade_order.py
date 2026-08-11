"""Does it matter whether Home Assistant or Home Keeper is upgraded first? (#183)

Three orders reach the same end state on paper, and a user picks one without
thinking about it:

* **together** — both updated in one sitting (``upgrade_run``);
* **HA first** — Home Assistant 2026.8 lands while Home Keeper is still the old
  version, and the fix arrives later (``ha_first_run``). This is what everyone who
  reported #183 actually did;
* **Home Keeper first** — the fix is installed while still on Home Assistant 2026.7,
  and Home Assistant is upgraded afterwards (``hk_first_run``).

They are not equivalent, and the difference is worth knowing precisely, because it
is the only advice this project can give someone who has not upgraded yet.

Each order gets its own container run, so this module is the slow part of the suite.
The shared checks live in ``_assess`` so the three orders are compared on exactly the
same criteria rather than on three hand-written variants that could drift.
"""

from __future__ import annotations

import pytest

SOURCE_DOMAIN = "hk_upgrade_source"
KITCHEN = "kitchen_sensor"
BAMBU_SERIAL = "AC12309BH109"


def _assess(run) -> dict:
    """Summarize the damage in one upgrade run, in comparable terms."""
    live = {d["id"] for d in run.after["devices"]}

    ours_but_foreign = [
        (d["id"][:8], d.get("name"))
        for d in run.after["devices"]
        if any("home_keeper" in e for e in d.get("config_entries") or ())
        and not any(
            i[0] == "home_keeper" for i in d.get("identifiers", []) if len(i) == 2
        )
    ]
    dangling = [
        (t["name"], (t.get("device_id") or "")[:8])
        for t in run.after["tasks"]
        if t.get("device_id") and t["device_id"] not in live
    ]
    duplicate_tasks = {}
    for namespace in (
        "home_keeper_battery_notes",
        "home_keeper_bambu_lab",
        "pawsistant",
    ):
        before = [
            t for t in run.before["tasks"] if (t.get("source") or {}).get(namespace)
        ]
        after = [
            t for t in run.after["tasks"] if (t.get("source") or {}).get(namespace)
        ]
        if len(after) > len(before):
            duplicate_tasks[namespace] = (len(before), len(after))

    return {
        "devices_we_own_but_did_not_create": ours_but_foreign,
        "tasks_pointing_at_a_dead_device": dangling,
        "glues_that_duplicated": duplicate_tasks,
    }


def _report(label: str, verdict: dict) -> str:
    lines = [f"--- {label} ---"]
    for key, value in verdict.items():
        lines.append(f"  {key}: {value if value else 'none'}")
    return "\n".join(lines)


# What Home Keeper is answerable for is `devices_we_own_but_did_not_create`: a device
# carrying our config entry that we never created. That is the thing the old identifier
# copy caused, and the thing Home Assistant splits on upgrade.
#
# The other two measures can be dirtied by an integration that isn't us. In this
# fixture the `battery_notes` stub merges onto the kitchen sensor (reproducing
# pre-2026.8 Battery Notes), so Home Assistant splits *that* device whatever Home
# Keeper does, stranding the tasks pointed at it. Asserting on those would make this
# suite fail for someone else's behaviour, so they are reported, not asserted.
OUR_FAULT = "devices_we_own_but_did_not_create"


@pytest.mark.xfail(
    reason="upgrading Home Assistant first leaves devices we never created; #183",
    strict=True,
)
def test_upgrading_home_assistant_first_is_clean(ha_first_run, capsys):
    """The order the #183 reporters took, and the one that can't be repaired in place.

    By the time the fixed Home Keeper loads, Home Assistant has already split the
    merged devices and handed us our own halves. Nothing this version does at setup
    can undo that, because those halves hold our entities.
    """
    verdict = _assess(ha_first_run)
    with capsys.disabled():
        print("\n" + _report("HA first, Home Keeper later", verdict))
    assert not verdict[OUR_FAULT], verdict


def test_upgrading_home_keeper_first_avoids_our_damage(hk_first_run, capsys):
    """Updating Home Keeper **before** Home Assistant avoids the damage we cause.

    This is the whole reason for measuring the orders, and it is the advice in the
    2026.8 migration guide. The mechanism: on the older Home Assistant this version
    detaches our config entry from every device an earlier release merged onto
    (``devices.async_detach_legacy_merged_devices``), so when Home Assistant later
    performs its split there is nothing of ours joined to those devices to split.

    Measured against the same fixture that shows three ghost devices for the other two
    orders. The residual dangling tasks reported here belong to the ``battery_notes``
    stub's own merge, not to us — see the comment above ``OUR_FAULT``.
    """
    verdict = _assess(hk_first_run)
    with capsys.disabled():
        print("\n" + _report("Home Keeper first, HA later", verdict))
    assert not verdict[OUR_FAULT], (
        "updating Home Keeper first should leave no device carrying our config entry "
        f"that we did not create: {verdict[OUR_FAULT]}"
    )


def test_home_keeper_first_is_the_best_order(
    upgrade_run, ha_first_run, hk_first_run, capsys
):
    """Updating Home Keeper first must not be worse than the alternatives, anywhere.

    ``test_upgrading_home_keeper_first_avoids_our_damage`` asserts only on the measure
    Home Keeper is answerable for, which leaves a hole: the other two measures could
    quietly get worse and that test would still pass. This closes it by comparing the
    orders against **each other** rather than against a hardcoded baseline — a magic
    number would need updating every time the fixture changes, and would say nothing
    about the claim actually being made.

    And the claim being made is exactly this: the migration guide tells users to update
    Home Keeper first. That advice is only honest if this order is no worse than the
    others on every measure, which is what this asserts.
    """
    together = _assess(upgrade_run)
    ha_first = _assess(ha_first_run)
    hk_first = _assess(hk_first_run)

    with capsys.disabled():
        print()
        print(_report("both together", together))
        print(_report("HA first, Home Keeper later", ha_first))
        print(_report("Home Keeper first, HA later", hk_first))

    for measure in hk_first:
        ours = len(hk_first[measure])
        for label, other in (("HA first", ha_first), ("both together", together)):
            assert ours <= len(other[measure]), (
                f"updating Home Keeper first is worse than {label} on {measure} "
                f"({ours} vs {len(other[measure])}) — the migration guide's advice "
                "is no longer correct"
            )
