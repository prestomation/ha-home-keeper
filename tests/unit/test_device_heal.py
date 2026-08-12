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
``test_coordinator_purge.py`` — we stub the handful of HA symbols it references,
register a fake for its HA-aware ``store`` sibling, and load the **real**
``devices.py`` under the synthetic ``hk`` package. The device registry is then
injected per-test by patching the module's ``dr`` binding, so the tests drive the
shipped functions rather than a copy of them. The real ``DeviceRegistry`` contract
itself is exercised by ``tests/upgrade/test_upgrade_repair.py`` against a genuine
Home Assistant.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)

HK_ENTRY = "hk_config_entry"
ZWAVE_ENTRY = "zwave_entry"
SWITCHBOT_ENTRY = "switchbot_entry"


# ── loading the real module ──────────────────────────────────────────────────
def _real_ha_present() -> bool:
    """True only when the *real* Home Assistant package is installed.

    A hand-built stub ``homeassistant`` module (e.g. from ``test_calendar.py``) has
    no ``__file__``; the real package does. This distinguishes them so we fill gaps
    over a stub tree but never shadow real submodules.
    """
    mod = sys.modules.get("homeassistant")
    if mod is None:
        try:  # pragma: no cover - depends on environment
            import homeassistant as mod  # type: ignore[no-redef]
        except ImportError:
            return False
    return getattr(mod, "__file__", None) is not None


def _install_ha_stubs() -> None:
    """Additively register the HA symbols ``devices.py`` imports.

    Idempotent and non-clobbering, on the same contract as ``test_calendar.py`` and
    ``test_coordinator_purge.py``: those install their own partial ``homeassistant``
    stub trees, so we only *fill gaps* rather than early-return or overwrite, and
    load order between the suites stays irrelevant.
    """
    if _real_ha_present():  # pragma: no cover - real HA env
        return

    def _mod(name: str) -> types.ModuleType:
        existing = sys.modules.get(name)
        if existing is not None:
            return existing
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    _mod("homeassistant")
    _mod("homeassistant.helpers")
    for name, attrs in (
        ("homeassistant.config_entries", ("ConfigEntry",)),
        ("homeassistant.core", ("HomeAssistant",)),
        ("homeassistant.helpers.area_registry", ("async_get",)),
        (
            "homeassistant.helpers.device_registry",
            (
                "async_get",
                "async_entries_for_config_entry",
                "DeviceRegistry",
                "DeviceEntry",
            ),
        ),
        (
            "homeassistant.helpers.entity_registry",
            ("async_get", "async_entries_for_device"),
        ),
    ):
        module = _mod(name)
        for attr in attrs:
            if not hasattr(module, attr):
                setattr(module, attr, type(attr, (), {}))


def _load_devices() -> types.ModuleType:
    _install_ha_stubs()
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


class FakeStore:
    """Task/asset storage with the two repoint methods the repair drives.

    The repoints mirror ``store.py``'s (including the ``source`` namespace copies
    contributors match on) and count their writes, so a test can assert both the
    healed state and that a settled install writes nothing.
    """

    def __init__(self, tasks: dict | None = None, assets: list | None = None):
        self._tasks = tasks or {}
        self._assets = assets or []
        self.saves = 0
        self.merged: dict[str, str] | None = None

    def get_tasks(self) -> dict:
        return self._tasks

    def list_assets(self) -> list[dict]:
        return list(self._assets)

    async def async_repoint_device_ids(self, mapping: dict[str, str]) -> int:
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
        if changed:
            self.saves += 1
        return changed

    async def async_merge_split_duplicates(self, canonical: dict[str, str]) -> int:
        self.merged = canonical
        return 0


@dataclass
class FakeEntry:
    entry_id: str = HK_ENTRY


def heal(registry: FakeRegistry, store: FakeStore) -> None:
    """Run the real ``async_heal_split_device_ids`` against *registry*/*store*."""
    original = devices.dr
    devices.dr = types.SimpleNamespace(async_get=lambda hass: registry)
    try:
        asyncio.run(devices.async_heal_split_device_ids(object(), FakeEntry(), store))
    finally:
        devices.dr = original


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
