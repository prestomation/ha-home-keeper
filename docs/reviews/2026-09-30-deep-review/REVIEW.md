# Home Keeper: deep code review

- **Commit:** `f016cf5` (0.28.0b2), 2026-09-30.
- **Scope:** all backend Python (32,700 lines), all panel and card TypeScript (24,000 lines), CI workflows and `ci/` scripts, and test quality.
- **Method:** parallel finder agents, one for each file group and one for each cross-cutting lens (security, data integrity, async, time zones, contracts, races, CI and more). An independent adversarial verifier then tried to refute each finding, and a second skeptic checked the most severe ones again. Many findings have a reproduction script.
- **Result files:** `RAW_FINDINGS.md` has every finding with evidence, failure scenario, fix, and verifier reason. The `find-*.json` and `verify-*.json` files have the same data as JSON.

Severity is the severity **after** verification. "Confirmed" means that a verifier traced or reproduced the defect. Duplicates found by more than one agent are merged, and the other IDs are shown in brackets.

## Fix first: confirmed high

1. **Non-admin users can read and change private appliance data.** There are two open paths.
   - The document and part-file upload views check only for a signed-in user. Any user can add a document or replace a part file (the old file is deleted). The reply contains the full appliance record: costs, serial numbers, warranty dates, and part vendors. `manuals.py:549` (B06-1, also X01-1, X03-1)
   - `delete_archived_completion` has no admin gate on the websocket command or on the service. It also returns the full appliance record for any asset, even when nothing is deleted. `websocket_api.py:709` (B03-1, also X01-2; the second skeptic rates this path medium, because it needs a crafted call)
2. **Settings: the retention box deletes data while you type.** (Both checks: high.) Each keystroke saves, and each save reloads the entry and runs the purge. Typing "30" first saves "3", which permanently deletes completed one-off tasks older than 3 days. `panel-settings.ts:372`, `coordinator.py:271` (X12-1)
3. **Settings cards send back an old copy of all options.** Each card starts its form from the full options object, and the backend replaces each key it gets. A save in one card reverts earlier saves in the same visit. Example: turn problem sync on, then add an exclusion. The second save turns sync off again, and the reload removes all synced tasks. `panel-settings.ts:372`, `options.py:176` (F03-1)
4. **The split-duplicate merge deletes user tasks on every setup.** (Two checks: high. One verifier: critical.) The merge runs on every setup and reload, also when no device was split. Tasks that share a consumable link (for example 3 smoke-alarm tasks that use one battery part, or a task made with Duplicate) merge into one task. The tasks that have no completions are deleted. `store.py:1306` (B01-1, also B17-1)
5. **Sensor task passes overlap and complete tasks many times.** Evaluation passes are not serialized and read old task data. When 6 devices recover at the same time, the passes record 21 completions, with duplicate events and stock draws. `sensor_watcher.py:497` (B14-2)
6. **An appliance update without `parts` detaches all part files.** This happens on the inline Notes edit, on a rename through the service, and on a partial import. The files stay on disk as orphans. `assets.py:1607` (B05-1)
7. **Import and dry run fail on Home Assistant 2026.8 and older.** (First check: high. Second check: medium, because it fails loudly and writes nothing.) The code reads `.id` from items of `registry.devices`, but on those versions the items are ID strings. It must use `device_compat.all_devices`. No minimum HA version is declared. `transfer_runner.py:71` (B04-1, also B17-3)
8. **A restore of nested appliances onto a new install fails.** The export writes `parent_asset_id` as a UUID, but the planner finds a planned record only by name or `external_id`. Nothing is written. `transfer.py:1022` (B04-2)
9. **To-do list sync puts evening tasks on the next day.** (First check: high. Second check: medium, because only the external list is wrong.) The panel stores times in UTC, and the sync takes the date without a conversion to local time. In US time zones, a due time after about 16:00 local time syncs one day late. `todo_list.py:292` (X04-1, also B10-7)

## Confirmed medium, by theme

### Security and privacy
- Diagnostics do not redact completion notes (the key is `note`, not `notes`), appliance metadata, costs, vendors, part numbers, or document share URLs. `diagnostics.py:28` (B20-1, B20-2, B21-1)
- Home Keeper copies appliance serial numbers to the HA device. Any non-admin user can read them through `config/device_registry/list`, and `SECURITY.md` says that they cannot. `devices.py:461` (X01-5)

### Schedule correctness
- The first panel save of a task that a service made brings back a completed one-off as overdue and cancels a snooze. `merge_update` compares `due` and `anchor` as text, and the panel sends UTC. `models.py:1123` (B08-1)
- An undo on an overdue fixed task drops the overdue occurrence. `recurrence.py:669` (B07-1)
- A delete or move of an older history row calculates `next_due` again. This removes a later skip, snooze or due-today. `recurrence.py:670` (B07-2, B08-4)
- A back-dated completion that is older than the latest one moves `last_completed` and a floating `next_due` back. `recurrence.py:530` (B07-3, B08-3, X04-4)
- Due today (or an early snooze) followed by Done on a fixed task gives back the occurrence that the user just did. `recurrence.py:481` (B07-5, X04-2)
- Floating dates are calculated in the stored offset, not in the HA time zone. They move by 1 hour at a DST change and by 1 day near midnight. `recurrence.py:354` (B07-4, X04-3)
- The calendar ignores `next_due` for fixed tasks. Snoozed, skipped, done-early and due-today tasks show at the wrong time, and calendar triggers fire for them. `calendar.py:91` (X04-5, B11-2)
- The panel never reads the HA time zone. When the browser zone is different, anchors move. `forms.ts:203` (X04-7, F04-6)

### Sync engines and notifications
- When a synced to-do line is deleted, the lookup falls back to last cycle's ticked line with the same text. This completes the task (or restocks the part) although nothing was done. `todo_items.py:84` (B09-1, B10-1, B11-1)
- The shopping mirror can match a new buy reminder to last time's ticked line on CalDAV-like lists. `shopping.py:344` (B09-2)
- Two profiles that hold one task complete it twice in one pass. `todo_list_sync.py:229` (B10-3)
- A move of a profile's sync to a new list stalls forever when the old list is gone. `todo_list.py:444` (B10-2)
- Automatic notifications fire when any task in the home crosses, not only a task in the notification's profile. `notifier.py:311` (B16-1, B18-1)
- A Snooze or Skip tap on an old notification card is not checked against the freshness token, so it can move a completed task. `notifier.py:487` (B16-2, X04-6)
- In a due-soon walk, the task that was just done comes back with new buttons. A second tap completes it again. `notifier.py:529` (B16-5)
- The Snooze button on a blocked task does nothing when "Allow snooze" is off. `notifier.py:494` (B16-3)

### Sensor tasks
- The startup baseline runs before other integrations load. A missing entity is baselined as not met, so tasks that the user already dealt with arm again at each restart. `sensor_watcher.py:373` (B14-1)
- The restored "unavailable" placeholder at startup arms availability tasks. `sensor_watcher.py:174` (B14-4)
- The meter-reset debounce counts passes, not readings, so one glitch can re-base the meter. `sensor_tasks.py:386` (B14-3)
- A crossing that the watcher sees while the task is armed arms the task again right after Done. `sensor_tasks.py:558` (B14-5)
- Each bound-entity change renders all templates on the event loop. `sensor_watcher.py:494` (B14-6)

### Declarative companions
- When a user disables an entity, its device, or its integration, the companion task and all its history are deleted. `declarative_companions.py:413` (B12-1)
- A name template that renders empty stops every reconcile pass, and the next restart fails setup. `declarative_companion_sync.py:355` (B12-2)
- The setup reconcile renders names before the entities have a state. This renames tasks at each restart and causes an extra reload. `declarative_companion_sync.py:153` (B12-3)
- One companion that matches several entities on one device gives identical entity names (the Brother and Dyson presets). `task_entities.py:62` (B15-1)

### Lifecycle and error handling
- Each entry reload removes all `home_keeper.*` services, so automation calls in that window fail. The `quality_scale.yaml` claim for `action-setup` is wrong. `__init__.py:2006` (B02-1, B20-3)
- A very large `one_off_retention_days` value overflows the date math, and the entry then stays in a setup retry loop. Only the options flow has an upper limit. `options.py:147` (B19-1, B21-6)
- Option saves are not queued. A save during the reload that the last save started fails with `not_loaded`. `panel-settings.ts:699` (X12-2)
- A rename of a problem sensor's entity recreates its task, so labels, history and note are lost. `problem_tasks.py:164` (B18-2)
- A delete of a declarative companion does not reload, so its device-page entities stay. `websocket_api.py:1404` (B03-2)
- Import and export parse YAML on the event loop, at several seconds per MB. `websocket_api.py:1174` (B03-3, B04-9)
- `devices.py` uses device-registry APIs that HA 2026.9 deprecates and that HA 2027.8 removes (`async_get_device`, `via_device`, `remove_config_entry_id`). `device_compat.py` wraps none of them. After 2027.8, setup fails for any install with a sub-appliance, and the prune step fails on most installs. `devices.py:463` (X13-1)

### Import and export
- Tasks attach to the wrong appliance when two appliances share a name. `transfer.py:375` (B04-3, X03-4)
- A replay of history moves `last_completed` back, and past the 500-entry cap it drops the newest entries. `transfer.py:1511` (B04-4, X03-3)
- A task with a manual consumable link is left out of the export, with no message. `transfer.py:306` (B09-4)

### Files and stock
- An upload that reuses a document ID overwrites that document's file. `manuals.py:617` (B06-2)
- The trash icon on a document, and Remove on a part file, delete the stored file at once, with no confirmation. The drawer's Cancel does not restore it. `panel-asset-editors.ts:215` (F08-3)
- A failed document add, edit or remove shows its error only in the banner at the bottom of the drawer, which is often off-screen on a phone. The re-render also clears the link that the user typed. `panel-asset-editors.ts:419` (F08-1)
- When a part is removed, its file stays on disk. `store.py:944` (B06-3)
- The delete paths for declarative companions and problem tasks do not archive completion history. `store.py:1812` (B01-4)
- A change of "Last replaced" on a wear part does not move its task. `reconcile.py:674` (B09-3)
- Stock can go above the maximum, and after that every appliance edit fails. `number.py:73` (B15-3)

### Sensor bindings and declarative dialog
- A sensor task stores only the entity ID. When the user renames the source entity, the task stops, with no warning. `sensor_watcher.py:115` (X10-1)
- "Clear on recover" set to off does not survive a reopen of the declarative dialog. A later edit saves it as on. In availability mode, the backend cannot store off at all. `panel-declarative.ts:880`, `models.py:408` (F06-1, F06-2)
- After a task changes type or sensor mode, its old completions and skips can no longer be edited, because the dialog sends back a hidden `reading` that the backend now refuses. Fix this in the store, not in the frontend, or the stored reading is erased. `panel-defer.ts:64` (F10-1)

### CI and release
- The walkthrough-preview and docs-preview jobs run `npm ci` with a write token on Dependabot PRs. One run pushed to `gh-pages` from a Dependabot branch. (X06-4)
- The nightly HA-beta integration job takes 13 minutes against a 15-minute cap. A timeout ends as "cancelled", and `failure()` does not fire on that, so no regression issue is filed. `ha-beta.yml:28` (X06-5)

### Panel and card
- The panel's Done, Skip, Snooze, the completion dialog, and Create/Save accept a second press while the first call runs. `panel.ts:1096`, `panel.ts:934` (X12-3, X12-4)
- An emptied optional sensor field keeps the old value on save. `forms.ts:1079` (F02-2)
- When the user clears the stock box on the appliance page, the stock is set to 0. This can fire the out-of-stock event and make an auto-buy task. `panel-detail.ts:962` (F07-3)
- "Remove orphaned tasks" deletes in bulk with no confirmation. If the loaded-entries call fails, it shows every managed task as orphaned. It also sends one call per task, and each device-attached delete does a full entry reload, so N orphans cause N reloads. `panel-lists.ts:147` (F07-5, X08-1)
- Notes lose single line breaks, because `ha-markdown` is used without `breaks`. `markdown.ts:99` (F04-1)
- The card subscribes to an event that HA refuses for non-admin users, and it tries again on each hass update. Each try writes an ERROR to the log. `card.ts:534` (F09-1, X12-6)
- The card does not show counted wear progress to non-admin users. `assets.py:1763` (F09-2)
- The card's "Due soon" filter never shows a task on the day that it is due, but the panel's Due soon filter does. `card-filter.ts:505` (F05-1)

### Accessibility
- The confirm-delete dialog has no dialog role and no `aria-modal`, and it does not take focus. Tab reaches the page behind it. `panel-dialogs.ts:191` (X11-1)
- The card rebuilds its whole shadow tree on each refresh, also while its create form or Snooze/Skip dialog is open. Focus falls to the page body, and HA hotkeys then get the next keys. `card.ts:587` (X11-3)

### Other confirmed medium
- An unquoted YAML `state: on` in an import is stored as "True", and the sensor task never arms. `models.py:379` (B08-2)
- The 2026.8 device-split repair does not update `related_device_ids`, profile device filters, or problem-sensor exclusions. They keep the dead IDs. `store.py:1261` (X03-8, B17-4)

## Suggested fix order

1. **Close the privilege gaps:** add the admin check to the `manuals.py` upload views and to `delete_archived_completion` (websocket and service). Make diagnostics redact `note`, `metadata` and costs. Stop copying serial numbers to the HA device.
2. **Stop the silent data loss:** debounce or commit-on-blur the retention box, and seed each settings card with only its own keys. Guard the split-duplicate merge so that it runs only when a split happened. Keep part file fields when `parts` is not sent. Serialize sensor-watcher passes.
3. **Make restore work:** use `device_compat.all_devices` in `transfer_runner.py`, resolve `parent_asset_id` by UUID in the planner, and do not move `last_completed` back on a history replay.
4. **Fix the schedule cluster:** most of the recurrence findings (B07-1, B07-2, B07-3, B07-5, B08-1, X04-5) come from 2 roots. `next_due` is calculated again from history alone, and times are compared as text or in the stored offset, not in the HA time zone. One design pass can fix these together.

## Coverage and limits

- **Agents:** 43 finder slices (21 backend file groups, 10 frontend file groups, 12 cross-cutting lenses), 29 verifiers, and 2 second-opinion skeptics. That is 74 subagents in total.
- **Totals:** 308 raw findings. After verification and the merge of duplicates: 1 critical, 9 high, 66 medium and 156 low confirmed; 21 plausible; 45 duplicates merged; 10 refuted. The one critical is the split-duplicate merge (item 4 above). Two other checks rated it high.
- **Refuted examples:** the day-31 monthly clamp to the 28th is intended (B07-6). `register_companion` is open to any user by design (X01-6). A meter reset is documented to re-anchor (B14-7). The full list with reasons is in `RAW_FINDINGS.md`.
- **Severity disputes:** where the two checks disagree, both ratings are shown above. The `RAW_FINDINGS.md` file shows the first verifier's rating and the second opinion.
- **Not run:** Docker, e2e, walkthrough, and mutation suites. Home Assistant was not installed in the container. Where a verdict needed HA behavior, the verifiers read the HA 2026.9.4 source. The pure modules were reproduced with scripts (see the `tmp-*` folders next to this file). Browser-only behavior, such as how `ha-form` sends events and how Escape moves through nested dialogs, was traced in source code, not run in a browser.
- **Not reviewed:** the `website/` Docusaurus site, the prose quality of `docs/guide/`, and translation quality beyond key and placeholder parity.
- **Repository:** no file in the repository was changed. All output is in this folder.
