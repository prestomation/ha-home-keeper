"""Per-part spare-stock ``number`` entities for Home Keeper appliances.

A virtual appliance's stock-tracked spare parts (``assets.part_tracks_stock``) each get
an editable ``number`` on the appliance's device page showing the on-hand count.
Changing it delegates to ``store.adjust_part_stock`` — the same path the service /
wear-part completion use — so the edge-triggered low/out/restocked stock events still
fire. Owned (virtual) appliances only: we don't add stock controls onto a foreign
device a task happens to be attached to.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import assets as asset_model
from .const import DOMAIN, MAX_INTERVAL
from .coordinator import HomeKeeperCoordinator
from .entity import async_prune_platform_entities

_STOCK_ICON = "mdi:package-variant"
# unique-id shape: ``{DOMAIN}_asset_<asset_id>_part_<part_id>_stock``.
_UID_PREFIX = f"{DOMAIN}_asset_"
_UID_INFIX = "_part_"
_UID_SUFFIX = "_stock"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a spare-stock number for each stock-tracked part on a virtual asset."""
    coordinator: HomeKeeperCoordinator = entry.runtime_data

    rows = coordinator.virtual_asset_parts(asset_model.part_tracks_stock)
    entities: list[NumberEntity] = []
    live_uids: set[str] = set()
    for asset, part, device_info in rows:
        uid = f"{_UID_PREFIX}{asset['id']}{_UID_INFIX}{part['id']}{_UID_SUFFIX}"
        live_uids.add(uid)
        entities.append(
            HomeKeeperPartStockNumber(coordinator, asset["id"], part, device_info)
        )

    # Prune number entities whose part (or stock tracking) is gone.
    def _is_stale(uid: str) -> bool:
        return (
            uid.startswith(_UID_PREFIX)
            and uid.endswith(_UID_SUFFIX)
            and _UID_INFIX in uid
            and uid not in live_uids
        )

    async_prune_platform_entities(hass, entry, "number", _is_stale)

    async_add_entities(entities)


class HomeKeeperPartStockNumber(CoordinatorEntity[HomeKeeperCoordinator], NumberEntity):
    """On-hand spare count for one appliance part, editable on the device page."""

    _attr_has_entity_name = True
    _attr_translation_key = "part_spares"
    _attr_icon = _STOCK_ICON
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = float(MAX_INTERVAL)
    _attr_native_step = 1

    def __init__(
        self,
        coordinator: HomeKeeperCoordinator,
        asset_id: str,
        part: dict[str, Any],
        device_info: DeviceInfo | None,
    ) -> None:
        super().__init__(coordinator)
        self._asset_id = asset_id
        self._part_id = part["id"]
        # Part names are free-form, so the translated name carries the name as a
        # placeholder ("Anode rod spares") rather than localizing the part itself.
        self._attr_translation_placeholders = {"part": part.get("name") or ""}
        self._attr_unique_id = (
            f"{_UID_PREFIX}{asset_id}{_UID_INFIX}{part['id']}{_UID_SUFFIX}"
        )
        self._attr_device_info = device_info

    def _part(self) -> dict[str, Any] | None:
        return asset_model.find_part(
            self.coordinator.store.get_asset(self._asset_id), self._part_id
        )

    @property
    def native_value(self) -> float | None:
        part = self._part()
        if part is None:
            return None
        stock = part.get("stock")
        return float(stock) if stock is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the on-hand count by adjusting toward *value* (fires stock events)."""
        part = self._part()
        if part is None:
            # The part (or its appliance) was removed between render and submit — the
            # entity will be pruned on the next reload, so there's nothing to adjust
            # (and adjust_part_stock would raise an unlocalized KeyError).
            return
        current = int(part.get("stock") or 0)
        # round() (not int()) so a raw service call with a fractional value snaps to the
        # nearest whole spare rather than truncating toward zero.
        delta = round(value) - current
        if delta:
            await self.coordinator.store.adjust_part_stock(
                self._asset_id, self._part_id, delta
            )
        await self.coordinator.async_request_refresh()
