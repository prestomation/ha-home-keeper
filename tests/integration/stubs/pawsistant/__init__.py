"""Test-only stub of a Home Keeper companion (push self-registration).

Lives under ``tests/integration/stubs/`` and is bind-mounted into the e2e Home
Assistant container's ``custom_components`` — it is **not** part of the shipped
integration. On setup it self-registers with Home Keeper through the public
``home_keeper.register_companion`` service (the same push path a real companion
uses), so the panel's Settings → Companions section renders a real *connected*
companion in e2e and screenshot runs. Pawsistant is deliberately not in Home
Keeper's catalog, so it exercises the self-registration (push) path; the Battery
Notes stub exercises the catalog-detection (pull) path.

It also joins the import and export (docs/INTEGRATING.md §11): it registers the
``import_export`` capability and admin-only ``pawsistant.export_data`` and
``pawsistant.import_data`` services. They return fixed example data, so the panel's
Import and export card shows a real companion row and a companion preview section.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import Unauthorized

DOMAIN = "pawsistant"

_EXPORT_DATA: dict[str, Any] = {
    "dogs": [{"name": "Biscuit", "breed": "Beagle"}],
    "events": [
        {"dog": "Biscuit", "type": "walk", "at": "2026-10-01T07:30:00+00:00"},
        {"dog": "Biscuit", "type": "meal", "at": "2026-10-01T08:00:00+00:00"},
    ],
    "care_schedules": [{"dog": "Biscuit", "name": "Flea treatment", "every_days": 30}],
}


async def _require_admin(hass: HomeAssistant, call: ServiceCall) -> None:
    """Refuse a caller that is not an admin, as a real companion must."""
    user_id = call.context.user_id
    if user_id is None:
        return
    user = await hass.auth.async_get_user(user_id)
    if user is None or not user.is_admin:
        raise Unauthorized(context=call.context)


def _count(document: Any, key: str) -> int:
    data = document.get("data", document) if isinstance(document, dict) else {}
    value = data.get(key) if isinstance(data, dict) else None
    return len(value) if isinstance(value, list) else 0


def _register_services(hass: HomeAssistant) -> None:
    async def export_data(call: ServiceCall) -> ServiceResponse:
        await _require_admin(hass, call)
        return {"format": 1, "version": "0.0.1", "data": _EXPORT_DATA, "skipped": {}}

    async def import_data(call: ServiceCall) -> ServiceResponse:
        await _require_admin(hass, call)
        document = call.data.get("document")
        problems = []
        if _count(document, "care_schedules"):
            problems.append(
                {
                    "level": "warning",
                    "path": "care_schedules",
                    "message": "Care tasks are made again after the import.",
                }
            )
        return {
            "ok": True,
            "dry_run": bool(call.data.get("dry_run")),
            "counts": {
                "dogs": {
                    "created": _count(document, "dogs"),
                    "updated": 0,
                    "unchanged": 0,
                },
                "events": {
                    "created": _count(document, "events"),
                    "updated": 0,
                    "unchanged": 0,
                },
            },
            "records": [],
            "problems": problems,
        }

    hass.services.async_register(
        DOMAIN, "export_data", export_data, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register(
        DOMAIN, "import_data", import_data, supports_response=SupportsResponse.ONLY
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register this stub with Home Keeper as a connected companion."""
    _register_services(hass)
    await hass.services.async_call(
        "home_keeper",
        "register_companion",
        {
            "domain": DOMAIN,
            "name": "Pawsistant",
            "icon": "mdi:paw",
            "description": (
                "Pet care tracker — logs walks, meals, meds and weight, and can "
                "schedule recurring pet-care chores as Home Keeper tasks."
            ),
            "config_entry_id": entry.entry_id,
            "docs_url": "https://github.com/prestomation/Pawsistant",
            "capabilities": ["care_schedules", "import_export"],
        },
        blocking=True,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Nothing to tear down — the in-memory registry is reconciled by Home Keeper."""
    return True
