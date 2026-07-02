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

- [ ] C1. Naive `completed_at` corrupts the store: qualify naive datetimes at the
  `store.complete_task` boundary (mirror `models._coerce_seed`), same for
  `update_completion` ts edits. Regression test with a naive datetime through the
  service schema path. (`store.py:800`, `__init__.py:193`)
- [ ] C2. Unavailable/unknown problem-sensor state must be "skip", not "cleared":
  treat `unavailable`/`unknown`/missing states as indeterminate in
  `problem_sync._is_problem` → reconcile leaves armed tasks alone. Regression test:
  armed task + unavailable sensor → no completion fired. (`problem_sync.py:160`,
  `problem_tasks.py:177`)

## Security

- [ ] S1. Stored XSS via completion `photo`: add a shared `safeHref()` (http(s)-only)
  in the frontend and use it for the history photo link/thumbnail; validate the
  scheme server-side in `models.normalize_completion_metadata` too. Extend to the
  other unguarded href sinks (panel `task_chips.url`, document links, metadata
  links, card `task_chips`) for defence-in-depth. (`panel.ts:4274`, `models.py:65`)
- [ ] S2. Admin-gate the sensitive websocket commands: `require_admin` on
  `home_keeper/set_options` and `home_keeper/export_inventory`.
  (`websocket_api.py`)
- [ ] S3. Redact sensitive fields in diagnostics (`serial_number`, completion `who`)
  via `async_redact_data`. (`diagnostics.py`)

## Major bugs

- [ ] M1. `merge_update` recomputes `next_due` on recurrence-key *presence*; only
  recompute when a recurrence key's value actually changed. Regression tests: panel
  edit payload on a completed one-off (stays dormant) and on a snoozed task (snooze
  survives). (`models.py:610`)
- [ ] M2. Reserved `source` namespaces: validate `source.part` / and reject malformed
  reserved shapes in `models.build_task` (service `add_task` path); make
  `reconcile.py` use `.get()` so malformed stored data can't brick setup.
  (`reconcile.py:121,220`, `models.py:477`)
- [ ] M3. Transition edge-state must survive config-entry reloads: persist the
  fired-flags map across coordinator recreation (hand off via `hass.data` keyed
  storage that outlives the entry reload) so add/delete task no longer swallows
  overdue/due-soon events. Regression test. (`transitions.py`, `coordinator.py`)
- [ ] M4. Unload teardown is dead code: gate on `async_loaded_entries()` so panel +
  services are removed when the last entry unloads; make `_coordinator()` raise a
  localized `ServiceValidationError` instead of bare `RuntimeError`.
  (`__init__.py:1035,486`)
- [ ] M5. Pass `config_entry=entry` to `DataUpdateCoordinator.__init__` (2025.11
  removal of implicit inference); collapse `self.entry` duality.
  (`coordinator.py:68`)
- [ ] M6. Add `serial_number` to `_ASSET_FIELDS` so `add_asset`/`update_asset`
  services accept it. (`__init__.py:268`)
- [ ] M7. To-do item rename support: apply summary changes via `store.update_task`
  in `async_update_todo_item`. (`todo.py:82`)
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
