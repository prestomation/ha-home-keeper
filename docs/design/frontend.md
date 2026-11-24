---
title: Frontend
summary: The sidebar panel, the dashboard task card, and the text both show in the user's language.
implements:
  - custom_components/home_keeper/frontend/src/panel.ts
  - custom_components/home_keeper/frontend/src/draft-step.ts
  - custom_components/home_keeper/frontend/src/refresh-machine.ts
  - custom_components/home_keeper/frontend/src/overlay-state.ts
  - custom_components/home_keeper/frontend/src/panel-host.ts
  - custom_components/home_keeper/frontend/src/panel-chips.ts
  - custom_components/home_keeper/frontend/src/panel-controls.ts
  - custom_components/home_keeper/frontend/src/panel-detail.ts
  - custom_components/home_keeper/frontend/src/panel-icons.ts
  - custom_components/home_keeper/frontend/src/panel-indent.ts
  - custom_components/home_keeper/frontend/src/panel-lists.ts
  - custom_components/home_keeper/frontend/src/panel-parts.ts
  - custom_components/home_keeper/frontend/src/parts-overview.ts
  - custom_components/home_keeper/frontend/src/panel-list-patch.ts
  - custom_components/home_keeper/frontend/src/panel-styles.ts
  - custom_components/home_keeper/frontend/src/panel-task-form.ts
  - custom_components/home_keeper/frontend/src/panel-types.ts
  - custom_components/home_keeper/frontend/src/task-layout.ts
  - custom_components/home_keeper/frontend/src/list-bar.ts
  - custom_components/home_keeper/frontend/src/types.ts
  - custom_components/home_keeper/frontend/src/utils.ts
  - custom_components/home_keeper/frontend/src/api.ts
  - custom_components/home_keeper/frontend/src/forms.ts
  - custom_components/home_keeper/frontend/src/dialogs.ts
  - custom_components/home_keeper/frontend/src/confirm-dialog.ts
  - custom_components/home_keeper/frontend/src/limits.ts
  - custom_components/home_keeper/frontend/src/index.ts
  - custom_components/home_keeper/frontend/src/global.d.ts
  - custom_components/home_keeper/frontend/src/i18n.ts
  - custom_components/home_keeper/frontend/src/locales/*
  - custom_components/home_keeper/frontend/src/card.ts
  - custom_components/home_keeper/frontend/src/card-index.ts
  - custom_components/home_keeper/card*.py
  - custom_components/home_keeper/backend_i18n.py
  - custom_components/home_keeper/*/uk.json
related: [architecture, coordinator-entities, events-api, profiles-notifications, recurrence]
source_hash: 23fb04aacbb7
---

# Frontend

Home Keeper ships 2 browser bundles of TypeScript custom elements. The panel (`home-keeper-panel`)
is the admin surface. The card (`home-keeper-card`) is a usage surface on a dashboard for any user.

## Goals

- **G1. Deep links.** Every page of the panel has a URL, and Back and Forward move inside it.
- **G2. Safe markup.** User text never reaches the DOM as HTML without escaping.
- **G3. CSS picks the layout.** A phone below 700px has its own layout; render code ignores width.
- **G4. A card that always loads.** Also after an upgrade and with a stale cached page.
- **G5. The user's language.** Panel, card and server-built text follow `hass.language`.

## Non-goals

- Business rules and access control. The store and the Python core own them (see
  [the security model](../SECURITY.md)); `limits.ts` only mirrors limits for a fast check.

## Design

### Build and serving

Rollup builds `src/index.ts` and `src/card-index.ts` into 2 IIFE files in `frontend/dist/`.
`panel.async_register_panel` serves only `dist/` as a static path, because Home Assistant
serves static paths before authentication. Each module URL has a `?v=` content hash from
`panel.cache_token`. The panel has `require_admin=False`, and `HomeKeeperPanel._readOnly` hides
each admin-only control from a non-admin. Entry files check the registry before they define.

### Panel: one element, flat regions

`panel.ts` holds the `HomeKeeperPanel` class: `set hass`, `set route`, `_render`, `_hydrate`, the
lifecycle callbacks and the form lifecycles. Each other region is a flat `panel-*.ts` module of free
functions over `PanelHost` (`panel-host.ts`), such as `panel-lists.tasksList`. A region that adds
listeners exports `wireXxx(p, root)`; `_hydrate` calls these in a fixed order. `_render` rebuilds
the shadow tree from strings, so every user value goes through `utils.escapeHTML` first. It records
the focused control (`_focusKey`) and restores it after the rebuild. The task form has sections
(`forms.taskSchemaSections`), and each gets only its own fields (`forms.pickFormData`). A changed
`forms.taskFormSchemaKey` renders the drawer again. `dialogs.makeDialog` builds each dialog. Each
form numbers its draft (`draft-step.ts`); a late save answer for a replaced draft is ignored.
`overlay-state.ts` stacks the open dialogs, forms, sheets and menus with their openers, also in the
card. `_busy()` is the 1 busy rule, only the top overlay takes Escape, and a close gives the
keyboard back to its opener. Every action that loses data asks in `confirm-dialog.ts`
(`confirmDestructive`; the card calls `mountConfirm`), with Cancel as the default.

### Routes

`utils.parseRoute` and `utils.buildPath` are pure and round-trip through the URL parser of the
browser. Paths: `/tasks`, `/tasks/<id>`, `/appliances`, `/appliances/parts`, `/appliances/<id>`,
`/appliances/<id>/<tab>` (`ASSET_TABS`), `/settings/<section>` (`SETTINGS_SECTIONS`) and
`/<tab id>/<path>` for a companion tab ([panel-tabs](panel-tabs.md)). Other paths give the task
list. `utils.encodeRouteSegment` encodes each id and path segment. Only `set route` changes
`_view`, `_detail` and `_partsView` (`_applyLocation`). `_navigate(loc, replace)`: a detail pushes;
a tab or mode switch, a close or a delete replaces. The panel keeps the URL that each history entry
(`hkKey`) shows now, so the back arrow of a section pops only to the index. The Parts mode
(`panel-parts.partsBody`, `parts-overview.ts`) keeps its choices per browser (`LS_PARTS_*`).

### Data and refresh

`api.ts` wraps the websocket commands. `refresh-machine.refreshStep` tells the panel and the card
when to load. A load covers the changes seen at its start (`utils.hkStateSignal`, pushes), so a
change during a load or before a failed one loads again, and a `_refresh` during a load waits for
the next one. The panel waits while `_busy()`, and loads when the last overlay closes. A change in
2 s of its own clean load is its echo. `panel-list-patch.ts` redraws changed rows.

### Task layouts, the list bar, preferences and styles

Tasks draws Rows, Tiles or a Board (`task-layout.ts`, `panel-lists.ts`). Above it,
`panel-controls.taskBar` draws a sticky bar: Search, Filters, the spend button, Add, and a chip for
each active filter (`list-bar.ts`). A sentinel observer marks a pinned bar `data-stuck`. `_render`
keeps the scroll of the board and the appliance pane. A choice about this screen is per browser
(`localStorage`, `LS_*` in `panel-types.ts`). A choice about the person (task layout, intro
dismissed) is per user, in HA frontend user data (`home_keeper_<pref>`, `api.getTaskLayout`).
`panel-styles.STYLES` starts with `--hk-*` tokens on `:host`, each mapped to a Home Assistant theme
variable. Media queries change the layout at 1150px (sheet drawer), 1000px (Settings index) and
700px (bottom tabs, folded filters, stacked rows and parts cards).

### Dashboard card

`card.ts` defines `HomeKeeperCard` and its editor, and shapes tasks with `card-filter.ts`. It
refreshes from `todo/item/subscribe`; an admin also listens for `home_keeper_task_completed`. Rows
show [task photos](task-photos.md). A `profile` picks tasks; `labels` narrow them. A toggle beats
`startsCollapsed`. The card picker (or `preview`) draws `PREVIEW_MAX_ITEMS` rows.
`card.async_register_card` uses one delivery path per install: a Lovelace resource in storage mode,
else `frontend.add_extra_js_url`. Both at once race the scoped element registry.
`card_resource.plan_card_resource` matches rows on the URL path without the `?v=` token and plans
the changes that leave exactly one row. Write `res_type`, read `type`. Panel and card registrations
live for the whole run; only `async_remove_entry` removes them.

### Translations

`i18n.ts` gives `t`, `tn` (CLDR plurals), `tlist` and `tOpt` (a key that only some languages have).
`locales/index.ts` bundles 17 JSON tables, so no fetch occurs. A lookup falls back to English, then
to the key. `backend_i18n.py` builds final text: `resolve_exception` reads the `exceptions` group
of `strings.json`, and `resolve_string` reads `backend_strings/<lang>.json`. Setup loads both.

## Trade-offs

- **String templates, free functions over `PanelHost`:** no dependency and no forwarding layer,
  but the escape and focus rules.

## One-way doors

- Panel URLs under `/home-keeper`. Appliance devices store `/appliances/<id>` as their
  `configuration_url`, so old paths must keep working.
- User-data keys `home_keeper_intro_dismissed`, `home_keeper_task_layout` and
  `home_keeper_preset_nudge`. Store a growable choice as a string; unknown reads as default.
- The card type `custom:home-keeper-card`, its config keys, and `/home_keeper_panel/`.
