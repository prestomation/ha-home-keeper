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
- [ ] M8. Services parity for completion deletion: add
  `home_keeper.delete_completion` + `home_keeper.delete_archived_completion`
  services (services.yaml + strings.json), fire `asset_updated` for archived
  deletion, document in EVENTS.md. (`websocket_api.py:281`)
- [ ] M9. `async_remove_entry` must delete the uploaded-documents tree
  (`<config>/home_keeper/documents/`). (`__init__.py:1042`, `manuals.py`)
- [ ] M10. Panel appliance editor: re-render after metadata/part row deletion and
  stop stale-index closures from corrupting sibling rows (key rows or re-read index
  at event time). (`panel.ts:3986,4084`)
- [ ] M11. Panel robustness: initial-load failure shows error + retry instead of
  infinite spinner; try/catch + toast on `_complete`, `_deleteAsset`,
  `_deleteCompletion`, `_deleteArchivedCompletion`; debounce + serialize
  profile/notification persistence (no per-keystroke entry reloads, no
  out-of-order overwrite). (`panel.ts:843,916,1166,1251,2786,2974`)
- [ ] M12. Panel navigation: `_openEdit`/`_openEditAsset` must navigate via URL
  (route is the single source of truth), not mutate `_view`/`_detail` directly.
  (`panel.ts:867,1114`)
- [ ] M13. Device triggers: don't freeze the task/asset filter at attach time —
  re-resolve per event so late-loading entries and newly attached tasks fire.
  (`device_trigger.py:143`)
- [ ] M14. `add_task`/`delete_task` handlers reload the entry unconditionally —
  apply the same entity-set gate as `update_task` (only reload when per-task
  entities change). (`__init__.py:512,555`)

## Minor bugs

- [ ] N1. Notification "Mark done" action: no-op when the task is no longer
  due/armed (stale tap on a second device must not double-advance).
  (`notifier.py:300`)
- [ ] N2. Usage-meter zero-blip: require a meter-reset reading to persist across two
  consecutive readings before re-baselining. (`sensor_tasks.py:113`)
- [ ] N3. Reject NaN/Infinity in every numeric gate in `models.py` (`cost`,
  `sensor.target`, `sensor.value`, baseline). (`models.py:58,129,149`)
- [ ] N4. `notes: null` must normalize to `""`, not `"None"`. (`models.py:297`)
- [ ] N5. Purged one-off tasks: clean up per-task entities when the coordinator
  purges expired one-offs (reload gate like the service delete path).
  (`coordinator.py:132`)
- [ ] N6. Calendar: fixed occurrences count as active during their event window;
  window queries include events overlapping the window start.
  (`calendar.py:91,128`)
- [ ] N7. Duplicate completion timestamps: make `complete_task` idempotent for an
  identical explicit `completed_at` ts (skip duplicate history entries).
  (`store.py:799`, `recurrence.py:374`)
- [ ] N8. Frontend bucket drift: dormant sensor tasks land in the Monitored bucket
  (panel + card-filter); card hides Done on completed one-offs; panel
  `_statusBucket` gets card-filter's NaN guard; `dueLabel`/`_relativeDay` use
  calendar days, not 24-hour buckets. (`panel.ts:1415,1421`, `card-filter.ts:89`,
  `card.ts:786`, `utils.ts:98`)
- [ ] N9. `strings.json` ↔ `services.yaml` parity: add `register_companion` /
  `list_companions` strings; add missing field strings (`labels`, `card_links`,
  `task_chips`, `source`, completion metadata fields, `dismissed_companions`);
  document schema-only fields (`completion_detail`, `completion_required_fields`,
  `managed_by`, snooze/skip `origin`).
- [ ] N10. Documents: stream GETs via `web.FileResponse` (no 25 MB buffering) and
  write the blob to disk *before* persisting store metadata/firing the event.
  (`manuals.py:151,227`)
- [ ] N11. `testing.py` fake: compute `changed_fields` as a real before/after diff
  like the store. (`testing.py:73`)
- [ ] N12. Feature-module minors: `last_replaced` validation uses injected `now`
  (not naive `date.today()`); enforce the document cap after `_merge_documents`;
  cap companion registry entry sizes/count; drop the dead `declared_type` param
  from `validate_upload`. (`assets.py:437,212`, `companions.py:68`,
  `documents.py:59`)
- [ ] N13. Frontend leaks/races: panel `disconnectedCallback` removes confirm scrim
  + document keydown listener (and `_openConfirmDialog` removes a previous scrim);
  card `_subscribe` unsubscribes if disconnected mid-flight; panel guards duplicate
  initial load; card editor stops refetching profiles on every hass churn.
  (`panel.ts:1006`, `card.ts:398,905`)

## Maintainability

- [ ] R1. Extract services from `__init__.py` into `services.py`: registration
  table (teardown derived from it), exception-translation decorator for the
  copy-pasted `KeyError → task_not_found` blocks, schemas alongside. `__init__.py`
  keeps only entry lifecycle.
- [ ] R2. Shared `_coordinator()` lookup helper (used by `websocket_api.py`,
  `device_trigger.py`, `manuals.py`, `__init__.py`/`services.py`).
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
