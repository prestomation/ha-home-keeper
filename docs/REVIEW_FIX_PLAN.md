# Code-review fix plan (2026-07)

Working checklist for the in-depth code review performed on this branch
(`claude/code-review-maintainability-qwbj3o`). Each item is fixed in its own
commit, and the same commit ticks the box here — so if work stops, the next
session picks up at the first unchecked box. Items are ordered: criticals,
security, majors, minors, maintainability. This file is deleted in the final
cleanup commit once everything is checked.

Conventions for every commit: run the relevant tests locally first
(`pytest tests/unit`, `npm test` / `npm run build` in
`custom_components/home_keeper/frontend`, `mypy custom_components/home_keeper`),
add/extend a regression test where the bug class allows it, and update
`CHANGELOG.md` (`## [Unreleased]`) for user-facing fixes.

## Critical

- [x] C1. Naive `completed_at` corrupts the store: qualify naive datetimes at the
  `store.complete_task` boundary (mirror `models._coerce_seed`) and inside
  `recurrence.apply_completion` as a defence-in-depth. Regression test added
  (`test_apply_completion_qualifies_naive_completed_at`). (`store.py:800`,
  `recurrence.py:288`)
- [x] C2. Unavailable/unknown problem-sensor state must be "skip", not "cleared":
  `problem_sync._is_problem` now returns three-way `True`/`False`/`None`; the
  reconciler transitions only on a definite reading (`is True`/`is False`) and
  leaves the armed state untouched while indeterminate. New sensors start dormant
  on `None`. Regression tests added (indeterminate doesn't clear/arm/false-create).
  (`problem_sync.py:160`, `problem_tasks.py:173`)

## Security

- [x] S1. Stored XSS via completion `photo`: added `isHttpUrl`/`safeHref`/
  `isSafeImageUrl` to `utils.ts`; the history photo now renders only for http(s) or
  site-relative URLs (the `ha-picture-upload` shape), and
  `models.normalize_completion_metadata` rejects unsafe photo values server-side.
  Also routed the other href sinks (panel `_link`, document links, `task_chips` in
  both panel and card) through the guard, and folded card's local `isHttp` into the
  shared helper. Unit + frontend regression tests added.
- [x] S2. Admin-gate the sensitive websocket commands: `@websocket_api.require_admin`
  on `ws_set_options` and `ws_export_inventory` (config-entry mutation and the
  serial/cost inventory export). Service-based integration tests unaffected (they
  call via the admin service path, not the ws command). (`websocket_api.py`)
- [x] S3. Redact sensitive fields in diagnostics via `async_redact_data`:
  `serial_number`, `notes`, `who`, `photo` (recursive by key). Schedule/structural
  fields kept for debugging. (`diagnostics.py`)

## Major bugs

- [x] M1. `merge_update` now recomputes `next_due` only when a recurrence key's
  *value* actually changed (was: key present in payload). Regression tests added:
  completed one-off + realistic rename payload stays dormant; snoozed task rename
  keeps the snooze; genuine interval change still reschedules. (`models.py:614`)
- [x] M2. Reserved `source` namespaces: `reconcile.part_source` now requires
  asset_id/part_id before treating a source as a part source (malformed reserved
  shapes no longer KeyError-brick setup), and `store.add_task` rejects the reserved
  `part`/`problem_sensor` namespaces from the service/ws path (internal reconcilers
  use `build_task` directly, so they're unaffected). Regression test added.
  (`reconcile.py:45`, `store.py:163`)
- [x] M3. Transition edge-state now persists in a process-lifetime `hass.data`
  store keyed by entry id, seeded into each new coordinator. On a *reload* the prior
  state is preserved (not baselined over) during setup, so a transition that
  happened during the reload fires on the first refresh after
  `enable_transition_events` instead of being swallowed; a genuine *restart* (empty
  `hass.data`) still baselines silently. Cleaned up on entry removal. Regression test
  added. (`coordinator.py`, `__init__.py`)
- [x] M4. Unload teardown: gate on `async_loaded_entries(DOMAIN)` (was
  `async_entries`, which is never empty during unload — dead code) so the panel and
  all services are actually removed when the last entry unloads; `_coordinator()`
  now raises a localized `HomeAssistantError` (`integration_not_loaded`, added to
  strings.json + all 16 locales) instead of a bare `RuntimeError`.
  (`__init__.py`)
- [x] M5. Pass `config_entry=entry` to `DataUpdateCoordinator.__init__` (fixes the
  2025.11 implicit-inference removal); `entry` is now a read-only property aliasing
  the base's `self.config_entry`, collapsing the duality. (`coordinator.py`)
- [x] M6. Added `serial_number` to `_ASSET_FIELDS` so `add_asset`/`update_asset`
  services accept it (previously rejected with "extra keys not allowed"). (`__init__.py`)
- [x] M7. To-do item rename support: `async_update_todo_item` now persists
  summary/notes edits via `store.update_task` for a NEEDS_ACTION item (was silently
  discarded), keeping the declared `UPDATE_TODO_ITEM` feature honest. (`todo.py`)
- [x] M8. Added `home_keeper.delete_completion` and
  `home_keeper.delete_archived_completion` services (handlers + schemas + `_SERVICES`
  teardown, services.yaml, strings.json + all 16 locales); the ws commands and
  services share the same store methods. `delete_archived_completion` now fires
  `home_keeper_asset_updated` with `changed_fields: ["archived_history"]`, documented
  in EVENTS.md. (`__init__.py`, `store.py`, `services.yaml`, `strings.json`)
- [x] M9. `async_remove_entry` now calls `manuals.async_delete_all_documents` to
  rmtree the uploaded-documents blob tree on uninstall (was left on disk forever).
  (`__init__.py`, `manuals.py`)
- [x] M10. Confirm-dialog delete now calls `_render()` after the callback, so a
  deleted metadata/part row disappears and the form rebuilds with fresh indices —
  fixing both the invisible deletion and the stale-index closures that corrupted
  sibling rows. (`panel.ts`)
- [x] M11. Panel robustness: initial-load failure now shows a localized error +
  Retry button instead of an infinite spinner (`_loadError`); `_complete`,
  `_deleteAsset`, `_deleteCompletion`, `_deleteArchivedCompletion` catch and toast;
  per-keystroke profile/notification saves are debounced (600ms trailing) so typing
  no longer fires a config-entry reload per character or races out-of-order. New
  locale keys (`error.actionFailed`, `error.loadFailed`, `btn.retry`) across 16
  locales. (`panel.ts`)
- [x] M12. `_openEdit`/`_openEditAsset` now navigate via `_navigate(...)` (URL is
  the single source of truth) instead of mutating `_view`/`_detail`, so reload/
  deep-link, the tab buttons, and Back stay consistent. (`panel.ts`)
- [x] M13. Device triggers: `async_attach_trigger` now derives its event-data
  filter from the device registry alone (`_attach_filter`) instead of the
  coordinator's loaded tasks, so a trigger attached before Home Keeper finishes
  setup no longer freezes to the never-matching sentinel — it fires whenever its
  event arrives, and picks up tasks attached after the automation was created.
  (`device_trigger.py`)
- [x] M14. `add_task`/`delete_task` (both the services and the websocket commands)
  now reload the entry only when the task owns per-task entities (device-attached +
  enabled) via a shared `coordinator.task_has_entities` predicate; otherwise a plain
  refresh — no more N teardown/rebuild cycles when a companion seeds device-less
  tasks. (`__init__.py`, `websocket_api.py`, `coordinator.py`)

## Minor bugs

- [x] N1. Notification "Mark done" action: no-op when the task is no longer
  due/armed (stale tap on a second device must not double-advance).
  (`notifier.py:300`)
- [x] N2. Usage-meter zero-blip: require a meter-reset reading to persist across two
  consecutive readings before re-baselining. (`sensor_tasks.py:113`)
- [x] N3. Added `models._finite_float` (rejects NaN/Infinity) and routed `cost`,
  `sensor.target`, `sensor.value`, and `sensor.baseline` through it. Regression
  tests added. (`models.py`)
- [x] N4. `build_task`/`normalize_fields` now coalesce `notes` with `or ""` so an
  explicit `notes: null` clears the field instead of storing `"None"`. Regression
  test added. (`models.py`)
- [x] N5. Purged one-off tasks: clean up per-task entities when the coordinator
  purges expired one-offs (reload gate like the service delete path).
  (`coordinator.py:132`)
- [x] N6. Calendar: fixed occurrences count as active during their event window;
  window queries include events overlapping the window start.
  (`calendar.py:91,128`)
- [x] N7. `apply_completion` now replaces (rather than appends) a completion at an
  already-present ISO `ts`, so a double-tapped notification / duplicated automation
  can't create an ambiguous twin entry that undo/edit can't disambiguate. Regression
  test added. (`recurrence.py`)
- [x] N8. Frontend bucket drift: dormant sensor tasks land in the Monitored bucket
  (panel + card-filter); card hides Done on completed one-offs; panel
  `_statusBucket` gets card-filter's NaN guard; `dueLabel`/`_relativeDay` use
  calendar days, not 24-hour buckets. (`panel.ts:1415,1421`, `card-filter.ts:89`,
  `card.ts:786`, `utils.ts:98`)
- [x] N9. `strings.json` ↔ `services.yaml` parity: add `register_companion` /
  `list_companions` strings; add missing field strings (`labels`, `card_links`,
  `task_chips`, `source`, completion metadata fields, `dismissed_companions`);
  document schema-only fields (`completion_detail`, `completion_required_fields`,
  `managed_by`, snooze/skip `origin`).
- [x] N10. Documents: stream GETs via `web.FileResponse` (no 25 MB buffering) and
  write the blob to disk *before* persisting store metadata/firing the event.
  (`manuals.py:151,227`)
- [x] N11. `testing.py` fake now computes `changed_fields` via the store's real
  `_changed_fields` before/after diff (was: every provided key), so it can't fire a
  `task_updated` the real integration wouldn't. (`testing.py`)
- [x] N12. Feature-module minors: `last_replaced` validation uses injected `now`
  (not naive `date.today()`); enforce the document cap after `_merge_documents`;
  cap companion registry entry sizes/count; drop the dead `declared_type` param
  from `validate_upload`. (`assets.py:437,212`, `companions.py:68`,
  `documents.py:59`)
- [x] N13. Frontend leaks/races: panel `disconnectedCallback` removes confirm scrim
  + document keydown listener (and `_openConfirmDialog` removes a previous scrim);
  card `_subscribe` unsubscribes if disconnected mid-flight; panel guards duplicate
  initial load; card editor stops refetching profiles on every hass churn.
  (`panel.ts:1006`, `card.ts:398,905`)

## Maintainability

- [ ] R1. Extract services from `__init__.py` into `services.py`: registration
  table (teardown derived from it), exception-translation decorator for the
  copy-pasted `KeyError → task_not_found` blocks, schemas alongside. `__init__.py`
  keeps only entry lifecycle.
- [x] R2. Shared coordinator lookup helper in `coordinator.py`: `get_coordinator`
  (returns `None` when unloaded) and `require_coordinator` (raises the localized
  `integration_not_loaded`). Replaced the four hand-rolled copies in
  `websocket_api.py`, `device_trigger.py`, `manuals.py`, and `__init__.py`.
- [ ] R3. Shared registry-prune helper for the four entity platforms + shared part
  lookup for `number.py`/`binary_sensor.py`. (`sensor.py:73`, `binary_sensor.py:75`,
  `button.py:39`, `number.py:53`)
- [ ] R4. Single content-type allowlist in `const.py` (used by `assets.py` and
  `documents.py`).
- [ ] R5. Panel list-shaping folds onto `card-filter.ts`'s pure functions
  (`statusBucket`/`bucketByKey`/`taskAreaId`) to kill the drift class fixed in N8.
- [ ] R6. Extract the Settings tab from `panel.ts` into `settings.ts` (profiles /
  notifications / companions), deduplicating the near-identical
  `_renderProfiles`/`_renderNotifications` pair.
- [ ] R7. Extract the asset editor (form + schemas + parts/metadata/documents
  editors) from `panel.ts` into `asset-form.ts`.
- [ ] R8. Contract hygiene: coordinator returns a copy (or documents the live-dict
  alias loudly + asserts `always_update`); `problem_tasks` reconciler stops
  mutating store dicts in place; `transitions.py` uses a public parse helper
  instead of `recurrence._parse`.

## Wrap-up

- [ ] W1. UI screenshots for the panel-touching changes (Playwright harness →
  `docs/images/`, embedded in the PR body per AGENTS.md), CHANGELOG entries
  complete, full test suite + mypy + frontend build green, request final Cue
  review.
- [ ] W2. Delete this plan file in the final commit.
