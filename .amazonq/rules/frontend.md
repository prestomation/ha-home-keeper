---
title: Frontend rules
summary: Rules for the panel and the card - routing, markup, styles, layout, accessibility and HA elements.
---

# Frontend rules

How the panel and the card work is in [frontend](../../docs/design/frontend.md).

## Routing

- **The URL is the source of truth.** Every page maps to a URL under `/home-keeper`. The
  `set route` setter is the only place that changes `_view` or `_detail`. Never set them
  directly to navigate.
- Navigate with `_navigate(location, replace?)`. Opening a detail pushes. Switching a tab,
  closing a detail or deleting an object replaces.
- Keep `parseRoute` and `buildPath` pure in `utils.ts`. An unknown path falls back to the
  task list. A detail URL for a deleted object shows the gone notice.
- **A new URL segment keeps old URLs working.** Appliance devices store
  `/appliances/<id>` in `configuration_url`. `buildPath` leaves the default tab out.
- Forms are not deep-linked. Opening the edit drawer does not change the URL, except an
  edit on another view (`_navigate` plus `_pendingEdit`). Mount the drawer in `_hydrate`
  before the task-detail early return.
- `utils.navigateTo` leaves the panel. A control that leaves carries the
  `.hk-chip-ext` mark.
- A device chip on a task opens the appliance page in the panel. On an appliance it opens
  the device page. `assetForTask` in `utils.ts` is the 1 ranking for a task's appliance.

## Markup and text

- Escape all user content with `escapeHTML` before it goes into `innerHTML`.
- The frontend has no runtime dependencies. The Rollup config has no `node-resolve` plugin.
- A third-party module that the panel needs is vendored into `src/` with its license
  header and a note on the changes, as `qrcodegen.ts` is. Do not edit a vendored file.

### Markdown

- Every notes field renders as Markdown through `markdown.ts` (`markdownBlock`,
  `wireMarkdown`) and HA's `ha-markdown`. Never bundle a parser.
- `ha-markdown` loads lazily. Always keep the escaped-text fallback working.
- Store Markdown source, never HTML. Debounce a preview and update it in place.

## Styles

- **Every rule reads a `--hk-*` token. No rule writes a literal color.** Each token
  resolves to a Home Assistant theme variable or a `color-mix()` of one.
- **Set a button's weight with `btnAttrs()` or `setBtnWeight()`** (`utils.ts`). Never write
  `ha-button` attributes by hand, and never use `raised` or `destructive`: `ha-button`
  reads only `appearance`, `variant` and `size`. 1 primary action per surface. Cancel is
  `tertiary`. `danger-primary` is only for a surface whose whole job is a delete.
- Pair each `*-soft` token with a `*-ink` token for its label. Check a color pair against
  rendered pixels in both themes.
- Status chips have no outline. The row's action has the ring.
- Style inside an HA element through its `::part`, keyed on `data-hk-weight`.
- Reuse `.hk-eyebrow` and `.hk-indent`. Do not restate their rules.
- Both list rows use the same fixed tracks (`--hk-chip-col`, `--hk-status-col`). A chip
  strip holds 1 element per chip.

## Layout

- **Only CSS picks the layout.** Breakpoints are viewport `@media` queries. Nothing in
  `_render()` or `_hydrate()` reads the viewport. A route can render differently by width.
- **Never put `container-type` on `:host`.** It anchors fixed children to the content.
- Prefer `position: sticky` for panes. Use `fixed` only for a true viewport overlay.
- Breakpoints: 1150px (drawer becomes a bottom sheet), 1000px (Settings index, appliance
  pane steps aside), 700px (phone). A breakpoint about panel width adds about 250px for
  the HA sidebar.
- Never dim a container whose child must stay bright. Fade the elements one by one.
- Dimming is not disabling. Use `inert` where the drawer covers the list.

## Accessibility

- `_render()` restores focus through `_focusKey()` and `_restoreFocus()`. Give every
  control a stable `data-*` attribute.
- Focus an HA element through `_focus()`, never `el.focus()`.
- State shown by color has a text equivalent.
- Do not declare a widget role that you have not implemented. Navigation between URLs is
  buttons with `aria-current="page"`.
- `tests/e2e/tests/a11y.spec.ts` pins these rules.

## Task actions

- **`utils.isMonitoredDormant` is the 1 rule for "no Done".** The task page, the list and
  the card read it. Do not write the rule again on a surface.
- A dormant usage meter and a counted wear item's replacement task keep Done, because an
  early completion is real work.
- `card-filter.statusBucket` is a section rule and does not read that predicate.
- `sourceOwnedTask` lists the tasks that a reconciler owns wholly. They offer no Edit or
  Duplicate. A source-owned caption names its source.
- A declarative-companion task is managed. Edit shows only the unlocked fields, and the
  page adds **Edit companion**.
- Home Keeper is never the target of an "Edit in X" link. Check the domain against
  `utils.HK_DOMAIN` first.

## Forms

- **1 `ha-form` per section**, seeded with `pickFormData(data, section.fields)`. A change
  handler checks that a field is present before it reads it.
- A field that another field reveals lives in a dependent `ha-form` whose `schema` is set
  in place. Never call `_render()` from a `value-changed` handler.
- A collapsible is a native `details` with the panel's summary parts. Keep open state in
  panel state.
- Keep `hk-task-form` on the wrapper `<div>`. A test dispatches `value-changed` at the
  section that owns the field.
- A failed action shows inline next to its control and in a `_toast(...)`.
- A backend limit that the panel checks is mirrored in `limits.ts` and guarded by
  `tests/unit/test_upload_limit_parity.py`. The backend stays the authority.

## Documents and files

- `AssetDocument` is a union on `kind`. Every surface uses the `documents.ts` helpers.
  Never write `doc.kind === 'file' ? … : …` at a call site.
- **Open a file with a real `<a href>` that is signed before the tap**
  (`SignedUrlCache`). Never call `window.open` after an `await`: iOS blocks it. Give the
  tap target at least 44px.

## Modules

- `panel.ts` holds the element. Each region is a flat `panel-*.ts` module that exports
  free functions over `PanelHost` (`panel-host.ts`). No classes, mixins or shims.
- `PanelHost` is the coupling surface. Prefer an argument to a new member.
- New modules stay flat in `src/`. Several gates read `src/*.ts` without recursion.
- Pure logic that earns direct tests goes in an on-surface module (`utils`, `forms`,
  `documents`, `card-filter`), not in a `panel-*.ts` module.

## Preferences

- **A choice about this screen is per-browser**: localStorage through the `LS_*` keys in
  `panel-types.ts`. **A choice about the person is per-user**: HA frontend user data under
  `home_keeper_<pref>`.
- A user-data key and its values are a one-way door. Store a choice that can grow as a
  string, never a boolean, and read an unknown value as the default.

## Home Assistant elements

- **Use only HA elements that a custom panel page registers.** Check with
  `customElements.get('<tag>')` in the e2e container. Otherwise build from plain DOM and
  theme variables.
- **Probe a real element before you design against it.** `observedAttributes` tells you
  what it still reads. Assert on rendered pixels, not markup, where HA draws.
- Build an `ha-dialog` with `makeDialog` from `dialogs.ts`. Do not write a new one. The
  delete confirmation is a body-level scrim, not an `ha-dialog`.
- **Never tear down the panel or the card resource on unload.** Most unloads are half of a
  reload. Remove them in `async_remove_entry`, and the panel also for a disabled entry.
- **The card loads by 1 path per install.** A Lovelace resource in storage mode.
  `add_extra_js_url` only in YAML mode or when the resource write fails. Never both.
  `card_resource.py` plans the change, and `card.py` applies it.
