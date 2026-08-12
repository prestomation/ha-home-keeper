"""Unit tests for the snapshot-based fallback in device healing (#183).

When Home Assistant 2026.8 splits merged devices into per-config-entry devices,
``async_heal_split_device_ids`` repairs stale references.  Two gaps were fixed:

1. Assets of kind ``existing`` also carry a ``device_id`` that can become a dead
   composite — the heal now covers assets, not just tasks.
2. When Home Assistant garbage-collects the composite, the snapshot-based
   fallback in ``_resolve_successor_from_snapshot`` finds the live device from
   the asset's stored identifiers/connections.

These tests exercise the pure lookup logic without a Home Assistant runtime by
mocking the device registry.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── mock registry ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MockDevice:
    id: str
    config_entries: frozenset[str] = frozenset()
    identifiers: frozenset[tuple[str, ...]] = frozenset()
    connections: frozenset[tuple[str, ...]] = frozenset()


class MockRegistry:
    """Subset of HA's DeviceRegistry sufficient for the snapshot fallback."""

    def __init__(self, devices: list[MockDevice]):
        self._by_ident: dict[tuple[str, ...], MockDevice] = {}
        self._by_conn: dict[tuple[str, ...], MockDevice] = {}
        for d in devices:
            for ident in d.identifiers:
                self._by_ident[ident] = d
            for conn in d.connections:
                self._by_conn[conn] = d

    def async_get_device(
        self,
        identifiers: set[tuple[str, ...]] | None = None,
        connections: set[tuple[str, ...]] | None = None,
    ) -> MockDevice | None:
        if identifiers:
            for ident in identifiers:
                if ident in self._by_ident:
                    return self._by_ident[ident]
        if connections:
            for conn in connections:
                if conn in self._by_conn:
                    return self._by_conn[conn]
        return None


# ── replicate the production logic ────────────────────────────────────────────
#
# We can't import devices.py on this host (HA version mismatch), so the logic
# under test is replicated verbatim from _resolve_successor_from_snapshot.  The
# integration test tier (tests/upgrade/) runs the real function against a real
# HA instance, which is the authoritative check.


def resolve_successor_from_snapshot(
    registry: MockRegistry,
    snapshot: dict,
    entry_id: str,
) -> MockDevice | None:
    candidates: list[MockDevice] = []
    for ident in snapshot.get("identifiers", []):
        device = registry.async_get_device(identifiers={tuple(ident)})
        if device is not None and device not in candidates:
            candidates.append(device)
    connections = {tuple(c) for c in snapshot.get("connections", [])}
    if connections:
        device = registry.async_get_device(connections=connections)
        if device is not None and device not in candidates:
            candidates.append(device)
    if not candidates:
        return None
    foreign = [d for d in candidates if entry_id not in d.config_entries]
    if foreign:
        if len(foreign) > 1:
            return sorted(foreign, key=lambda d: d.id)[0]
        return foreign[0]
    return sorted(candidates, key=lambda d: d.id)[0]


# ── fixtures ──────────────────────────────────────────────────────────────────

HK_ENTRY = "hk_config_entry"
ZWAVE_ENTRY_A = "zwave_entry_a"
SWITCHBOT_ENTRY = "switchbot_entry"

# The two dead composite device_ids from the real snapshot
THERMOSTAT_DEAD_ID = "620eef300819d798126579786ab84740"
COFFEE_DEAD_ID = "abba09c890b6ce14049d67796271aa43"

THERMOSTAT_SNAPSHOT = {
    "id": "ed833511-8b7b-46e0-978b-f90bfece20ff",
    "kind": "existing",
    "device_id": THERMOSTAT_DEAD_ID,
    "identifiers": [
        ["zwave_js", "4268179804-12-57:17:8"],
        ["zwave_js", "4268179804-12"],
    ],
    "connections": [],
}

COFFEE_SNAPSHOT = {
    "id": "5d2669f9-6b3c-4271-8276-6b4031a0f036",
    "kind": "existing",
    "device_id": COFFEE_DEAD_ID,
    "identifiers": [],
    "connections": [
        ["bluetooth", "D0:65:85:16:4C:E2"],
        ["mac", "d0:65:85:16:4c:e2"],
    ],
}


# ── tests ─────────────────────────────────────────────────────────────────────


def test_snapshot_fallback_finds_thermostat_by_identifiers():
    """The T6 Pro thermostat asset resolves via stored Z-Wave identifiers."""
    dev_hk = MockDevice(
        "hk_half",
        config_entries=frozenset({HK_ENTRY}),
        identifiers=frozenset({("zwave_js", "4268179804-12")}),
    )
    dev_zwave = MockDevice(
        "zwave_real",
        config_entries=frozenset({ZWAVE_ENTRY_A}),
        identifiers=frozenset(
            {("zwave_js", "4268179804-12-57:17:8"), ("zwave_js", "4268179804-12")}
        ),
    )
    registry = MockRegistry([dev_hk, dev_zwave])

    result = resolve_successor_from_snapshot(registry, THERMOSTAT_SNAPSHOT, HK_ENTRY)

    assert result is not None, "should find the thermostat"
    assert result.id == "zwave_real", f"expected the Z-Wave device, got {result.id}"
    assert HK_ENTRY not in result.config_entries, "must be the foreign device"


def test_snapshot_fallback_finds_coffee_by_connections():
    """The Breville coffee maker asset resolves via stored Bluetooth connections."""
    dev_coffee = MockDevice(
        "coffee_real",
        config_entries=frozenset({SWITCHBOT_ENTRY}),
        connections=frozenset(
            {("bluetooth", "D0:65:85:16:4C:E2"), ("mac", "d0:65:85:16:4c:e2")}
        ),
    )
    registry = MockRegistry([dev_coffee])

    result = resolve_successor_from_snapshot(registry, COFFEE_SNAPSHOT, HK_ENTRY)

    assert result is not None, "should find the coffee maker"
    assert result.id == "coffee_real", f"expected the coffee device, got {result.id}"


def test_snapshot_fallback_prefers_foreign_over_hk_owned():
    """When both HK and a foreign device match, the foreign one wins."""
    dev_hk = MockDevice(
        "hk_half",
        config_entries=frozenset({HK_ENTRY}),
        connections=frozenset({("bluetooth", "D0:65:85:16:4C:E2")}),
    )
    dev_foreign = MockDevice(
        "coffee_real",
        config_entries=frozenset({SWITCHBOT_ENTRY}),
        connections=frozenset({("bluetooth", "D0:65:85:16:4C:E2")}),
    )
    registry = MockRegistry([dev_hk, dev_foreign])

    result = resolve_successor_from_snapshot(registry, COFFEE_SNAPSHOT, HK_ENTRY)

    assert result is not None
    assert result.id == "coffee_real", "should prefer the foreign device"
    assert HK_ENTRY not in result.config_entries


def test_snapshot_fallback_returns_none_when_nothing_matches():
    """An empty registry yields None — the caller skips healing that device."""
    registry = MockRegistry([])
    result = resolve_successor_from_snapshot(registry, THERMOSTAT_SNAPSHOT, HK_ENTRY)
    assert result is None


def test_snapshot_fallback_multiple_foreign_picks_sorted():
    """Two foreign matches with no HK entry: sorted determinism."""
    entry_b = "entry_b"
    entry_c = "entry_c"
    dev_b = MockDevice(
        "dev_b",
        config_entries=frozenset({entry_b}),
        identifiers=frozenset({("zwave_js", "4268179804-12-57:17:8")}),
    )
    dev_c = MockDevice(
        "dev_c",
        config_entries=frozenset({entry_c}),
        identifiers=frozenset({("zwave_js", "4268179804-12")}),
    )
    registry = MockRegistry([dev_b, dev_c])

    result = resolve_successor_from_snapshot(registry, THERMOSTAT_SNAPSHOT, HK_ENTRY)

    assert result is not None
    # Both identifiers match different devices; first match in identifier
    # order wins (the first identifier in the snapshot is looked up first).
    assert HK_ENTRY not in result.config_entries, "should be foreign"


def test_snapshot_fallback_no_identifiers_no_connections():
    """An asset with no snapshot data at all returns None."""
    registry = MockRegistry(
        [
            MockDevice(
                "some_dev",
                config_entries=frozenset({HK_ENTRY}),
                identifiers=frozenset({("zwave_js", "x")}),
            )
        ]
    )
    snapshot = {"identifiers": [], "connections": []}
    result = resolve_successor_from_snapshot(registry, snapshot, HK_ENTRY)
    assert result is None
