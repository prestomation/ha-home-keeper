"""Appliance device reconcile in ``devices.py``.

* B17-5: a recovered existing-device appliance takes its tasks to the new device.
* B17-8: a stored parent that is not a virtual appliance gives no ``via_device``
  link.
* B17-9: an area that a user sets on the device page stays until the area of the
  appliance changes in Home Keeper.

``devices.py`` loads the way ``test_device_heal.py`` loads it, and this suite uses
that suite's registry and store fakes.
"""

from __future__ import annotations

import asyncio
import types
from dataclasses import dataclass, replace

import pytest
from test_device_heal import (
    FakeDevice,
    FakeEntry,
    FakeRegistry,
    FakeStore,
    devices,
    existing_asset,
    task,
)


class _Store(FakeStore):
    def __init__(self, tasks=None, assets=None):
        super().__init__(tasks, assets)
        self.persisted = 0
        self.device_ids: dict[str, str] = {}

    def get_asset(self, asset_id):
        return next((a for a in self._assets if a["id"] == asset_id), None)

    async def async_persist(self) -> None:
        self.persisted += 1

    async def set_asset_device_id(self, asset_id: str, device_id: str) -> None:
        self.device_ids[asset_id] = device_id


def _run(coro, registry):
    original = devices.dr
    devices.dr = types.SimpleNamespace(
        async_get=lambda hass: registry,
        async_entries_for_config_entry=lambda reg, entry_id: [],
    )
    try:
        return asyncio.run(coro)
    finally:
        devices.dr = original


# ── B17-5 ────────────────────────────────────────────────────────────────────
NEW_DEVICE = FakeDevice(
    "dev_new",
    config_entries=frozenset({"zwave_entry"}),
    identifiers=frozenset({("zwave_js", "node-7")}),
)


def test_b17_5_a_recovered_appliance_takes_its_tasks():
    asset = existing_asset("a1", "dev_old", identifiers=[["zwave_js", "node-7"]])
    store = _Store(
        tasks={
            "t1": task("t1", "dev_old"),
            "t2": task("t2", "dev_other"),
            "t3": task("t3", None, source={"glue": {"device_id": "dev_old"}}),
        },
        assets=[asset],
    )
    hass = types.SimpleNamespace(data={})

    _run(
        devices.async_reconcile_assets(hass, FakeEntry(), store),
        FakeRegistry([NEW_DEVICE]),
    )

    assert asset["device_id"] == "dev_new"
    assert store.persisted == 1
    assert store.get_tasks()["t1"]["device_id"] == "dev_new"
    assert store.get_tasks()["t2"]["device_id"] == "dev_other"
    assert store.get_tasks()["t3"]["source"]["glue"]["device_id"] == "dev_new"


def test_b17_5_a_live_appliance_moves_no_task():
    asset = existing_asset("a1", "dev_new", identifiers=[["zwave_js", "node-7"]])
    store = _Store(tasks={"t1": task("t1", "dev_new")}, assets=[asset])

    _run(
        devices.async_reconcile_assets(
            types.SimpleNamespace(data={}), FakeEntry(), store
        ),
        FakeRegistry([NEW_DEVICE]),
    )

    assert store.saves == 0
    assert store.get_tasks()["t1"]["device_id"] == "dev_new"


# ── B17-8 and B17-9: the virtual device ──────────────────────────────────────
@dataclass(frozen=True)
class _VirtualDevice:
    id: str
    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    area_id: str | None = None
    configuration_url: str | None = None
    via_device_id: str | None = None


_UNSET = object()


class _VirtualRegistry:
    """``async_get_or_create`` and ``async_update_device`` with 2026.9 kwargs.

    ``supports_kwarg`` reads the signatures, so both name each field the
    reconcile can pass.
    """

    def __init__(self, device: _VirtualDevice) -> None:
        self.device = device
        self.created: list[dict] = []
        self.updates: list[dict] = []

    def async_get(self, device_id):
        return (
            types.SimpleNamespace(id=device_id) if device_id == "parent_dev" else None
        )

    def async_get_or_create(
        self,
        *,
        config_entry_id,
        identifiers,
        name,
        manufacturer,
        model,
        configuration_url,
        via_device_id=None,
    ):
        self.created.append({"via_device_id": via_device_id})
        return self.device

    def async_update_device(
        self,
        device_id,
        *,
        name=_UNSET,
        manufacturer=_UNSET,
        model=_UNSET,
        serial_number=_UNSET,
        area_id=_UNSET,
        configuration_url=_UNSET,
        via_device_id=_UNSET,
    ):
        sent = {
            key: value
            for key, value in {
                "name": name,
                "manufacturer": manufacturer,
                "model": model,
                "serial_number": serial_number,
                "area_id": area_id,
                "configuration_url": configuration_url,
                "via_device_id": via_device_id,
            }.items()
            if value is not _UNSET
        }
        self.updates.append(sent)
        self.device = replace(self.device, **sent)
        return self.device


def _registry(device: _VirtualDevice) -> _VirtualRegistry:
    return _VirtualRegistry(device)


def _virtual(asset_id: str, **extra) -> dict:
    return {"id": asset_id, "name": f"Asset {asset_id}", "kind": "virtual", **extra}


def _reconcile(registry, store, asset, hass=None):
    hass = hass or types.SimpleNamespace(data={})
    original = devices.area_exists
    devices.area_exists = lambda hass, area_id: True
    try:
        asyncio.run(
            devices._reconcile_virtual(hass, FakeEntry(), store, registry, asset)
        )
    finally:
        devices.area_exists = original
    return hass


def test_b17_8_an_existing_kind_parent_gives_no_via_link():
    parent = existing_asset("p1", "foreign_dev")
    child = _virtual("c1", parent_asset_id="p1")
    store = _Store(assets=[parent, child])
    registry = _registry(_VirtualDevice("dev1", name="Asset c1"))

    _reconcile(registry, store, child)

    assert registry.created == [{"via_device_id": None}]
    assert all("via_device_id" not in update for update in registry.updates)


def test_b17_8_an_existing_kind_parent_clears_an_old_via_link():
    parent = existing_asset("p1", "foreign_dev")
    child = _virtual("c1", parent_asset_id="p1")
    store = _Store(assets=[parent, child])
    registry = _registry(
        _VirtualDevice("dev1", name="Asset c1", via_device_id="foreign_dev")
    )

    _reconcile(registry, store, child)

    assert [u["via_device_id"] for u in registry.updates if "via_device_id" in u] == [
        None
    ]
    assert registry.device.via_device_id is None


def test_b17_8_a_virtual_parent_gives_the_via_link():
    parent = _virtual("p1", device_id="parent_dev")
    child = _virtual("c1", parent_asset_id="p1")
    store = _Store(assets=[parent, child])
    registry = _registry(_VirtualDevice("dev1", name="Asset c1"))

    _reconcile(registry, store, child)

    assert registry.created == [{"via_device_id": "parent_dev"}]
    assert registry.device.via_device_id == "parent_dev"


# ── B17-9 ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("area_id", "device_area", "pushed"),
    [
        ("garage", None, True),
        (None, "garage", False),
        ("kitchen", "garage", False),
        ("garage", "garage", False),
        (None, None, False),
    ],
)
def test_b17_9_the_first_reconcile_fills_only_an_empty_device(
    area_id, device_area, pushed
):
    hass = types.SimpleNamespace(data={})
    assert devices._area_to_push(hass, "a1", area_id, device_area) is pushed


def test_b17_9_an_area_set_on_the_device_page_stays():
    hass = types.SimpleNamespace(data={})
    assert devices._area_to_push(hass, "a1", None, None) is False
    # The user sets "garage" on the device page. An unrelated edit reconciles.
    assert devices._area_to_push(hass, "a1", None, "garage") is False


@pytest.mark.parametrize("new_area", ["kitchen", None])
def test_b17_9_a_panel_change_of_the_area_is_pushed(new_area):
    hass = types.SimpleNamespace(data={})
    assert devices._area_to_push(hass, "a1", "garage", "garage") is False
    assert devices._area_to_push(hass, "a1", new_area, "garage") is True
    # The next reconcile has nothing new to push.
    assert devices._area_to_push(hass, "a1", new_area, new_area) is False


def test_b17_9_each_appliance_has_its_own_record():
    hass = types.SimpleNamespace(data={})
    devices._area_to_push(hass, "a1", "garage", "garage")
    assert devices._area_to_push(hass, "a2", "kitchen", "garage") is False


def test_b17_9_the_reconcile_keeps_a_device_page_area():
    store = _Store(assets=[_virtual("a1")])
    registry = _registry(_VirtualDevice("dev1", name="Asset a1", area_id="garage"))
    asset = store.get_asset("a1")

    hass = _reconcile(registry, store, asset)
    _reconcile(registry, store, asset, hass)

    assert registry.device.area_id == "garage"
    assert all("area_id" not in update for update in registry.updates)

    asset["area_id"] = "kitchen"
    _reconcile(registry, store, asset, hass)
    assert registry.device.area_id == "kitchen"
