"""Unit tests for the HA 2026.8 split repair in ``devices.py`` (#183).

Covers the three pieces of the repair:

* ``_resolve_by_snapshot`` — find a live device from an asset's stored
  identifiers/connections, either with no preference (reconciliation recovering a
  re-created device) or preferring the device that isn't ours (resolving a
  garbage-collected composite).
* ``_split_successor`` — the composite lookup, and its fallback to the snapshot
  once Home Assistant has garbage-collected the composite.
* ``async_heal_split_device_ids`` — which mapping is applied to what. A device's
  task and its asset share one mapping, so a composite only the *asset* can
  resolve still heals the task sitting on the same device.

``devices.py`` imports Home Assistant, so — like ``test_calendar.py`` and
``test_coordinator_purge.py`` — we load it over the shared stub tree in
``ha_stubs.py``, register a fake for its HA-aware ``store`` sibling, and load the
**real** ``devices.py`` under the synthetic ``hk`` package. The device registry is
then injected per-test by patching the module's ``dr`` binding, so the tests drive
the shipped functions rather than a copy of them — the stub tree's own registry
symbols exist only to let the import resolve. The real ``DeviceRegistry`` contract
itself is exercised by ``tests/upgrade/test_upgrade_repair.py`` against a genuine
Home Assistant.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

from ha_stubs import install_ha_stubs

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)

HK_ENTRY = "hk_config_entry"
ZWAVE_ENTRY = "zwave_entry"
SWITCHBOT_ENTRY = "switchbot_entry"


# ── loading the real module ──────────────────────────────────────────────────
def _load_devices() -> types.ModuleType:
    install_ha_stubs()
    # devices.py imports HomeKeeperStore for a type annotation only; the real
    # store.py imports Home Assistant, so a name-only stand-in is enough.
    store_mod = types.ModuleType("hk.store")
    store_mod.HomeKeeperStore = type("HomeKeeperStore", (), {})
    sys.modules.setdefault("hk.store", store_mod)

    spec = importlib.util.spec_from_file_location(
        "hk.devices", str(_COMPONENT_DIR / "devices.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hk.devices"] = module
    spec.loader.exec_module(module)
    # Other suites put a fake ``hk.options`` in ``sys.modules`` at import time, and
    # this one may import after them. The heal needs the real pure module, which
    # conftest loads as ``hk_options``.
    module.options = sys.modules["hk_options"]
    return module


devices = _load_devices()


# ── fakes ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FakeDevice:
    id: str
    config_entries: frozenset[str] = frozenset()
    identifiers: frozenset[tuple[str, ...]] = frozenset()
    connections: frozenset[tuple[str, ...]] = frozenset()
    primary_config_entry: str | None = None
    composite_device_id: str | None = None


class FakeRegistry:
    """The slice of ``DeviceRegistry`` the repair actually calls.

    ``async_get_device`` returns the **first registered** device carrying a
    requested identifier or connection, mirroring the real registry's single-device
    answer. That is what makes the foreign-preference test meaningful: registering
    our own half first means a naive "first match wins" resolver picks the wrong
    device, so the preference has to do real work to pass.

    ``splits`` maps a composite id to the devices it was split into. Omitting an id
    models Home Assistant having garbage-collected that composite (and is also the
    answer an ordinary, never-split id gets).
    """

    def __init__(
        self,
        devices_: list[FakeDevice],
        splits: dict[str, list[FakeDevice]] | None = None,
        *,
        supports_composites: bool = True,
    ):
        self.devices = {d.id: d for d in devices_}
        self._splits = splits or {}
        self.lookups = 0
        self.composite_lookups = 0
        # Bound per instance rather than declared on the class so that a pre-2026.8
        # registry genuinely *lacks* the attribute, which is what the production
        # ``getattr(..., None)`` probe checks for.
        if supports_composites:
            self.async_get_devices_for_composite_device_id = self._composite_splits

    def _composite_splits(self, device_id: str) -> list[FakeDevice]:
        self.composite_lookups += 1
        return list(self._splits.get(device_id, []))

    def async_get(self, device_id: str) -> FakeDevice | None:
        # A live device answers for itself; a collected composite answers with
        # nothing, because it is synthesized from devices that no longer exist.
        return self.devices.get(device_id)

    def async_get_device(
        self,
        identifiers: set[tuple[str, ...]] | None = None,
        connections: set[tuple[str, ...]] | None = None,
    ) -> FakeDevice | None:
        self.lookups += 1
        for device in self.devices.values():
            if identifiers and device.identifiers & identifiers:
                return device
            if connections and device.connections & connections:
                return device
        return None


class ModernFakeRegistry(FakeRegistry):
    """``FakeRegistry`` with Home Assistant 2026.9's ``devices`` shape.

    Up to 2026.8 ``DeviceRegistry.devices`` was a mapping keyed by device id, which is
    what :class:`FakeRegistry` models; from 2026.9 it is a collection of entries, so
    iterating it yields the entries themselves. The repair reads every device from it,
    so it has to cope with both — see ``device_compat.all_devices``.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        by_id = self.devices
        self.devices = _EntryCollection(by_id.values())
        self._by_id = by_id

    def async_get(self, device_id: str) -> FakeDevice | None:
        return self._by_id.get(device_id)


class _EntryCollection:
    """A collection of device entries: iterable, sized, and not a mapping."""

    def __init__(self, devices):
        self._devices = list(devices)

    def __iter__(self):
        return iter(self._devices)

    def __len__(self):
        return len(self._devices)


class FakeStore:
    """Task/asset storage with the two repoint methods the repair drives.

    The repoints mirror ``store.py``'s (including the ``source`` namespace copies
    contributors match on) and count their writes, so a test can assert both the
    healed state and that a settled install writes nothing.

    Private to this suite: it speaks a device-registry vocabulary (repoints, a
    duplicate merge, assets) that no other suite's store double shares a method
    with.
    """

    def __init__(self, tasks: dict | None = None, assets: list | None = None):
        self._tasks = tasks or {}
        self._assets = assets or []
        self.saves = 0
        self.merged: dict[str, str] | None = None
        # The order the heal drives the store in, and each task's device id as the
        # merge saw it. The merge only joins copies on 2 different halves, so it has
        # to see the ids before the repoint moves them onto one half (#417).
        self.calls: list[str] = []
        self.ids_at_merge: dict[str, str | None] = {}

    def get_tasks(self) -> dict:
        return self._tasks

    def list_assets(self) -> list[dict]:
        return list(self._assets)

    async def async_repoint_device_ids(self, mapping: dict[str, str]) -> int:
        self.calls.append("repoint")
        changed = 0
        for task in self._tasks.values():
            if (new_id := mapping.get(task.get("device_id") or "")) is not None:
                task["device_id"] = new_id
                changed += 1
            for payload in (task.get("source") or {}).values():
                if not isinstance(payload, dict):
                    continue
                if (new_id := mapping.get(payload.get("device_id") or "")) is not None:
                    payload["device_id"] = new_id
                    changed += 1
        if changed:
            self.saves += 1
        return changed

    async def async_repoint_asset_device_ids(self, mapping: dict[str, str]) -> int:
        changed = 0
        for asset in self._assets:
            if (new_id := mapping.get(asset.get("device_id") or "")) is not None:
                asset["device_id"] = new_id
                changed += 1
            related = asset.get("related_device_ids") or []
            if any(device_id in mapping for device_id in related):
                asset["related_device_ids"] = list(
                    dict.fromkeys(mapping.get(d, d) for d in related)
                )
                changed += 1
        if changed:
            self.saves += 1
        return changed

    async def async_merge_split_duplicates(self, canonical: dict[str, str]) -> int:
        self.calls.append("merge")
        self.merged = canonical
        self.ids_at_merge = {tid: t.get("device_id") for tid, t in self._tasks.items()}
        return 0


@dataclass
class FakeEntry:
    entry_id: str = HK_ENTRY
    options: dict = field(default_factory=dict)


class FakeConfigEntries:
    """Records each options write, and applies it as Home Assistant does."""

    def __init__(self) -> None:
        self.updates: list[dict] = []

    def async_update_entry(self, entry: FakeEntry, *, options: dict) -> None:
        self.updates.append(options)
        entry.options = options


def heal(
    registry: FakeRegistry, store: FakeStore, entry: FakeEntry | None = None
) -> FakeConfigEntries:
    """Run the real ``async_heal_split_device_ids`` against *registry*/*store*."""
    original = devices.dr
    devices.dr = types.SimpleNamespace(async_get=lambda hass: registry)
    config_entries = FakeConfigEntries()
    hass = types.SimpleNamespace(config_entries=config_entries)
    try:
        asyncio.run(
            devices.async_heal_split_device_ids(hass, entry or FakeEntry(), store)
        )
    finally:
        devices.dr = original
    return config_entries


def task(tid: str, device_id: str | None, source: dict | None = None) -> dict:
    return {"id": tid, "name": f"Task {tid}", "device_id": device_id, "source": source}


def existing_asset(
    aid: str,
    device_id: str | None,
    identifiers: list | None = None,
    connections: list | None = None,
) -> dict:
    return {
        "id": aid,
        "name": f"Asset {aid}",
        "kind": "existing",
        "device_id": device_id,
        "identifiers": identifiers or [],
        "connections": connections or [],
    }


# ── the real-world shapes these tests are built from ─────────────────────────
# A Z-Wave thermostat (resolvable by identifiers) and a Bluetooth coffee maker
# (resolvable only by connections), both attached before the 2026.8 split.
DEAD_THERMOSTAT = "620eef300819d798126579786ab84740"
DEAD_COFFEE = "abba09c890b6ce14049d67796271aa43"

THERMOSTAT_IDENTS = [["zwave_js", "4268179804-12"], ["zwave_js", "4268179804-12-57"]]
COFFEE_CONNECTIONS = [["bluetooth", "D0:65:85:16:4C:E2"], ["mac", "d0:65:85:16:4c:e2"]]

ZWAVE_DEVICE = FakeDevice(
    "zwave_real",
    config_entries=frozenset({ZWAVE_ENTRY}),
    identifiers=frozenset({("zwave_js", "4268179804-12-57")}),
)
COFFEE_DEVICE = FakeDevice(
    "coffee_real",
    config_entries=frozenset({SWITCHBOT_ENTRY}),
    connections=frozenset({("bluetooth", "D0:65:85:16:4C:E2")}),
)
# What the split left us holding: the identifier we copied onto our own half.
HK_HALF = FakeDevice(
    "hk_half",
    config_entries=frozenset({HK_ENTRY}),
    identifiers=frozenset({("zwave_js", "4268179804-12")}),
)


# ── _resolve_by_snapshot ─────────────────────────────────────────────────────
def test_snapshot_resolves_by_identifier():
    """Reconciliation's mode: no preference, the first matching identifier wins."""
    registry = FakeRegistry([ZWAVE_DEVICE])
    found = devices._resolve_by_snapshot(registry, {"identifiers": THERMOSTAT_IDENTS})
    assert found is ZWAVE_DEVICE


def test_snapshot_stops_at_the_first_hit_when_there_is_no_preference():
    """Reconciliation's mode does no lookups it cannot use.

    With no preference the answer is the first match, so sweeping the remaining
    identifiers and the connections is wasted work on every setup.
    """
    registry = FakeRegistry([ZWAVE_DEVICE])
    snapshot = {
        # First identifier matches; the rest (and the connections) must go unasked.
        "identifiers": [["zwave_js", "4268179804-12-57"], *THERMOSTAT_IDENTS],
        "connections": COFFEE_CONNECTIONS,
    }
    assert devices._resolve_by_snapshot(registry, snapshot) is ZWAVE_DEVICE
    assert registry.lookups == 1, (
        f"expected to stop after the first identifier, made {registry.lookups} lookups"
    )


def test_snapshot_falls_back_to_connections():
    """A device with no identifiers in the snapshot resolves via connections."""
    registry = FakeRegistry([COFFEE_DEVICE])
    found = devices._resolve_by_snapshot(
        registry, {"identifiers": [], "connections": COFFEE_CONNECTIONS}
    )
    assert found is COFFEE_DEVICE


def test_snapshot_prefers_the_device_that_is_not_ours():
    """Our own split half must lose to the real device, even when matched first.

    ``HK_HALF`` is registered first and carries the snapshot's *first* identifier,
    so it is what an unprefixed lookup returns. Only the foreign preference gets
    this to the Z-Wave device.
    """
    registry = FakeRegistry([HK_HALF, ZWAVE_DEVICE])

    naive = devices._resolve_by_snapshot(registry, {"identifiers": THERMOSTAT_IDENTS})
    assert naive is HK_HALF, "sanity: without a preference our half matches first"

    found = devices._resolve_by_snapshot(
        registry, {"identifiers": THERMOSTAT_IDENTS}, prefer_not_entry=HK_ENTRY
    )
    assert found is ZWAVE_DEVICE
    assert HK_ENTRY not in found.config_entries


def test_snapshot_multiple_foreign_picks_lowest_id():
    """Two foreign matches and nothing to choose between them: sorted by id."""
    dev_z = FakeDevice(
        "zzz",
        config_entries=frozenset({ZWAVE_ENTRY}),
        identifiers=frozenset({("zwave_js", "4268179804-12")}),
    )
    dev_a = FakeDevice(
        "aaa",
        config_entries=frozenset({SWITCHBOT_ENTRY}),
        identifiers=frozenset({("zwave_js", "4268179804-12-57")}),
    )
    # Registered "zzz" first so insertion order can't be what produces the answer.
    registry = FakeRegistry([dev_z, dev_a])
    found = devices._resolve_by_snapshot(
        registry, {"identifiers": THERMOSTAT_IDENTS}, prefer_not_entry=HK_ENTRY
    )
    assert found is dev_a, "the lowest device id wins, not the first match"


def test_snapshot_all_ours_still_resolves():
    """With no foreign candidate at all, our own device is better than nothing."""
    registry = FakeRegistry([HK_HALF])
    found = devices._resolve_by_snapshot(
        registry, {"identifiers": THERMOSTAT_IDENTS}, prefer_not_entry=HK_ENTRY
    )
    assert found is HK_HALF


def test_snapshot_no_match_returns_none():
    """Nothing in the registry matches: the caller skips healing this device."""
    assert (
        devices._resolve_by_snapshot(
            FakeRegistry([]), {"identifiers": THERMOSTAT_IDENTS}
        )
        is None
    )


def test_snapshot_without_stored_data_returns_none():
    """An asset predating snapshotting has nothing to resolve from."""
    registry = FakeRegistry([ZWAVE_DEVICE])
    assert (
        devices._resolve_by_snapshot(registry, {"identifiers": [], "connections": []})
        is None
    )


# ── _split_successor ─────────────────────────────────────────────────────────
def test_successor_prefers_the_foreign_split():
    """The live composite resolves to the other integration's half, not ours."""
    registry = FakeRegistry(
        [HK_HALF, ZWAVE_DEVICE], {DEAD_THERMOSTAT: [HK_HALF, ZWAVE_DEVICE]}
    )
    assert devices._split_successor(registry, DEAD_THERMOSTAT, HK_ENTRY) is ZWAVE_DEVICE


def test_successor_follows_the_composites_primary_entry():
    """Several foreign splits: the entry Home Assistant called primary decides."""
    zwave = FakeDevice("zwave_real", config_entries=frozenset({ZWAVE_ENTRY}))
    switchbot = FakeDevice("aaa_switchbot", config_entries=frozenset({SWITCHBOT_ENTRY}))
    composite = FakeDevice(DEAD_THERMOSTAT, primary_config_entry=ZWAVE_ENTRY)
    registry = FakeRegistry(
        [composite, zwave, switchbot],
        {DEAD_THERMOSTAT: [HK_HALF, zwave, switchbot]},
    )
    found = devices._split_successor(registry, DEAD_THERMOSTAT, HK_ENTRY)
    assert found is zwave, (
        "the primary entry's device wins over the alphabetically lower id"
    )


def test_successor_picks_deterministically_with_no_primary():
    """Several foreign splits and no primary named: lowest id, so runs agree."""
    zwave = FakeDevice("zwave_real", config_entries=frozenset({ZWAVE_ENTRY}))
    switchbot = FakeDevice("aaa_switchbot", config_entries=frozenset({SWITCHBOT_ENTRY}))
    composite = FakeDevice(DEAD_THERMOSTAT)  # no primary_config_entry
    registry = FakeRegistry(
        [composite, zwave, switchbot],
        {DEAD_THERMOSTAT: [HK_HALF, zwave, switchbot]},
    )
    found = devices._split_successor(registry, DEAD_THERMOSTAT, HK_ENTRY)
    assert found is switchbot, "with nothing to choose on, the lowest id wins"


def test_successor_none_before_composites_exist():
    """Pre-2026.8 Home Assistant has no composites, so there is nothing to heal."""
    registry = FakeRegistry([ZWAVE_DEVICE], supports_composites=False)
    assert (
        devices._split_successor(
            registry,
            DEAD_THERMOSTAT,
            HK_ENTRY,
            snapshot={"identifiers": THERMOSTAT_IDENTS},
        )
        is None
    ), "a registry with no composite concept must not be 'healed' from a snapshot"


def test_successor_falls_back_to_snapshot_when_composite_collected():
    """A garbage-collected composite still resolves through the asset's snapshot."""
    registry = FakeRegistry([HK_HALF, ZWAVE_DEVICE])  # no composite entry: GC'd
    assert devices._split_successor(registry, DEAD_THERMOSTAT, HK_ENTRY) is None, (
        "sanity: without a snapshot a collected composite is unresolvable"
    )
    found = devices._split_successor(
        registry,
        DEAD_THERMOSTAT,
        HK_ENTRY,
        snapshot={"identifiers": THERMOSTAT_IDENTS},
    )
    assert found is ZWAVE_DEVICE


# ── async_heal_split_device_ids ──────────────────────────────────────────────
def test_heal_repoints_task_and_asset():
    """The ordinary case: both kinds of reference follow the live split."""
    registry = FakeRegistry(
        [HK_HALF, ZWAVE_DEVICE], {DEAD_THERMOSTAT: [HK_HALF, ZWAVE_DEVICE]}
    )
    store = FakeStore(
        tasks={"t1": task("t1", DEAD_THERMOSTAT)},
        assets=[existing_asset("a1", DEAD_THERMOSTAT, THERMOSTAT_IDENTS)],
    )
    heal(registry, store)
    assert store.get_tasks()["t1"]["device_id"] == "zwave_real"
    assert store.list_assets()[0]["device_id"] == "zwave_real"


def test_heal_carries_a_snapshot_resolved_device_over_to_the_task():
    """A task on a collected composite heals off the asset that shares the device.

    The regression this guards: a task keeps no identifiers/connections, so once
    Home Assistant collects the composite the task alone cannot be resolved. Only
    the asset can — and healing them from separate mappings left the asset on the
    live device and the task still pointing at the dead id.
    """
    registry = FakeRegistry([ZWAVE_DEVICE])  # composite already collected
    store = FakeStore(
        tasks={
            "t1": task("t1", DEAD_THERMOSTAT, {"bambu": {"device_id": DEAD_THERMOSTAT}})
        },
        assets=[existing_asset("a1", DEAD_THERMOSTAT, THERMOSTAT_IDENTS)],
    )
    heal(registry, store)
    assert store.list_assets()[0]["device_id"] == "zwave_real"
    assert store.get_tasks()["t1"]["device_id"] == "zwave_real", (
        "the task must inherit the successor only the asset could resolve"
    )
    assert store.get_tasks()["t1"]["source"]["bambu"]["device_id"] == "zwave_real", (
        "the contributor's own copy has to move too or it recreates the task"
    )


def test_heal_resolves_a_connections_only_asset():
    """A Bluetooth appliance has no identifiers; connections carry the repair."""
    registry = FakeRegistry([COFFEE_DEVICE])
    store = FakeStore(
        tasks={"t1": task("t1", DEAD_COFFEE)},
        assets=[existing_asset("a1", DEAD_COFFEE, connections=COFFEE_CONNECTIONS)],
    )
    heal(registry, store)
    assert store.list_assets()[0]["device_id"] == "coffee_real"
    assert store.get_tasks()["t1"]["device_id"] == "coffee_real"


def test_heal_leaves_virtual_assets_alone():
    """A virtual asset's device is ours outright and was never split."""
    ours = FakeDevice("hk_virtual", config_entries=frozenset({HK_ENTRY}))
    registry = FakeRegistry([ours, ZWAVE_DEVICE])
    virtual = {
        "id": "a1",
        "kind": "virtual",
        "device_id": "hk_virtual",
        # Identifiers that *would* resolve elsewhere if the kind were ignored.
        "identifiers": THERMOSTAT_IDENTS,
        "connections": [],
    }
    store = FakeStore(assets=[virtual])
    heal(registry, store)
    assert virtual["device_id"] == "hk_virtual"
    assert store.saves == 0


def test_heal_is_a_no_op_once_everything_is_healed():
    """A settled install must not rewrite (or re-save) anything on every restart."""
    registry = FakeRegistry([ZWAVE_DEVICE])
    store = FakeStore(
        tasks={"t1": task("t1", "zwave_real")},
        assets=[existing_asset("a1", "zwave_real", THERMOSTAT_IDENTS)],
    )
    heal(registry, store)
    assert store.get_tasks()["t1"]["device_id"] == "zwave_real"
    assert store.list_assets()[0]["device_id"] == "zwave_real"
    assert store.saves == 0, "a healed store must not be written again"


def test_heal_skips_devices_it_cannot_resolve():
    """An unresolvable id is left as-is rather than pointed somewhere arbitrary."""
    registry = FakeRegistry([])
    store = FakeStore(
        tasks={"t1": task("t1", DEAD_THERMOSTAT)},
        assets=[existing_asset("a1", DEAD_COFFEE, connections=COFFEE_CONNECTIONS)],
    )
    heal(registry, store)
    assert store.get_tasks()["t1"]["device_id"] == DEAD_THERMOSTAT
    assert store.list_assets()[0]["device_id"] == DEAD_COFFEE
    assert store.saves == 0


def test_heal_will_not_repoint_a_device_that_is_still_alive():
    """A live device is never overridden by a snapshot that resolves elsewhere.

    An empty composite answer also means "ordinary id, never split", so the fallback
    has to tell the two apart or a drifted snapshot silently moves a healthy asset.
    Here the asset sits on a live device while its snapshot matches a *different*
    one — the sort of drift that happens when identifiers migrate between devices
    and the heal runs before ``_reconcile_existing`` refreshes the snapshot.
    """
    live = FakeDevice("still_here", config_entries=frozenset({SWITCHBOT_ENTRY}))
    registry = FakeRegistry([live, ZWAVE_DEVICE])
    store = FakeStore(
        tasks={"t1": task("t1", "still_here")},
        assets=[existing_asset("a1", "still_here", THERMOSTAT_IDENTS)],
    )
    heal(registry, store)
    assert store.list_assets()[0]["device_id"] == "still_here", (
        "a live device must win over a stale snapshot"
    )
    assert store.get_tasks()["t1"]["device_id"] == "still_here"
    assert store.saves == 0


def test_heal_resolves_each_dead_device_once():
    """Many tasks on one unresolvable device cost one lookup, not one apiece."""
    registry = FakeRegistry([])
    store = FakeStore(
        tasks={f"t{i}": task(f"t{i}", DEAD_THERMOSTAT) for i in range(25)}
    )
    heal(registry, store)
    assert registry.composite_lookups == 1, (
        "25 tasks on one dead device should resolve it once, got "
        f"{registry.composite_lookups} lookups"
    )


def test_heal_retries_an_unresolved_task_device_once_an_asset_supplies_a_snapshot():
    """The snapshot-less miss must not poison the asset's second attempt."""
    registry = FakeRegistry([ZWAVE_DEVICE])
    store = FakeStore(
        # Task first in iteration order, so its failure is cached before the asset
        # gets a chance to resolve the same id with a snapshot.
        tasks={"t1": task("t1", DEAD_THERMOSTAT)},
        assets=[existing_asset("a1", DEAD_THERMOSTAT, THERMOSTAT_IDENTS)],
    )
    heal(registry, store)
    assert store.get_tasks()["t1"]["device_id"] == "zwave_real"
    assert store.list_assets()[0]["device_id"] == "zwave_real"


def test_heal_feeds_the_composite_map_to_the_duplicate_merge():
    """Live devices still carrying a composite id are handed to the merge step."""
    survivor = FakeDevice(
        "zwave_real",
        config_entries=frozenset({ZWAVE_ENTRY}),
        composite_device_id=DEAD_THERMOSTAT,
    )
    store = FakeStore()
    heal(FakeRegistry([survivor]), store)
    assert store.merged == {"zwave_real": DEAD_THERMOSTAT}


def test_heal_reads_every_device_from_a_2026_9_shaped_registry():
    """The same merge map, off the collection-shaped ``devices`` of HA 2026.9 (#253).

    Iterating the old mapping yields device *ids*, so a helper that iterated the new
    collection the same way would hand the merge step strings instead of entries.
    """
    survivor = FakeDevice(
        "zwave_real",
        config_entries=frozenset({ZWAVE_ENTRY}),
        composite_device_id=DEAD_THERMOSTAT,
    )
    store = FakeStore()
    heal(ModernFakeRegistry([survivor]), store)
    assert store.merged == {"zwave_real": DEAD_THERMOSTAT}


def test_417_heal_merges_before_it_repoints():
    """The merge sees the old id and the new id, not two copies on one half (#417).

    A glue made its task on the merged device. After the split it found no task for
    its half and made a second one there. The repoint moves the first copy onto the
    same half, so a merge that ran after it would see one half and keep both.
    """
    bambu_half = FakeDevice(
        "bambu_half",
        config_entries=frozenset({ZWAVE_ENTRY}),
        composite_device_id=DEAD_THERMOSTAT,
    )
    hk_half = FakeDevice(
        "hk_half",
        config_entries=frozenset({HK_ENTRY}),
        composite_device_id=DEAD_THERMOSTAT,
    )
    registry = FakeRegistry(
        [hk_half, bambu_half], {DEAD_THERMOSTAT: [hk_half, bambu_half]}
    )
    glue = "home_keeper_bambu_lab"
    store = FakeStore(
        tasks={
            "old": task("old", DEAD_THERMOSTAT, {glue: {"device_id": DEAD_THERMOSTAT}}),
            "new": task("new", "bambu_half", {glue: {"device_id": "bambu_half"}}),
        }
    )
    heal(registry, store)
    assert store.calls == ["merge", "repoint"]
    assert store.ids_at_merge == {"old": DEAD_THERMOSTAT, "new": "bambu_half"}
    # The composite id is its own root, so the old copy and the new one share a key.
    assert store.merged == {
        "hk_half": DEAD_THERMOSTAT,
        "bambu_half": DEAD_THERMOSTAT,
        DEAD_THERMOSTAT: DEAD_THERMOSTAT,
    }


def test_417_a_collected_composite_maps_to_its_successors_root():
    """A dead id only a snapshot resolves joins the split its successor came from.

    Home Assistant has garbage-collected the composite, so no live device names it.
    Without the heal's answer the merge could not tell the old copy belongs to the
    same original as the new one.
    """
    survivor = FakeDevice(
        "zwave_real",
        config_entries=frozenset({ZWAVE_ENTRY}),
        identifiers=frozenset({("zwave_js", "4268179804-12-57")}),
        composite_device_id="older_composite",
    )
    store = FakeStore(
        tasks={"t1": task("t1", DEAD_THERMOSTAT)},
        assets=[existing_asset("a1", DEAD_THERMOSTAT, THERMOSTAT_IDENTS)],
    )
    heal(FakeRegistry([HK_HALF, survivor]), store)
    assert store.merged == {
        "zwave_real": "older_composite",
        DEAD_THERMOSTAT: "older_composite",
    }
    assert store.get_tasks()["t1"]["device_id"] == "zwave_real"


def test_417_a_resolved_id_with_no_split_root_maps_to_its_live_id():
    """A successor with no composite id gives the dead id its own live id as root.

    The merge then ignores it: a root that no split device carries is not a split.
    """
    store = FakeStore(
        tasks={"t1": task("t1", DEAD_THERMOSTAT)},
        assets=[existing_asset("a1", DEAD_THERMOSTAT, THERMOSTAT_IDENTS)],
    )
    heal(FakeRegistry([HK_HALF, ZWAVE_DEVICE]), store)
    assert store.merged == {DEAD_THERMOSTAT: "zwave_real"}


# ── X03-8: the other places that keep a device id ────────────────────────────
def test_x03_8_heal_repoints_related_devices_and_options():
    # The heal moved task and asset device ids only. An appliance's related devices,
    # a profile's device filters and the problem-sensor exclusions stayed on the dead
    # id, so the appliance lost the task and the filters matched nothing.
    registry = FakeRegistry(
        [HK_HALF, ZWAVE_DEVICE], {DEAD_THERMOSTAT: [HK_HALF, ZWAVE_DEVICE]}
    )
    appliance = {
        "id": "a1",
        "kind": "virtual",
        "device_id": "hk_virtual",
        "related_device_ids": [DEAD_THERMOSTAT, "zwave_real", "other"],
    }
    store = FakeStore(assets=[appliance])
    entry = FakeEntry(
        options={
            "problem_sensor_exclude_devices": [DEAD_THERMOSTAT],
            "profiles": [
                {
                    "id": "p1",
                    "filter": {
                        "groups": [
                            {"devices": [DEAD_THERMOSTAT], "exclude_devices": []}
                        ]
                    },
                }
            ],
        }
    )
    config_entries = heal(registry, store, entry)

    assert appliance["related_device_ids"] == ["zwave_real", "other"]
    assert config_entries.updates == [
        {
            "problem_sensor_exclude_devices": ["zwave_real"],
            "profiles": [
                {
                    "id": "p1",
                    "filter": {
                        "groups": [{"devices": ["zwave_real"], "exclude_devices": []}]
                    },
                }
            ],
        }
    ]


def test_x03_8_heal_writes_no_options_when_no_option_id_is_dead():
    registry = FakeRegistry(
        [HK_HALF, ZWAVE_DEVICE], {DEAD_THERMOSTAT: [HK_HALF, ZWAVE_DEVICE]}
    )
    store = FakeStore(tasks={"t1": task("t1", DEAD_THERMOSTAT)})
    entry = FakeEntry(options={"problem_sensor_exclude_devices": ["zwave_real"]})
    config_entries = heal(registry, store, entry)
    assert store.get_tasks()["t1"]["device_id"] == "zwave_real"
    assert config_entries.updates == []


# ── X13-1: the heal on a 2026.9 registry ─────────────────────────────────────
@dataclass(frozen=True)
class OwnedDevice:
    """A 2026.8+ device: one config entry, in ``config_entry_id``."""

    id: str
    config_entry_id: str
    identifiers: frozenset[tuple[str, ...]] = frozenset()
    connections: frozenset[tuple[str, ...]] = frozenset()


class NewLookupRegistry(FakeRegistry):
    """A registry with ``async_get_devices``; ``async_get_device`` must not run."""

    def async_get_device(self, identifiers=None, connections=None):
        raise AssertionError("async_get_device is deprecated in HA 2026.9")

    def async_get_devices(self, *, identifiers=None, connections=None):
        self.lookups += 1
        return [
            d
            for d in self.devices.values()
            if (identifiers and d.identifiers & identifiers)
            or (connections and d.connections & connections)
        ]


def test_x13_1_snapshot_resolves_through_async_get_devices():
    ours = OwnedDevice(
        "hk_half", HK_ENTRY, identifiers=frozenset({("zwave_js", "4268179804-12")})
    )
    theirs = OwnedDevice(
        "zwave_real",
        ZWAVE_ENTRY,
        identifiers=frozenset({("zwave_js", "4268179804-12")}),
    )
    registry = NewLookupRegistry([ours, theirs])
    found = devices._resolve_by_snapshot(
        registry, {"identifiers": THERMOSTAT_IDENTS}, prefer_not_entry=HK_ENTRY
    )
    assert found is theirs


def test_x13_1_split_successor_reads_config_entry_id():
    ours = OwnedDevice("hk_half", HK_ENTRY)
    theirs = OwnedDevice("zwave_real", ZWAVE_ENTRY)
    registry = NewLookupRegistry([ours, theirs], {DEAD_THERMOSTAT: [ours, theirs]})
    assert devices._split_successor(registry, DEAD_THERMOSTAT, HK_ENTRY) is theirs
