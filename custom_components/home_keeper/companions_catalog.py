"""Curated catalog of integrations Home Keeper knows how to pair with.

Home Keeper has two ways to learn about a *companion* — another integration that
works with it:

1. **Self-registration (push).** A Home-Keeper-aware integration (e.g. Pawsistant,
   or the Battery Notes *glue*) announces itself at setup via the
   ``home_keeper.register_companion`` service. Home Keeper knows nothing about it
   ahead of time. See ``companions.py`` and docs/INTEGRATING.md.

2. **Catalog detection (pull).** For a handful of *popular* integrations that are
   not themselves Home-Keeper-aware, Home Keeper ships this small curated catalog so
   it can notice the upstream is installed and *suggest* the glue that connects them.
   The classic case: the user has **Battery Notes** installed but not the
   ``home_keeper_battery_notes`` glue — Home Keeper points them at it.

This file is intentionally tiny and pure (no Home Assistant imports). Each entry maps
an *upstream* integration domain the user already has to the *glue* integration that
bridges it into Home Keeper. Detection (is the upstream installed? is the glue
present?) lives in ``companions.py``; the *suggestion copy* lives here so it stays in
one curated place.
"""

from __future__ import annotations

from typing import Any, TypedDict


class CatalogEntry(TypedDict):
    """A detectable upstream integration and the glue that bridges it to Home Keeper."""

    upstream_domain: str  # the integration the user already has (we detect this)
    glue_domain: str  # the integration that connects it to Home Keeper
    name: str  # display name shown in the suggestion (the upstream the user knows)
    icon: str  # mdi icon for the row
    description: str  # one line: what installing the glue gets the user
    install_url: str  # where to get the glue (HACS / GitHub)


# The curated set. Keep this short and high-signal — every entry is a popular
# integration whose pairing with Home Keeper we actively want users to discover.
CATALOG: list[CatalogEntry] = [
    {
        "upstream_domain": "battery_notes",
        "glue_domain": "home_keeper_battery_notes",
        "name": "Battery Notes",
        "icon": "mdi:battery-alert-variant-outline",
        "description": (
            "You have Battery Notes installed. Add the Home Keeper — Battery "
            "Notes bridge to turn low-battery alerts into scheduled “replace "
            "battery” tasks, kept in sync both ways."
        ),
        "install_url": "https://github.com/prestomation/ha-home-keeper-battery-notes",
    },
]


def catalog_by_glue() -> dict[str, CatalogEntry]:
    """Index the catalog by glue domain (so a registered glue can resolve its entry)."""
    return {entry["glue_domain"]: entry for entry in CATALOG}


def as_public(entry: CatalogEntry) -> dict[str, Any]:
    """Project a catalog entry into the public companion shape (a *suggested* row)."""
    return {
        "domain": entry["glue_domain"],
        "name": entry["name"],
        "icon": entry["icon"],
        "description": entry["description"],
        "install_url": entry["install_url"],
        "upstream_domain": entry["upstream_domain"],
    }


# Status values on a public companion row.
STATUS_CONNECTED = "connected"  # self-registered, or a known glue that's installed
STATUS_SUGGESTED = "suggested"  # an upstream is installed but its glue isn't


def _connected_from_registered(domain: str, desc: dict[str, Any]) -> dict[str, Any]:
    """A *connected* row from a self-registered companion descriptor."""
    return {
        "domain": domain,
        "name": desc.get("name") or domain,
        "icon": desc.get("icon") or "mdi:puzzle",
        "description": desc.get("description") or "",
        "status": STATUS_CONNECTED,
        # The panel "Configure" button deep-links to this integration's own
        # options page; ownership of the settings stays with the companion.
        "configure_domain": domain,
        "config_entry_id": desc.get("config_entry_id"),
        "docs_url": desc.get("docs_url"),
        "capabilities": list(desc.get("capabilities") or []),
        "source": "registered",
    }


def _connected_from_catalog(entry: CatalogEntry) -> dict[str, Any]:
    """A *connected* row for a catalog glue that's installed but didn't self-register.

    Older glue builds may predate the registration handshake; if the glue domain has
    a config entry we still show it as connected (with a Configure deep-link) rather
    than nagging the user to install something they already have.
    """
    return {
        "domain": entry["glue_domain"],
        "name": entry["name"],
        "icon": entry["icon"],
        "description": "",
        "status": STATUS_CONNECTED,
        "configure_domain": entry["glue_domain"],
        "config_entry_id": None,
        "docs_url": None,
        "capabilities": [],
        "source": "catalog",
    }


def _suggested_from_catalog(entry: CatalogEntry) -> dict[str, Any]:
    """A *suggested* row: the upstream is installed but the glue isn't."""
    row = as_public(entry)
    row["status"] = STATUS_SUGGESTED
    return row


def build_companion_list(
    registered: dict[str, dict[str, Any]],
    installed_domains: set[str],
    *,
    dismissed: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Merge self-registered companions and catalog detection into public rows.

    Pure: takes plain data so it's unit-testable without Home Assistant.

    - ``registered`` maps a companion domain to its descriptor (self-registration).
    - ``installed_domains`` is the set of domains that currently have a config entry.
    - ``dismissed`` are catalog glue domains the user dismissed; their *suggested*
      rows are hidden (a connected row is always shown — dismissal only silences a
      suggestion, never hides a working pairing).
    """
    dismissed = dismissed or set()
    rows: list[dict[str, Any]] = []

    # Self-registered companions are always shown as connected.
    for domain in sorted(registered):
        rows.append(_connected_from_registered(domain, registered[domain]))

    # Catalog detection fills in the rest, skipping anything already registered.
    for entry in CATALOG:
        glue = entry["glue_domain"]
        if glue in registered:
            continue
        if glue in installed_domains:
            rows.append(_connected_from_catalog(entry))
        elif entry["upstream_domain"] in installed_domains and glue not in dismissed:
            rows.append(_suggested_from_catalog(entry))

    return rows
