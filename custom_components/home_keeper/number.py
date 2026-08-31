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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import assets as asset_model
from .const import DOMAIN, MAX_INTERVAL
from .coordinator import HomeKeeperCoordinator

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
    for asset, part, device in rows:
        uid = f"{_UID_PREFIX}{asset['id']}{_UID_INFIX}{part['id']}{_UID_SUFFIX}"
        live_uids.add(uid)
        entities.append(
            HomeKeeperPartStockNumber(coordinator, asset["id"], part, device)
        )

    # Prune number entities whose part (or stock tracking) is gone.
    reg = er.async_get(hass)
    for entity_entry in reg.entities.get_entries_for_config_entry_id(entry.entry_id):
        uid = entity_entry.unique_id or ""
        if (
            entity_entry.domain == "number"
            and uid.startswith(_UID_PREFIX)
            and uid.endswith(_UID_SUFFIX)
            and _UID_INFIX in uid
            and uid not in live_uids
        ):
            reg.async_remove(entity_entry.entity_id)

    async_add_entities(entities)


class HomeKeeperPartStockNumber(CoordinatorEntity[HomeKeeperCoordinator], NumberEntity):
    """On-hand spare count for one appliance part, editable on the device page."""

    _attr_has_entity_name = True
    _attr_translation_key = "part_spares"
    _attr_icon = _STOCK_ICON
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = float(MAX_INTERVAL)
    # Stock is decimal (a part can be measured in millilitres), but a part counted in
    # whole spares should still refuse "2.5 filters" in the UI — so the step follows
    # the part, see ``native_step``.
    _FRACTIONAL_STEP = 0.001

    def __init__(
        self,
        coordinator: HomeKeeperCoordinator,
        asset_id: str,
        part: dict[str, Any],
        device: dr.DeviceEntry,
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
        # Linked, not owned: the appliance device belongs to whoever created it.
        self.device_entry = device

    def _part(self) -> dict[str, Any] | None:
        asset = self.coordinator.store.get_asset(self._asset_id) or {}
        return asset_model.find_part(asset, self._part_id)

    @property
    def native_value(self) -> float | None:
        part = self._part()
        if part is None:
            return None
        stock = part.get("stock")
        return float(stock) if stock is not None else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """The part's own unit (``ml``, ``m``…), or none for plain whole spares."""
        return asset_model.part_stock_unit(self._part() or {}) or None

    @property
    def native_step(self) -> float:
        """A whole step for a part counted in spares, a fine one for a measured part.

        A part only deals in fractions once the user says so — by giving it a unit, a
        fractional stock/threshold, or a fractional per-completion amount. Until then
        the box keeps rejecting "2.5 filters" the way it always did.
        """
        part = self._part() or {}
        if asset_model.part_stock_unit(part):
            return self._FRACTIONAL_STEP
        quantities = (
            part.get("stock"),
            part.get("reorder_at"),
            part.get("consume_quantity"),
            part.get("restock_quantity"),
        )
        if any(q is not None and float(q) != int(float(q)) for q in quantities):
            return self._FRACTIONAL_STEP
        return 1

    async def async_set_native_value(self, value: float) -> None:
        """Set the on-hand quantity by adjusting toward *value* (fires stock events)."""
        part = self._part()
        if part is None:
            # The part (or its appliance) was removed between render and submit — the
            # entity will be pruned on the next reload, so there's nothing to adjust
            # (and adjust_part_stock would raise an unlocalized KeyError).
            return
        current = float(part.get("stock") or 0)
        # Snap to the part's own step so a raw service call can't push a whole-spare
        # part off its integers, while a measured part keeps its decimals.
        step = self.native_step
        delta = round(round(value / step) * step - current, 3)
        if delta:
            await self.coordinator.store.adjust_part_stock(
                self._asset_id, self._part_id, delta
            )
        # A crossing may create/remove an auto-buy task; settle it (reloads only if a
        # buy task's device entities changed, else refreshes).
        await self.coordinator.async_settle_buy_tasks()
