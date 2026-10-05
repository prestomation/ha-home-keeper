"""Device-registry lookups that work across the Home Assistant versions we support.

Home Assistant 2026.9 reshaped two parts of ``homeassistant.helpers.device_registry``
that Home Keeper leans on:

* **Child devices.** A device can now be registered as a *child* of another, and a
  child is its own class (``ChildDeviceEntry``) rather than a ``DeviceEntry``. Both
  derive from ``BaseDeviceEntry``, so a child still carries ``id``, ``identifiers``,
  ``name``, ``name_by_user``, ``area_id``, ``labels``, ``config_entry_id`` and
  ``disabled_by`` — every attribute Home Keeper reads off a device except one. What a
  child drops is the hardware description: ``connections``, ``manufacturer``,
  ``model``, ``model_id``, ``hw_version``, ``sw_version``, ``serial_number``,
  ``entry_type``, ``configuration_url`` and ``via_device_id``, which are the names
  ``ChildDeviceEntry.__getattr__`` answers through a deprecation shim until 2027.9
  removes it. ``DeviceRegistry.async_get`` answers with either kind, and
  ``Entity.device_entry`` accepts either, so a child device is a perfectly good thing
  to attach a task or an appliance to and Home Keeper keeps taking one.
* **``DeviceRegistry.devices``.** It used to be a mapping keyed by device id and is now
  a collection of entries, so iterating the old one yields ids and the new one yields
  entries. ``.values()`` — the one spelling that answers on both today — is deprecated
  from 2026.9 and gone in 2027.9.

Home Keeper still annotates registry devices as ``dr.DeviceEntry`` everywhere, because
``ChildDeviceEntry`` does not exist on the stable Home Assistant that ``lint.yml``
type-checks against: naming it would fail that gate, and there is no older name that
covers both kinds. So the annotation is a deliberate approximation, every lookup that
can now answer with a child comes through this module, and the one attribute a child
genuinely lacks gets an explicit answer here instead of an ``AttributeError`` (or, on
2026.9 exactly, a deprecation warning) somewhere further in.

Home Assistant imports are ``TYPE_CHECKING``-only, which keeps this module pure Python
and unit-testable in isolation — the ``recurrence.py``/``models.py`` contract. Keep it
that way: it means the two registry shapes can be exercised with plain fakes.

Home Assistant 2026.9 also deprecates four device-registry calls, and 2027.8 removes
them: ``async_get_device``, the ``via_device`` argument of ``async_get_or_create``,
the ``remove_config_entry_id`` argument of ``async_update_device``, and
``DeviceEntry.config_entries``. Each one has a replacement that older cores do not
have. The helpers below use the replacement when the registry has it, else the old
call. Keep every use of those four calls in this module.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.helpers import device_registry as dr


def resolve_device(
    registry: dr.DeviceRegistry, device_id: str | None
) -> dr.DeviceEntry | None:
    """Resolve *device_id* to a registry device, child devices included.

    Returns ``None`` for an empty *device_id*, so callers holding an optional
    reference (most of ours) need no guard of their own.

    Typed as ``DeviceEntry`` deliberately — see the module docstring. From Home
    Assistant 2026.9 this may really hand back a ``ChildDeviceEntry``, which offers
    every attribute Home Keeper reads off a device except ``connections``; that one
    goes through :func:`device_connections`.
    """
    if not device_id:
        return None
    # The lookup's declared type widens to a union in HA 2026.9 that we cannot name
    # (module docstring), so the approximation is applied here, once.
    device: Any = registry.async_get(device_id)
    return device


def all_devices(registry: dr.DeviceRegistry) -> list[dr.DeviceEntry]:
    """Every main device in the registry.

    ``DeviceRegistry.devices`` is a mapping keyed by device id before Home Assistant
    2026.9 and a collection of entries from 2026.9 on, so iterating it yields ids on
    one and entries on the other. Ask which shape we were handed rather than calling
    ``.values()``, which answers on both today but is deprecated from 2026.9.
    """
    devices: Any = registry.devices
    if isinstance(devices, Mapping):
        return list(devices.values())
    return list(devices)


def device_connections(device: dr.DeviceEntry) -> set[tuple[str, str]]:
    """*device*'s connections, or an empty set for a device that cannot have any.

    Only main devices have connections. A child device answers the attribute through a
    backwards-compatibility shim that logs a deprecation warning and stops answering in
    Home Assistant 2027.9, so key off ``parent_device_id`` — which only a child carries
    — rather than reading through the shim.
    """
    if getattr(device, "parent_device_id", None) is not None:
        return set()
    return device.connections


class RegistryDeviceIds:
    """The ids of every device on this install, main and child, for ``in`` only.

    ``device_id in RegistryDeviceIds(registry)`` asks the registry for that one id.
    Iterating ``DeviceRegistry.devices`` cannot give this answer: before Home
    Assistant 2026.9 it yields ids and not entries, and from 2026.9 it lists main
    devices only, so a child device would read as not on this install (B04-1).
    """

    def __init__(self, registry: dr.DeviceRegistry) -> None:
        self._registry = registry

    def __contains__(self, device_id: object) -> bool:
        return (
            isinstance(device_id, str)
            and resolve_device(self._registry, device_id) is not None
        )


def supports_kwarg(func: Callable[..., Any], name: str) -> bool:
    """Whether *func* declares a parameter called *name*.

    A ``**kwargs`` catch-all does not count: on Home Assistant 2026.9
    ``async_get_or_create`` takes the deprecated ``via_device`` through it.
    """
    try:
        return name in inspect.signature(func).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins without signatures
        # If we cannot confirm support, do not pass the argument.
        return False


def device_config_entries(device: dr.DeviceEntry) -> set[str]:
    """The config entries *device* belongs to.

    From Home Assistant 2026.8 a device belongs to one config entry, which it names
    in ``config_entry_id``. ``config_entries`` is then a deprecated shim, and 2027.8
    removes it. An older core has only ``config_entries``.
    """
    entry_id = getattr(device, "config_entry_id", None)
    if isinstance(entry_id, str):
        return {entry_id}
    return set(getattr(device, "config_entries", None) or ())


def find_devices(
    registry: dr.DeviceRegistry,
    *,
    identifiers: set[tuple[str, str]] | None = None,
    connections: set[tuple[str, str]] | None = None,
) -> list[dr.DeviceEntry]:
    """Every main device that has one of *identifiers* or *connections*.

    Home Assistant 2026.9 has ``async_get_devices``, which gives all the devices
    that match. ``async_get_device`` gives one device, and 2027.8 removes it, so it
    is used only on a core that has no ``async_get_devices``.
    """
    lookup: Any = getattr(registry, "async_get_devices", None)
    if lookup is not None:
        return list(
            lookup(identifiers=identifiers or None, connections=connections or None)
        )
    device: Any = registry.async_get_device(
        identifiers=identifiers, connections=connections
    )
    return [] if device is None else [device]


def via_device_kwargs(
    registry: dr.DeviceRegistry,
    parent_identifier: tuple[str, str] | None,
    parent_device_id: str | None,
) -> dict[str, Any]:
    """The ``async_get_or_create`` argument that links a device to its parent.

    Home Assistant 2026.9 takes the parent's device id as ``via_device_id``, and
    2027.8 removes ``via_device`` (the parent's identifier). The two must never go
    together: Home Assistant refuses the call. An unknown ``via_device_id`` also
    stops the call, so it is given only when the parent device exists. The next
    ``async_update_device`` sets the link when the parent comes later.
    """
    if parent_identifier is None:
        return {}
    if supports_kwarg(registry.async_get_or_create, "via_device_id"):
        if resolve_device(registry, parent_device_id) is None:
            return {}
        return {"via_device_id": parent_device_id}
    return {"via_device": parent_identifier}


def remove_config_entry(
    registry: dr.DeviceRegistry, device: dr.DeviceEntry, entry_id: str
) -> None:
    """Take config entry *entry_id* off *device*.

    Before Home Assistant 2026.8 a device can belong to several config entries, and
    ``remove_config_entry_id`` removes one of them (the device goes when none is
    left). From 2026.8 a device belongs to one config entry, so the device of
    *entry_id* is removed, and a device of another config entry is left alone.
    """
    owner = getattr(device, "config_entry_id", None)
    if isinstance(owner, str):
        if owner == entry_id:
            registry.async_remove_device(device.id)
        return
    registry.async_update_device(device.id, remove_config_entry_id=entry_id)
