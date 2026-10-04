---
title: Frontend
summary: The admin sidebar panel, the dashboard task card, and the text both show in the user's language.
implements:
  - custom_components/home_keeper/frontend/src/panel.ts
  - custom_components/home_keeper/frontend/src/panel-host.ts
  - custom_components/home_keeper/frontend/src/panel-chips.ts
  - custom_components/home_keeper/frontend/src/panel-controls.ts
  - custom_components/home_keeper/frontend/src/panel-detail.ts
  - custom_components/home_keeper/frontend/src/panel-icons.ts
  - custom_components/home_keeper/frontend/src/panel-indent.ts
  - custom_components/home_keeper/frontend/src/panel-lists.ts
  - custom_components/home_keeper/frontend/src/panel-styles.ts
  - custom_components/home_keeper/frontend/src/panel-task-form.ts
  - custom_components/home_keeper/frontend/src/panel-types.ts
  - custom_components/home_keeper/frontend/src/task-layout.ts
  - custom_components/home_keeper/frontend/src/types.ts
  - custom_components/home_keeper/frontend/src/utils.ts
  - custom_components/home_keeper/frontend/src/api.ts
  - custom_components/home_keeper/frontend/src/forms.ts
  - custom_components/home_keeper/frontend/src/dialogs.ts
  - custom_components/home_keeper/frontend/src/limits.ts
  - custom_components/home_keeper/frontend/src/index.ts
  - custom_components/home_keeper/frontend/src/global.d.ts
  - custom_components/home_keeper/frontend/src/i18n.ts
  - custom_components/home_keeper/frontend/src/locales/index.ts
  - custom_components/home_keeper/frontend/src/card.ts
  - custom_components/home_keeper/frontend/src/card-index.ts
  - custom_components/home_keeper/card.py
  - custom_components/home_keeper/card_resource.py
  - custom_components/home_keeper/backend_i18n.py
related: [architecture, coordinator-entities, events-api, profiles-notifications]
source_hash: 827cfa6f4ff7
---

# Frontend

Home Keeper ships 2 browser bundles of plain TypeScript custom elements. The panel
(`home-keeper-panel`) is the admin surface. The card (`home-keeper-card`) is a usage surface
on a dashboard that any user can see.

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
`panel.cache_token`, so a rebuild busts caches. The panel registers with `require_admin=True`.
Both entry files check the registry before `customElements.define`, so a second load is safe.
`global.d.ts` types the `panel-version` module that Rollup fills from `const.py`.

### Panel: one element, flat regions

`panel.ts` holds the `HomeKeeperPanel` class: `set hass`, `set route`, `_render`, `_hydrate`,
the lifecycle callbacks and the form lifecycles. Each other region is a flat `panel-*.ts`
module of free functions over `PanelHost` (`panel-host.ts`), such as `panel-lists.tasksList`.
A region that adds listeners exports `wireXxx(p, root)`; `_hydrate` calls these in a fixed
order. Add a `PanelHost` member only when a region needs live panel state. New modules stay
flat in `src/`, because the i18n parity test and Stryker do not read subdirectories.

`_render` rebuilds the shadow tree from strings, so every user value goes through
`utils.escapeHTML` first. `_render` records the focused control (`_focusKey`) and restores it
after the rebuild. The task form is split into sections (`forms.taskSchemaSections`), and each
section gets only its own fields through `forms.pickFormData`. Thus one section cannot write
stale values over another. `dialogs.makeDialog` is the one `ha-dialog` builder.

### Routes

`utils.parseRoute` and `utils.buildPath` are pure and round-trip. Paths: `/tasks`,
`/tasks/<id>`, `/appliances`, `/appliances/<id>`, `/appliances/<id>/<tab>` (`ASSET_TABS`) and
`/settings/<section>` (`SETTINGS_SECTIONS`). An unknown path gives the task list. `set route`
is the only place that changes `_view` and `_detail`, via `_applyLocation`. Code navigates with
`_navigate(loc, replace)`: opening a detail pushes; a tab switch, a close or a delete replaces.
A form is an overlay with no URL. `utils.navigateTo` leaves the panel, with a visible mark.

### Data and refresh

`api.ts` wraps the websocket commands; `types.ts` declares their shapes. `_refresh` loads all
data. On each `hass` push, `_liveRefresh` compares `utils.hkStateSignal` and loads again when
a task changed elsewhere, but not while a form or a dialog is open.

### Task layouts and preferences

The Tasks tab draws a list as Rows, Tiles or a Board. `task-layout.ts` holds the pure part:
`parseTaskLayout`, `shortDueLabel`, `urgencyClass` and the action-sheet actions, which
follow `defer.deferVerbs`.
`panel-lists.ts` draws the markup; `panel-controls.groupTasks` gives the board columns.

- **Per browser:** a choice about this screen (group by, filter, tree collapse) goes in
  `localStorage` under the `LS_*` keys in `panel-types.ts`.
- **Per user:** a choice about the person (task layout, intro dismissed) goes in Home Assistant
  frontend user data under a `home_keeper_<pref>` key, through `api.getTaskLayout` and peers.

### Styles and the phone layout

`panel-styles.STYLES` starts with `--hk-*` tokens on `:host`, each mapped to a Home Assistant
theme variable; no rule uses a literal colour. Viewport media queries change the layout at
1150px (bottom-sheet drawer), 1000px (Settings index) and 700px (phone: bottom tab bar,
floating Add, wrapped chips, stacked rows). Never put `container-type` on `:host`.

### Dashboard card

`card.ts` defines `HomeKeeperCard` and its editor (groups from `group-editor.ts`), and
shapes tasks with `card-filter.ts`. It refreshes from `todo/item/subscribe`, which any
user can open; an admin also listens for `home_keeper_task_completed`. The rows and the
New task form show task photos ([task-photos](task-photos.md)).

`card.async_register_card` uses one delivery path per install: a Lovelace resource in storage
mode, else `frontend.add_extra_js_url`. Both at once race the scoped element registry.
`card_resource.plan_card_resource` matches rows on the URL path without the `?v=` token and
plans the changes that leave exactly one row. Write `res_type`, read `type`. Panel and card
registrations live for the Home Assistant run; only `async_remove_entry` removes them.

### Translations

`i18n.ts` gives `t`, `tn` (CLDR plurals) and `tlist`. `locales/index.ts` puts 16 JSON tables
in the bundle, so no fetch occurs. A lookup falls back to English, then to the key.
`backend_i18n.py` builds final text in Python. `resolve_exception` reads the `exceptions`
group of `strings.json` for websocket and upload errors. `resolve_string` reads
`backend_strings/<lang>.json` for other text, such as CSV headers. Pure callers take `lang`
as a parameter. Setup runs `backend_i18n.preload` in the executor, so reads never block the loop.

## Trade-offs

- **Custom elements and string templates** over a framework: one small IIFE with no runtime
  dependency, at the cost of the escape and focus rules above.
- **Free functions over `PanelHost`** over sub-controller classes: no forwarding layer, and
  each region's access to the panel is typed.

## One-way doors

- Panel URLs under `/home-keeper`. Appliance devices store `/appliances/<id>` as their
  `configuration_url`, so old paths must keep working.
- User-data keys `home_keeper_intro_dismissed`, `home_keeper_task_layout` and
  `home_keeper_preset_nudge`. Store a growable choice as a string; unknown reads as default.
- The card type `custom:home-keeper-card`, its config keys, and `/home_keeper_panel/`.
