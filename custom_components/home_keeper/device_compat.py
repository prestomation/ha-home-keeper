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
"""

from __future__ import annotations

from collections.abc import Mapping
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
