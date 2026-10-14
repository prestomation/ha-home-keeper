"""Companion panel tabs: a companion integration adds a tab to the Home Keeper panel.

A companion calls :func:`async_register_panel_tab` from its own ``async_setup_entry``
and passes the unregister callable that it gets back to ``entry.async_on_unload``.
The panel reads the tabs through the admin-only ``home_keeper/get_panel_tabs``
websocket command, imports the tab's ES module and shows its custom element.

This is a Python API and not a service. A tab runs JavaScript in the admin panel
with the session of the admin, so only code that runs in the Home Assistant process
can add one. That code already has full access, so the API adds no new risk. The
``register_companion`` service, which any user with service access can call, does
not accept a tab.

The registry is in memory on ``hass.data`` for the Home Assistant run. A reload of
the Home Keeper entry keeps it, as it keeps the sidebar panel. The removal of the
entry clears it. A change to the registry is not store state, so it fires no bus
event (see ``api_surface.SURFACE_KINDS``).

The module imports Home Assistant only for type annotations, so the unit tier and
the mutation gate run it with no Home Assistant installed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

from .const import DATA_PANEL_TABS, MAX_PANEL_TABS

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

# The tab id is the first URL segment under the panel: ``/home-keeper/<id>/...``.
TAB_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
# The first URL segments that the panel routes itself (``utils.parseRoute``).
ROUTED_TAB_IDS = frozenset({"tasks", "appliances", "settings"})
# First URL segments that Home Keeper keeps for pages it can add later, such as a
# launcher that holds many tabs. A companion cannot take one, so a later page there
# breaks no companion. ``utils.ts`` keeps the same list in ``RESERVED_TAB_IDS``.
FUTURE_TAB_IDS = frozenset(
    {
        "apps",
        "calendar",
        "companions",
        "dashboard",
        "help",
        "history",
        "more",
        "notifications",
        "overview",
        "profiles",
        "search",
    }
)
RESERVED_TAB_IDS = ROUTED_TAB_IDS | FUTURE_TAB_IDS
# A tab element shares the panel's prefix, so a tab element is easy to identify.
ELEMENT_PATTERN = re.compile(r"^home-keeper-[a-z0-9-]+$")
# The custom elements that Home Keeper defines itself.
HOME_KEEPER_ELEMENTS = frozenset(
    {"home-keeper-panel", "home-keeper-card", "home-keeper-card-editor"}
)
# A Home Assistant integration domain.
COMPANION_PATTERN = re.compile(r"^[a-z0-9_]{1,100}$")
# A language code key in ``titles``, such as ``en`` or ``pt-BR``.
LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{1,8}){0,2}$")
MAX_MODULE_URL_LEN = 500
MAX_TITLE_LEN = 50
MAX_TITLES = 50
MAX_ICON_LEN = 100
FALLBACK_LANGUAGE = "en"


@dataclass(frozen=True)
class PanelTab:
    """One tab that a companion integration adds to the Home Keeper panel."""

    companion: str
    """The domain of the companion integration that owns the tab."""
    id: str
    """The URL segment: the tab is at ``/home-keeper/<id>/...``."""
    titles: Mapping[str, str]
    """Language code to tab title. ``en`` is required."""
    icon: str
    """An icon name, such as ``mdi:bookshelf``."""
    module_url: str
    """The same-origin path of the ES module that defines ``element``."""
    element: str
    """The custom element tag that the module defines."""
    host_api: int = 1
    """The lowest panel host API version that the tab needs."""
    order: int = 100
    """The sort key among the companion tabs. Lower comes first."""


def _is_int(value: Any) -> bool:
    """Whether *value* is an ``int`` and not a ``bool``."""
    return isinstance(value, int) and not isinstance(value, bool)


def _check_module_url(url: Any) -> None:
    """Raise ``ValueError`` if *url* is not a safe same-origin module path."""
    if not isinstance(url, str) or not url:
        raise ValueError("module_url must be a non-empty string")
    if len(url) > MAX_MODULE_URL_LEN:
        raise ValueError(f"module_url must be at most {MAX_MODULE_URL_LEN} characters")
    if not url.startswith("/") or url.startswith("//"):
        raise ValueError("module_url must start with a single '/'")
    if any(ord(char) <= 0x20 or ord(char) == 0x7F for char in url):
        raise ValueError("module_url must not contain a space or a control character")
    path = unquote(urlsplit(url).path)
    if "\\" in url or "\\" in path:
        raise ValueError("module_url must not contain a backslash")
    if path.startswith("//"):
        raise ValueError("module_url must start with a single '/'")
    if ".." in path.split("/"):
        raise ValueError("module_url must not contain a '..' segment")


def _check_titles(titles: Any) -> dict[str, str]:
    """Return a copy of *titles*, or raise ``ValueError`` if it is not valid."""
    if not isinstance(titles, Mapping):
        raise ValueError("titles must be a mapping of language code to title")
    if len(titles) > MAX_TITLES:
        raise ValueError(f"titles must have at most {MAX_TITLES} languages")
    clean: dict[str, str] = {}
    for lang, title in titles.items():
        if not isinstance(lang, str) or not LANGUAGE_PATTERN.match(lang):
            raise ValueError(f"titles has a language code that is not valid: {lang!r}")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"titles[{lang!r}] must be a non-empty string")
        if len(title) > MAX_TITLE_LEN:
            raise ValueError(
                f"titles[{lang!r}] must be at most {MAX_TITLE_LEN} characters"
            )
        clean[lang] = title.strip()
    if FALLBACK_LANGUAGE not in clean:
        raise ValueError("titles must have a non-empty 'en' title")
    return clean


def validate_panel_tab(tab: Any, registered: Mapping[str, PanelTab]) -> PanelTab:
    """Return a checked copy of *tab*, or raise ``ValueError`` with the reason.

    *registered* holds the tabs that are already registered, by id. The copy holds
    its own read-only copy of ``titles``, so a later change to the caller's mapping
    does not change the registered tab.
    """
    if not isinstance(tab, PanelTab):
        raise ValueError("tab must be a PanelTab")
    if not isinstance(tab.companion, str) or not COMPANION_PATTERN.match(tab.companion):
        raise ValueError("companion must be an integration domain")
    if not isinstance(tab.id, str) or not TAB_ID_PATTERN.match(tab.id):
        raise ValueError(f"id must match {TAB_ID_PATTERN.pattern}")
    if tab.id in RESERVED_TAB_IDS:
        raise ValueError(f"id {tab.id!r} is reserved by Home Keeper")
    if tab.id in registered:
        raise ValueError(f"id {tab.id!r} is already registered")
    if not isinstance(tab.element, str) or not ELEMENT_PATTERN.match(tab.element):
        raise ValueError(f"element must match {ELEMENT_PATTERN.pattern}")
    if tab.element in HOME_KEEPER_ELEMENTS:
        raise ValueError(f"element {tab.element!r} is a Home Keeper element")
    if any(other.element == tab.element for other in registered.values()):
        raise ValueError(f"element {tab.element!r} is already registered")
    _check_module_url(tab.module_url)
    titles = _check_titles(tab.titles)
    icon = tab.icon
    if not isinstance(icon, str) or not icon or len(icon) > MAX_ICON_LEN:
        raise ValueError(f"icon must be a string of 1 to {MAX_ICON_LEN} characters")
    if any(char.isspace() for char in icon):
        raise ValueError("icon must not contain a space")
    if not _is_int(tab.host_api) or tab.host_api < 1:
        raise ValueError("host_api must be an integer of 1 or more")
    if not _is_int(tab.order):
        raise ValueError("order must be an integer")
    return replace(tab, titles=MappingProxyType(titles))


def resolve_title(titles: Mapping[str, str], language: str | None) -> str:
    """The title for *language*, then for its base language, then the ``en`` title.

    A match is not case-sensitive, and ``_`` and ``-`` are the same, so ``pt_br``
    finds the ``pt-BR`` title.
    """
    by_key = {lang.lower().replace("_", "-"): title for lang, title in titles.items()}
    wanted = (language or "").lower().replace("_", "-")
    for candidate in (wanted, wanted.partition("-")[0]):
        if candidate and candidate in by_key:
            return by_key[candidate]
    return titles[FALLBACK_LANGUAGE]


def project_panel_tabs(
    tabs: list[PanelTab], language: str | None
) -> list[dict[str, Any]]:
    """The tabs as the panel reads them, sorted by ``order``, then title, then id."""
    titled = [(tab, resolve_title(tab.titles, language)) for tab in tabs]
    titled.sort(key=lambda pair: (pair[0].order, pair[1].casefold(), pair[0].id))
    return [
        {
            "id": tab.id,
            "companion": tab.companion,
            "title": title,
            "icon": tab.icon,
            "module_url": tab.module_url,
            "element": tab.element,
            "host_api": tab.host_api,
            "order": tab.order,
        }
        for tab, title in titled
    ]


class PanelTabRegistry:
    """The registered tabs, by id."""

    def __init__(self) -> None:
        self._tabs: dict[str, PanelTab] = {}

    def register(self, tab: PanelTab) -> Callable[[], None]:
        """Add *tab* and return a callable that removes it again.

        Raise ``ValueError`` if the tab is not valid, if its id or its element is
        already registered, or if the registry holds ``MAX_PANEL_TABS`` tabs. The
        callable is idempotent. It removes only this registration, so a call after a
        new registration of the same id leaves the new tab in place.
        """
        checked = validate_panel_tab(tab, self._tabs)
        if len(self._tabs) >= MAX_PANEL_TABS:
            raise ValueError(f"the registry holds the maximum of {MAX_PANEL_TABS} tabs")
        self._tabs[checked.id] = checked

        def unregister() -> None:
            if self._tabs.get(checked.id) is checked:
                del self._tabs[checked.id]

        return unregister

    def tabs(self) -> list[PanelTab]:
        """The registered tabs, in registration order."""
        return list(self._tabs.values())

    def clear(self) -> None:
        """Remove every tab."""
        self._tabs.clear()


def async_get_registry(hass: HomeAssistant) -> PanelTabRegistry:
    """Return the registry on *hass*, and make it if it does not exist."""
    registry = hass.data.get(DATA_PANEL_TABS)
    if not isinstance(registry, PanelTabRegistry):
        registry = PanelTabRegistry()
        hass.data[DATA_PANEL_TABS] = registry
    return registry


def async_register_panel_tab(hass: HomeAssistant, tab: PanelTab) -> Callable[[], None]:
    """Add a companion tab to the Home Keeper panel and return its unregister callable.

    Call it from the event loop, in the companion's ``async_setup_entry``, and pass
    the result to ``entry.async_on_unload``. Raise ``ValueError`` with the reason if
    the tab is not valid.
    """
    return async_get_registry(hass).register(tab)


def async_list_panel_tabs(hass: HomeAssistant, language: str | None) -> list[dict]:
    """The registered tabs as the panel reads them, with titles for *language*."""
    return project_panel_tabs(async_get_registry(hass).tabs(), language)


def async_clear_panel_tabs(hass: HomeAssistant) -> None:
    """Remove every tab. Called when the Home Keeper entry is removed."""
    registry = hass.data.get(DATA_PANEL_TABS)
    if isinstance(registry, PanelTabRegistry):
        registry.clear()


__all__ = [
    "PanelTab",
    "PanelTabRegistry",
    "async_list_panel_tabs",
    "async_register_panel_tab",
    "project_panel_tabs",
    "resolve_title",
    "validate_panel_tab",
]
