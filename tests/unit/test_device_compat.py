"""Unit tests for the cross-version device-registry lookups (#253).

Home Assistant 2026.9 changed two shapes Home Keeper reads from the device registry:
``DeviceRegistry.devices`` stopped being a mapping keyed by device id, and
``DeviceRegistry.async_get`` started answering with child devices, which carry no
``connections``. Both shapes have to keep working while a released Home Keeper spans
the two Home Assistant versions, and only one of them can be exercised at a time
against a real container — so the shapes themselves are pinned here.

The fakes below stand in for the two eras deliberately: the mapping fake iterates like
the pre-2026.9 ``ActiveDeviceRegistryItems`` (a ``UserDict``, so iteration yields
**ids**), and the collection fake iterates like the 2026.9 view (which yields
**entries**). A helper that iterated the wrong one would silently return device ids
where entries belong, which is exactly the failure this guards.

``tests/unit/test_device_heal.py`` covers the repair that consumes ``all_devices``, and
the real ``DeviceRegistry`` contract is exercised against a genuine Home Assistant by
``tests/integration`` and ``tests/upgrade``.
"""

from dataclasses import dataclass, field

import hk_device_compat as device_compat


@dataclass(frozen=True)
class FakeDevice:
    """A main device: has ``connections``, has no parent."""

    id: str
    connections: set = field(default_factory=set)


@dataclass(frozen=True)
class FakeChildDevice:
    """A 2026.9 child device: has a parent, and no ``connections`` attribute at all."""

    id: str
    parent_device_id: str


class MappingRegistry:
    """Pre-2026.9: ``devices`` is a mapping, so iterating it yields device ids."""

    def __init__(self, devices):
        self.devices = {d.id: d for d in devices}

    def async_get(self, device_id):
        return self.devices.get(device_id)


class _EntryCollection:
    """The 2026.9 ``devices`` view: a collection of entries, and not a mapping."""

    def __init__(self, devices):
        self._devices = list(devices)

    def __iter__(self):
        return iter(self._devices)

    def __len__(self):
        return len(self._devices)


class CollectionRegistry:
    """2026.9 and later: ``devices`` is a collection, so iterating yields entries."""

    def __init__(self, devices):
        self._by_id = {d.id: d for d in devices}
        self.devices = _EntryCollection(devices)

    def async_get(self, device_id):
        return self._by_id.get(device_id)


DEV_A = FakeDevice("a", {("mac", "aa:bb:cc:dd:ee:ff")})
DEV_B = FakeDevice("b")
CHILD = FakeChildDevice("c", parent_device_id="a")


# ── all_devices: both registry shapes yield entries ──────────────────────────


def test_a_mapping_registry_yields_entries_not_ids():
    assert device_compat.all_devices(MappingRegistry([DEV_A, DEV_B])) == [DEV_A, DEV_B]


def test_a_collection_registry_yields_its_entries():
    assert device_compat.all_devices(CollectionRegistry([DEV_A, DEV_B])) == [
        DEV_A,
        DEV_B,
    ]


def test_an_empty_registry_yields_nothing_in_either_shape():
    assert device_compat.all_devices(MappingRegistry([])) == []
    assert device_compat.all_devices(CollectionRegistry([])) == []


def test_all_devices_returns_a_list_the_caller_can_hold():
    # The registry mutates its containers in place, so callers get a snapshot: a view
    # would change under a caller that removes devices while iterating.
    registry = MappingRegistry([DEV_A, DEV_B])
    devices = device_compat.all_devices(registry)
    registry.devices.clear()
    assert devices == [DEV_A, DEV_B]


# ── resolve_device ───────────────────────────────────────────────────────────


def test_resolve_device_returns_the_registered_device():
    assert device_compat.resolve_device(MappingRegistry([DEV_A]), "a") is DEV_A


def test_resolve_device_returns_none_for_an_unknown_id():
    assert device_compat.resolve_device(MappingRegistry([DEV_A]), "nope") is None


def test_resolve_device_resolves_a_child_device():
    # A child device is a legitimate attach target: HA links entities to either kind.
    assert device_compat.resolve_device(CollectionRegistry([CHILD]), "c") is CHILD


def test_resolve_device_answers_none_for_an_absent_reference_without_asking():
    # The empty-id guard is the caller's `if device_id` folded in, so it must not
    # reach the registry: `async_get(None)` is not a lookup the registry accepts.
    class Exploding:
        def async_get(self, device_id):
            raise AssertionError(f"registry consulted for {device_id!r}")

    assert device_compat.resolve_device(Exploding(), None) is None
    assert device_compat.resolve_device(Exploding(), "") is None


# ── device_connections ───────────────────────────────────────────────────────


def test_a_main_device_reports_its_connections():
    assert device_compat.device_connections(DEV_A) == {("mac", "aa:bb:cc:dd:ee:ff")}


def test_a_main_device_without_connections_reports_an_empty_set():
    assert device_compat.device_connections(DEV_B) == set()


def test_a_child_device_reports_no_connections_instead_of_raising():
    # Asking a real ChildDeviceEntry for `connections` goes through a compatibility
    # shim that logs a deprecation and stops answering in HA 2027.9; the fake has no
    # such shim, so reading the attribute here would raise outright.
    assert device_compat.device_connections(CHILD) == set()
