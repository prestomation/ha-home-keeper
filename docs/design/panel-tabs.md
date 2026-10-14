---
title: Companion panel tabs
summary: How a companion integration adds an admin tab to the Home Keeper panel.
implements:
  - custom_components/home_keeper/panel_tabs.py
  - custom_components/home_keeper/frontend/src/panel-tabs.ts
related: [companions-presets, frontend, events-api, architecture]
source_hash: 323bcccfe25a
---

# Companion panel tabs

A companion integration can add a tab to the Home Keeper panel. The tab shows the
companion's own admin UI, such as the books of Home Keeper Library, with no second
sidebar panel. The companion registers the tab in Python, and the panel loads the
companion's ES module and shows its custom element.

## Goals

- **G1. One panel.** A companion's admin UI is a tab in the Home Keeper panel, with
  the same URL rules, Back and Forward, and the same phone layout.
- **G2. A small, stable contract.** 1 Python call, 1 websocket read, and a host API
  object with a version, so a tab and the panel can change apart.
- **G3. Admin only.** A tab is code that runs in the panel. Only in-process code can
  add one, and only an admin sees it.
- **G4. A failure stays in the tab.** A tab that does not load shows an error and
  Retry in that tab. The rest of the panel works.

## Non-goals

- QR labels or any other feature of a specific companion.
- Storage of tab data in Home Keeper. A tab keeps its own data in its own integration.
- A service that registers a tab. `register_companion` does not accept one.
- Settings for the tab. Configure opens the companion's integration page, as before.
- A fixed place for the entry of a tab. The entry is in the tab bar now, a later release
  can move it to a menu or a launcher, and `order` is only a hint.

## Design

### Registration

`panel_tabs.PanelTab` is a frozen dataclass: `companion`, `id`, `titles` (language
code to title, `en` required), `icon`, `module_url`, `element`, `host_api` (default 1)
and `order` (default 100). A companion calls `panel_tabs.async_register_panel_tab` in
its `async_setup_entry` and passes the callable it gets back to `entry.async_on_unload`.

`panel_tabs.validate_panel_tab` raises `ValueError` with the reason. The `id` matches
`TAB_ID_PATTERN`, is not in `RESERVED_TAB_IDS` (the first segments that `parseRoute`
owns, and the segments kept for later pages) and is not registered. The `module_url` is
a same-origin path: 1 leading `/`, no `//`, no backslash, no space or control character,
and no `..` segment, also after percent decoding. The `element` matches
`ELEMENT_PATTERN`, is not a Home Keeper element and is not used by another tab. The
registered copy holds a read-only copy of `titles`.

`panel_tabs.PanelTabRegistry` holds at most `const.MAX_PANEL_TABS` tabs on `hass.data`
for the Home Assistant run. An entry reload keeps it, as it keeps the sidebar panel.
`async_remove_entry` clears it. The unregister callable is idempotent and removes only
its own registration. The module imports Home Assistant only for type annotations, so
it is in the mutation allowlist.

### Read and options

`home_keeper/get_panel_tabs` is admin-only and needs no loaded entry. It returns every
tab from `panel_tabs.project_panel_tabs`: the title for the `language` field of the
call, then the Home Assistant language, then `en` (`panel_tabs.resolve_title` tries the
exact code, then the base code). The rows are sorted by `order`, title and id.

The `hidden_panel_tabs` option is a list of tab ids. It is an id list in
`options._normalize`, so the options flow keeps it, and `set_options` writes it. An id
of a tab that is not registered stays in the list.

### Panel

`utils.parseRoute` keeps an unknown first segment that matches `PANEL_TAB_ID_RE` as
`{view: 'tab', tab, path}`. `utils.normalizeTabPath` removes dot segments, empty
segments, a query and a fragment, so a path never leaves the tab. `buildPath` writes
`/<id><path>`. After the load, an id that `utils.visiblePanelTabs` does not show goes
to the task list with a replace.

The tab bars show Tasks, Appliances, the visible tabs, then Settings.
`panel-tabs.ensureTabLoaded` checks `host_api` against `utils.PANEL_HOST_API` first,
then imports the module 1 time per URL, waits for `customElements.whenDefined` for
`TAB_DEFINE_TIMEOUT_MS`, and makes 1 element per tab for the life of the panel. A redraw
moves the element into the new tree. A move inside the open tab only sets `route`.
Retry imports a new URL with a `hk_retry` query value, because a browser keeps a
failed module in its module map.

The panel sets `hass` on each update, `narrow`, `route` and `host`. `panel-tabs.hostApi` is a frozen
object: `apiVersion`, `navigate` (through `_navigate`), `taskLink`, `applianceLink`, `openTask`,
`openAppliance` and `showToast`. `panel-tabs.onTabLinkClick` listens on the tab area: a plain left
click on a link that `utils.panelSubPath` maps to a panel route goes through `_navigate`, with no
page load. A modified click, a `target`, a `download`, or a click that the tab handled goes to the
browser. Settings → Companions shows a **Panel tab** chip and a **Show tab** switch on the row of
the companion that owns the tab. A companion with a tab and no `register_companion` row gets a row
of its own.

## Trade-offs

- **A Python API** over **a service field**: only code that already runs in the
  process can put script in the admin panel.
- **A registry for the run** over **one cleared on each unload**: a reload is routine
  (each options save), and the companion does not set up again after it.
- **No bus event** for a registry change: it is not store state, and no automation acts
  on it. `api_surface.SURFACE_KINDS` records this.
- **A kept element** over **a new element per visit**: the tab keeps its state, at the
  cost of a disconnect and a connect on each panel redraw.

## One-way doors

- The `PanelTab` fields and defaults, and the import path
  `custom_components.home_keeper.panel_tabs` with `async_register_panel_tab`.
- The URL shape `/home-keeper/<id>/<path>` and the reserved ids. `RESERVED_TAB_IDS` is
  `ROUTED_TAB_IDS` plus `FUTURE_TAB_IDS`, the segments kept for later Home Keeper pages.
  A new reserved id breaks a companion that uses it, so add it before a companion can.
- Host API version 1: the element properties, the `host` methods, and the link clicks
  that the panel opens.
- The `home_keeper/get_panel_tabs` reply and the `hidden_panel_tabs` option key.
