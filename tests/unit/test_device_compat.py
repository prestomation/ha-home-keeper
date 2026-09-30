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


# ── RegistryDeviceIds (B04-1) ────────────────────────────────────────────────


def test_b04_1_device_ids_answer_on_a_mapping_registry():
    # Before 2026.9 iterating ``devices`` yields ids, so reading ``.id`` off each one
    # raised AttributeError and every import failed.
    ids = device_compat.RegistryDeviceIds(MappingRegistry([DEV_A, DEV_B]))
    assert "a" in ids
    assert "b" in ids
    assert "nope" not in ids


def test_b04_1_device_ids_include_a_child_that_devices_does_not_list():
    # From 2026.9 ``devices`` lists main devices only. ``async_get`` answers both.
    registry = CollectionRegistry([DEV_A])
    registry._by_id[CHILD.id] = CHILD
    ids = device_compat.RegistryDeviceIds(registry)
    assert "a" in ids
    assert "c" in ids
    assert "b" not in ids


def test_b04_1_device_ids_answer_no_for_an_empty_or_odd_value():
    class Exploding:
        def async_get(self, device_id):
            raise AssertionError(f"registry consulted for {device_id!r}")

    ids = device_compat.RegistryDeviceIds(Exploding())
    assert "" not in ids
    assert None not in ids
    assert 7 not in ids


# ── X13-1: the calls HA 2026.9 deprecates and 2027.8 removes ─────────────────


@dataclass(frozen=True)
class LegacyEntryDevice:
    """Before 2026.8: a device lists its config entries, and has no single owner."""

    id: str
    config_entries: frozenset = frozenset()


@dataclass(frozen=True)
class OwnedDevice:
    """2026.8 and later: a device has one config entry in ``config_entry_id``."""

    id: str
    config_entry_id: str | None = None
    config_entries: frozenset = frozenset({"shim-value-that-must-not-be-read"})


def test_x13_1_config_entries_reads_config_entry_id_when_there_is_one():
    assert device_compat.device_config_entries(OwnedDevice("d", "hk")) == {"hk"}


def test_x13_1_config_entries_falls_back_to_the_old_set():
    device = LegacyEntryDevice("d", frozenset({"hk", "zwave"}))
    assert device_compat.device_config_entries(device) == {"hk", "zwave"}
    # A composite with no owner reads the old set too.
    owned_by_none = OwnedDevice("d", None, frozenset({"x"}))
    assert device_compat.device_config_entries(owned_by_none) == {"x"}
    assert device_compat.device_config_entries(DEV_B) == set()


class LookupRegistry:
    """A registry with the lookups of one era, and a log of the calls it got."""

    def __init__(self, devices, *, modern):
        self._devices = list(devices)
        self.calls = []
        if modern:
            self.async_get_devices = self._get_devices
        else:
            self.async_get_device = self._get_device

    def _hits(self, identifiers, connections):
        return [
            d
            for d in self._devices
            if (identifiers and d.identifiers & identifiers)
            or (connections and d.connections & connections)
        ]

    def _get_devices(self, *, identifiers=None, connections=None):
        self.calls.append(("async_get_devices", identifiers, connections))
        return self._hits(identifiers, connections)

    def _get_device(self, identifiers=None, connections=None):
        self.calls.append(("async_get_device", identifiers, connections))
        hits = self._hits(identifiers, connections)
        return hits[0] if hits else None


@dataclass(frozen=True)
class IdDevice:
    id: str
    identifiers: frozenset = frozenset()
    connections: frozenset = frozenset()


ZW1 = IdDevice("zw1", identifiers=frozenset({("zwave_js", "12")}))
ZW2 = IdDevice("zw2", identifiers=frozenset({("zwave_js", "12")}))
BT = IdDevice("bt", connections=frozenset({("bluetooth", "D0")}))


def test_x13_1_find_devices_uses_async_get_devices_when_there_is_one():
    registry = LookupRegistry([ZW1, ZW2, BT], modern=True)
    found = device_compat.find_devices(registry, identifiers={("zwave_js", "12")})
    assert found == [ZW1, ZW2]
    assert registry.calls == [("async_get_devices", {("zwave_js", "12")}, None)]
    assert device_compat.find_devices(registry, connections={("bluetooth", "D0")}) == [
        BT
    ]
    assert registry.calls[-1] == ("async_get_devices", None, {("bluetooth", "D0")})


def test_x13_1_find_devices_falls_back_to_async_get_device():
    registry = LookupRegistry([ZW1, ZW2], modern=False)
    found = device_compat.find_devices(registry, identifiers={("zwave_js", "12")})
    assert found == [ZW1]
    assert registry.calls == [("async_get_device", {("zwave_js", "12")}, None)]
    assert device_compat.find_devices(registry, identifiers={("zwave_js", "9")}) == []


class CreateRegistry:
    """``async_get_or_create`` and ``async_get`` in one of two signatures."""

    def __init__(self, devices, *, via_device_id):
        self._by_id = {d.id: d for d in devices}
        if via_device_id:
            self.async_get_or_create = self._create_new
        else:
            self.async_get_or_create = self._create_old

    def async_get(self, device_id):
        return self._by_id.get(device_id)

    def _create_new(self, *, config_entry_id, via_device_id=None, **kwargs):
        return None

    def _create_old(self, *, config_entry_id, via_device=None, **kwargs):
        return None


PARENT_IDENT = ("home_keeper", "asset_parent")


def test_x13_1_via_device_id_when_the_registry_takes_it():
    registry = CreateRegistry([DEV_A], via_device_id=True)
    assert device_compat.via_device_kwargs(registry, PARENT_IDENT, "a") == {
        "via_device_id": "a"
    }


def test_x13_1_no_via_device_id_for_a_parent_that_is_not_registered():
    # An unknown via_device_id makes Home Assistant refuse the call, and via_device
    # together with via_device_id is refused too, so nothing is given.
    registry = CreateRegistry([DEV_A], via_device_id=True)
    assert device_compat.via_device_kwargs(registry, PARENT_IDENT, "nope") == {}
    assert device_compat.via_device_kwargs(registry, PARENT_IDENT, None) == {}


def test_x13_1_via_device_on_an_older_registry():
    registry = CreateRegistry([DEV_A], via_device_id=False)
    assert device_compat.via_device_kwargs(registry, PARENT_IDENT, "a") == {
        "via_device": PARENT_IDENT
    }


def test_x13_1_no_parent_gives_no_link():
    for via_device_id in (True, False):
        registry = CreateRegistry([DEV_A], via_device_id=via_device_id)
        assert device_compat.via_device_kwargs(registry, None, "a") == {}


def test_x13_1_supports_kwarg_reads_the_signature():
    def func(*, named=None, **kwargs):
        return None

    assert device_compat.supports_kwarg(func, "named") is True
    # A name taken only through **kwargs is not supported.
    assert device_compat.supports_kwarg(func, "via_device") is False


class RemoveRegistry:
    def __init__(self):
        self.removed = []
        self.updated = []

    def async_remove_device(self, device_id):
        self.removed.append(device_id)

    def async_update_device(self, device_id, **kwargs):
        self.updated.append((device_id, kwargs))


def test_x13_1_remove_config_entry_removes_a_device_the_entry_owns():
    registry = RemoveRegistry()
    device_compat.remove_config_entry(registry, OwnedDevice("d", "hk"), "hk")
    assert (registry.removed, registry.updated) == (["d"], [])


def test_x13_1_remove_config_entry_leaves_a_device_of_another_entry():
    registry = RemoveRegistry()
    device_compat.remove_config_entry(registry, OwnedDevice("d", "zwave"), "hk")
    assert (registry.removed, registry.updated) == ([], [])


def test_x13_1_remove_config_entry_on_an_older_registry():
    registry = RemoveRegistry()
    device = LegacyEntryDevice("d", frozenset({"hk", "zwave"}))
    device_compat.remove_config_entry(registry, device, "hk")
    assert registry.removed == []
    assert registry.updated == [("d", {"remove_config_entry_id": "hk"})]


def test_x13_1_supports_kwarg_is_false_without_a_signature():
    assert device_compat.supports_kwarg(42, "via_device_id") is False
