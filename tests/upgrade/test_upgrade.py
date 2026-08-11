"""What survives a pre-split → post-split Home Assistant upgrade (#183).

Home Assistant 2026.8 made device identifiers unique per config entry, so devices
that several integrations had merged onto are split apart on first boot. Home Keeper
attaches its per-task entities to devices it does not own, which puts it squarely in
the path of that migration.

Each test here is one scenario from the upgrade fixture. They share a single
``upgrade_run`` session fixture — the upgrade happens once, and every test reads the
same before/after snapshots.

Scenarios that are **expected to be broken today** are marked ``xfail(strict=True)``
so the suite documents the damage without going red, and turns into a hard failure
the moment a fix lands. Scenarios that pass are controls: they pin down what the
migration must *not* disturb.
"""

from __future__ import annotations

import pytest

SOURCE_DOMAIN = "hk_upgrade_source"
KITCHEN = "kitchen_sensor"
WATER_HEATER = "water_heater"
BAMBU_SERIAL = "AC12309BH109"

BN_GLUE_NS = "home_keeper_battery_notes"
BAMBU_GLUE_NS = "home_keeper_bambu_lab"
PAW_NS = "pawsistant"


# ── the fixture itself held together ─────────────────────────────────────────


def test_fixture_produced_the_expected_world(upgrade_run):
    """Guard rail: if seeding failed, every other result here is meaningless."""
    before = upgrade_run.before
    assert before["devices"], "no devices existed pre-upgrade"
    assert before["tasks"], "no Home Keeper tasks existed pre-upgrade"

    kitchen = [
        d
        for d in before["devices"]
        if any(list(i) == [SOURCE_DOMAIN, KITCHEN] for i in d.get("identifiers", []))
    ]
    assert kitchen, "the source kitchen sensor was never created"


# ── scenario 1: a plain task on a foreign device ─────────────────────────────


@pytest.mark.xfail(
    reason="HA 2026.8 forks a nameless duplicate rather than merging; see #183",
    strict=True,
)
def test_foreign_attached_task_keeps_its_device(upgrade_run):
    """A task attached to another integration's device must still point at it."""
    task = next(iter(upgrade_run.tasks_named("Upgrade probe foreign task")), None)
    assert task is not None, "the probe task did not survive the upgrade"

    device = upgrade_run.device(task["device_id"])
    assert device is not None, (
        f"task device_id {task['device_id']} resolves to nothing after the upgrade"
    )
    # A device that resolves but has no name is why #183 item 1 shows raw GUIDs:
    # HA's picker and the panel both fall back to the id when the name is unset.
    assert device.get("name") or device.get("name_by_user"), (
        f"task points at a nameless device ({device['id']}) — the UI will show its id"
    )
    assert any(
        list(i) == [SOURCE_DOMAIN, KITCHEN] for i in device.get("identifiers", [])
    ), "the task should still point at the source kitchen sensor"


@pytest.mark.xfail(
    reason="HA 2026.8 forks a duplicate device from the copied identifiers; see #183",
    strict=True,
)
def test_upgrade_does_not_leave_duplicate_devices(upgrade_run):
    """Exactly one device should carry the source device's identifiers."""
    carriers = upgrade_run.devices_with_identifier(SOURCE_DOMAIN, KITCHEN)
    assert len(carriers) == 1, (
        "the kitchen sensor's identifiers appear on "
        f"{len(carriers)} devices after the upgrade: "
        f"{[(d['id'], d.get('name'), d.get('config_entries')) for d in carriers]}"
    )


# ── scenarios 2 and 3: assets ────────────────────────────────────────────────


def test_virtual_asset_device_is_untouched(upgrade_run):
    """Control: a device Home Keeper owns outright has nothing to split."""
    assets = upgrade_run.tasks_named("Upgrade probe virtual asset")
    # The asset itself isn't a task; assert on the device instead.
    virtual = [
        d
        for d in upgrade_run.after["devices"]
        if d.get("name") == "Upgrade probe virtual asset"
    ]
    assert len(virtual) == 1, (
        f"expected exactly one virtual asset device, found {len(virtual)}"
    )
    assert virtual[0].get("name"), "a Home Keeper-owned device must keep its name"
    assert not assets, "sanity: the virtual asset should not have produced a task"


def test_existing_kind_asset_still_resolves_its_device(upgrade_run):
    """An asset decorating a foreign device should recover via its identifier snapshot.

    ``devices._resolve_by_snapshot`` exists for exactly this: the owning integration
    recreates the device under a new registry id and the asset re-finds it by stored
    identifiers/connections. The upgrade split is the same shape of event.
    """
    heaters = upgrade_run.devices_with_identifier(SOURCE_DOMAIN, WATER_HEATER)
    assert heaters, "the water heater vanished entirely"
    named = [d for d in heaters if d.get("name") or d.get("name_by_user")]
    assert named, (
        "no named device carries the water heater's identifiers after the upgrade"
    )


# ── scenarios 4-6: the three glue integrations ───────────────────────────────


def test_battery_notes_glue_task_survives(upgrade_run):
    """The glue's task should survive the upgrade (it is deletion-protected)."""
    tasks = upgrade_run.tasks_from(BN_GLUE_NS)
    assert tasks, "the Battery Notes glue task did not survive the upgrade"


def test_bambu_lab_glue_task_survives(upgrade_run):
    tasks = upgrade_run.tasks_from(BAMBU_GLUE_NS)
    assert tasks, "the Bambu Lab glue task did not survive the upgrade"


def test_pawsistant_task_survives(upgrade_run):
    tasks = upgrade_run.tasks_from(PAW_NS)
    assert tasks, "the Pawsistant task did not survive the upgrade"


def test_split_devices_keep_their_name(upgrade_run):
    """Both halves of a split device keep the name, unlike a fresh 2026.8 attach.

    Worth pinning because it separates the two ways #183 shows raw GUIDs:

    * *upgrade* path — the name is copied to both halves, but every registry **id**
      changes, so a stored ``device_id`` dangles (see the next test);
    * *fresh attach* path — ``device_info_for_task`` sends identifiers with no
      ``name``, so the forked device is nameless and the UI shows its id
      (``tests/integration/test_device_attach.py``).

    A fix has to handle both; neither one implies the other.
    """
    for domain, value in [("bambu_lab", BAMBU_SERIAL), (SOURCE_DOMAIN, KITCHEN)]:
        carriers = upgrade_run.devices_with_identifier(domain, value)
        assert carriers, f"({domain}, {value}) vanished entirely"
        nameless = [d for d in carriers if not (d.get("name") or d.get("name_by_user"))]
        assert not nameless, (
            f"({domain}, {value}) produced nameless device(s) after the split: "
            f"{[d['id'] for d in nameless]}"
        )


@pytest.mark.xfail(
    reason=(
        "HA 2026.8 renumbers both halves of a split device, dangling stored ids; #183"
    ),
    strict=True,
)
def test_stored_device_ids_still_resolve(upgrade_run):
    """Every Home Keeper task's ``device_id`` must still resolve after the upgrade.

    This is the root cause of #183 items 1 and 3. Splitting a merged device does not
    keep either half's registry id: the fixture's printer went from one device
    ``57c050c7…`` to two devices with entirely new ids. Any ``device_id`` persisted
    before the upgrade — Home Keeper's own, and the copies the glues keep in their
    ``source`` namespaces — points at nothing afterwards.
    """
    live = {d["id"] for d in upgrade_run.after["devices"]}
    dangling = [
        (t["name"], t["device_id"])
        for t in upgrade_run.after["tasks"]
        if t.get("device_id") and t["device_id"] not in live
    ]
    assert not dangling, (
        f"{len(dangling)} task(s) point at a dead device id: {dangling}"
    )


@pytest.mark.xfail(
    reason=("the copy inside source.<ns> dangles too, and is the re-keying bug; #183"),
    strict=True,
)
def test_source_namespace_device_ids_still_resolve(upgrade_run):
    """A contributor's *own* copy of the device id must resolve too.

    Separate from the test above on purpose. Healing only ``task["device_id"]`` would
    flip that one green while leaving this one red — and this is the copy that
    actually drives duplication, because bambu-lab and battery-notes match existing
    tasks on ``source.<ns>.device_id`` rather than on the task's field.

    So these two together are the real acceptance criterion for the auto-heal: a fix
    that satisfies only the first one is not a fix.
    """
    live = {d["id"] for d in upgrade_run.after["devices"]}
    dangling = []
    for task in upgrade_run.after["tasks"]:
        for namespace, payload in (task.get("source") or {}).items():
            if not isinstance(payload, dict):
                continue
            device_id = payload.get("device_id")
            if device_id and device_id not in live:
                dangling.append((task["name"], namespace, device_id))
    assert not dangling, (
        f"{len(dangling)} source namespace(s) hold a dead device id: {dangling}"
    )


# ── scenario 7: the decisive one ─────────────────────────────────────────────


_DUPLICATES_ON_UPGRADE = pytest.mark.xfail(
    reason=("glue re-keys on a stale source.device_id and creates a second task; #183"),
    strict=True,
)


@pytest.mark.parametrize(
    ("source_ns", "label"),
    [
        pytest.param(BN_GLUE_NS, "Battery Notes", marks=_DUPLICATES_ON_UPGRADE),
        pytest.param(BAMBU_GLUE_NS, "Bambu Lab", marks=_DUPLICATES_ON_UPGRADE),
        # No xfail: Pawsistant is expected to pass, and that is the point.
        pytest.param(PAW_NS, "Pawsistant"),
    ],
)
def test_glue_does_not_duplicate_its_task_after_the_upgrade(
    upgrade_run, source_ns, label
):
    """No glue should create a second task for the same real-world thing.

    Measured, not predicted: on this fixture Battery Notes and Bambu Lab each go from
    one task to two across the upgrade. Both store the device id twice — on the task
    *and* inside their ``source`` namespace — and match existing tasks on the
    ``source`` copy. The split renumbers the device, so that copy no longer matches
    anything; their reconcile creates a fresh task while the stale one persists
    (neither ``plan_reconcile`` deletes tasks whose device vanished).

    Pawsistant is the counter-example and the reference implementation: its ``source``
    namespace holds ``dog_id`` / ``event_type`` / ``schedule_id`` and no device id at
    all, so it re-keys durably no matter what the registry does. Any fix for the other
    two should move them to the same shape — and note bambu-lab already keys its
    *options* on the printer serial for exactly this reason (``wiring.py``), it just
    never applied that to task matching.

    This constrains the Home Keeper auto-heal too: healing only ``task["device_id"]``
    and leaving ``source.<ns>.device_id`` stale reproduces the same duplication.
    """
    tasks = upgrade_run.tasks_from(source_ns)
    before = [
        t for t in upgrade_run.before["tasks"] if (t.get("source") or {}).get(source_ns)
    ]
    assert len(tasks) <= len(before), (
        f"{label} went from {len(before)} to {len(tasks)} task(s) across the upgrade — "
        f"duplicates: {[t['name'] for t in tasks]}"
    )


def test_report_device_id_churn(upgrade_run, capsys):
    """Not an assertion — prints the before/after registry picture on every run.

    When one of the xfail scenarios above flips (or a new HA release changes the
    migration), this is the first thing to read: it shows which fixture devices were
    renumbered, how many carriers each identifier ended up with, and what each glue
    task points at on both sides of the upgrade.
    """

    def by_ident(snap, domain, value):
        return [
            (d["id"][:8], d.get("name"), tuple(d.get("config_entries") or ()))
            for d in snap["devices"]
            if any(list(i) == [domain, value] for i in d.get("identifiers", []))
        ]

    lines = ["", "=== device identifiers, before -> after ==="]
    for domain, value in [
        (SOURCE_DOMAIN, KITCHEN),
        (SOURCE_DOMAIN, WATER_HEATER),
        ("bambu_lab", BAMBU_SERIAL),
    ]:
        lines.append(f"({domain}, {value})")
        lines.append(f"  before: {by_ident(upgrade_run.before, domain, value)}")
        lines.append(f"  after : {by_ident(upgrade_run.after, domain, value)}")

    live = {d["id"] for d in upgrade_run.after["devices"]}
    lines.append("")
    lines.append("=== glue tasks, before -> after (! = device id no longer exists) ===")
    for ns in (BN_GLUE_NS, BAMBU_GLUE_NS, PAW_NS):
        lines.append(ns)
        for when, snap in (
            ("before", upgrade_run.before),
            ("after ", upgrade_run.after),
        ):
            for t in snap["tasks"]:
                src = (t.get("source") or {}).get(ns)
                if not src:
                    continue
                dev = t.get("device_id") or ""
                flag = (
                    "!" if when.strip() == "after" and dev and dev not in live else " "
                )
                lines.append(f"  {when} {flag} device={dev[:8]:<8} source={src}")

    with capsys.disabled():
        print("\n".join(lines))
