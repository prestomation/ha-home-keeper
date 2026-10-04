---
title: Profiles and notifications
summary: Saved task filters (profiles) and the actionable phone notifications that deliver them.
implements:
  - custom_components/home_keeper/profiles.py
  - custom_components/home_keeper/notifications.py
  - custom_components/home_keeper/notifier.py
  - custom_components/home_keeper/frontend/src/panel-settings.ts
  - custom_components/home_keeper/frontend/src/card-filter.ts
  - custom_components/home_keeper/frontend/src/group-editor.ts
related: [coordinator-entities, events-api, sync, companions-presets, frontend]
source_hash: ce4094582243
---

# Profiles and notifications

A profile is a saved filter that answers "which tasks". A notification sends the tasks of
1 profile to phones, with buttons that act on the task. The panel list, the card,
notifications and to-do list sync all read the same profile.

## Goals

- **G1. One filter, one meaning.** A profile selects the same tasks in Python and TS.
- **G2. Act from the phone.** Done, Snooze and Skip buttons change the task, and a walk
  then sends the next task in the queue.
- **G3. No double action.** A tap on an old card or a twin card does not act again.
- **G4. Per-person delivery.** Each person gets only the tasks for that person.
- **G5. Localized text.** Payload text uses the Home Assistant language and plurals.

## Non-goals

- No built-in send time. An automation calls `home_keeper.notify` at the time it wants.
  The only automatic send is the overdue or due-soon transition trigger.
- No target other than `mobile_app_*` and `persistent_notification` ([SECURITY.md](../SECURITY.md)).
- The to-do list sync engine reads the profile `sync` block. It is in the `sync` doc.

## Design

### Profile model (`profiles.py`)

A profile is `{id, name, filter, sync}`; a filter is `{status, groups}`. The fixed key
set of `profiles.normalize_filter` is the allowlist of a group: `name` (display only),
`labels`, `labels_match` (`any`/`all`), `areas`, `devices`, `companions`, 4 `exclude_*`
lists and `exclude_shopping`. `status` is `all`, `overdue` (default) or `due_soon`.
`normalize_profile` gives a stable hex `id`; `resolve_profile` finds by id, then name.

In `profiles.matches_filter`, a task must be enabled and have a `next_due`. `overdue` is
due now or earlier; `due_soon` adds the 3-day `transitions.DUE_SOON_WINDOW`. Then the
task must match 1 active group. A group with no value is not active; with no active group,
every task in the tier matches. In a group, include lists are AND; an empty list is "any".
`labels` is OR, or AND if `labels_match` is `all`. Exclude lists win in their group only.
`companions` matches `profiles.companion_keys`: the owner domain, or a narrower key for a
declarative companion or a problem-sensor task. `exclude_shopping` drops buy reminders by
kind. `due_queue` sorts by `next_due`, then name.

`migrate_options_v1` moves v1 flat keys into 1 group (entry version 2); `set_options`
refuses them. `liftLegacyCardConfig` lifts a card's flat keys. `group-editor.ts` draws groups.

### Effective ids and the TypeScript twin (`card-filter.ts`)

A task inherits labels from its device and its area, and an area from its device.
`profileMatches` in `card-filter.ts` resolves these inline with `taskLabelIds` and
`taskAreaId`. `notifier.effective_filter_tasks` writes the same effective ids onto task
copies before the pure matcher runs. `DUE_SOON_DAYS` (3) mirrors the backend window and
is different from the card's 7-day `soon` section. `tests/fixtures/profile_filter_cases.json`
holds the shared cases. The card `profile` setting and the active profile in
`panel-lists.ts` use `profileMatches` in place of their own filters.

### Notification model (`notifications.py`)

`notifications.normalize_notification` gives the stored shape: `id`, `name`,
`profile_id`, `targets`, `actions` (ordered, from `complete`/`snooze`/`skip`/`open`),
`snooze_hours`, `style` (`walk` or `digest`), `channel`, `urgency`, `icon`, `color` and
`auto` (`{overdue, due_soon}`). A `None` `profile_id` covers every overdue task; one that
no longer resolves sends nothing. `notifications.split_targets` drops a target that is
not allowed when the value is stored. Per-person delivery is 1 notification for each
person: a profile for that person's tasks and the `mobile_app_*` service of the phone.

### Send and walk (`notifier.py`)

Three paths send. `notifier.async_run_notify` serves `home_keeper.notify`: a saved
notification or profile, with optional `target`, `status` and `when_empty`. It applies
`status` with `profiles.with_status` on a copy; only this path accepts `none`, which
selects no task. `notifier.async_send_auto` gets the crossings of each refresh from
`transitions.auto_crossings`, and sends a notification 1 time if a crossed task passes its
profile. The action listener advances a walk after each tap.

A walk sends only the head of the queue and keeps no cursor: Done, Snooze and Skip each
move the task out of the queue. The advance sends with `when_empty: all_clear`, so an
empty queue closes with an "All caught up" card. It also keeps the changed task out,
because under `due_soon` or `all` that task can still match. A digest is 1 card with up to
5 task names. `notifications.notification_tag` gives 1 stable tag per notification, so a
new card replaces the old card. A send with no saved notification, or other targets, gets
a `notifications.route_id`, which `notifications.resolve_tap_notification` reads on a tap.

### Buttons and the stale-tap guard

A button action is `home_keeper::<verb>::<task_id>::<notification_id>::<due_token>`.
`notifications.due_token` is the task's `next_due` at send time. On a tap,
`notifier.async_setup_notifications` decodes the action with `notifications.decode_action`
and calls `notifications.is_current_action`. A different `next_due` means the task moved
after the send, so the tap does nothing. No `await` comes between the check and the store
change, so 2 taps at once cannot both pass. A tokenless 4-field action accepts Snooze and
Skip, and Done only on an overdue task.

`notifications.actions_for` removes a verb that the `allow_snooze` or `allow_skip`
option turns off. It removes Done and Skip for a completion-blocked task, and Done for a
task that needs a tag scan. If no verb that advances the walk is left, it adds Snooze
before the other buttons, also when `allow_snooze` is off. Snooze length is the task's
own `snooze_hours`, else the notification's (`notifications.snooze_hours_for`).

### Payload text and look

`notifications.payload_data` builds every `data` block. It expands `channel` and
`urgency` into the Android and iOS keys and adds `icon` and `color`; `normal` adds no
keys. Text comes from flat files in `notification_strings/`, 1 for each locale.
`notifications._t` tries each language of `backend_i18n.language_chain`, and
`notifications._tn` picks the Babel CLDR plural form. Babel reads files on first use, so
`notifier` builds payloads in the executor.

### Where settings live

`profiles`, `notifications`, `allow_snooze` and `allow_skip` are config entry options,
normalized on each read by `options.current_options`. The Settings tab
(`panel-settings.ts`) edits both lists through `set_options`. Its Test button sends
`status: all` with `when_empty: all_clear`, so a card always arrives. A second button
sends `status: none` for the all-clear card, and `profileHasAnyTask` decides which of the
2 cards is the other one. `options.profile_removals_in_use` refuses a save that deletes a
profile that a remaining notification uses.

## Trade-offs

- **Stateless walk** over **a stored cursor**: no queue to store or repair. Under status
  `all`, a snoozed task can come back later in the same walk.
- **Effective ids on a backend copy** over **registry reads in the matcher**: it stays pure.
- **The `next_due` token** over **a stored state record**: no storage, and twin cards
  block each other.
- **A separate string tree** over **`strings.json`**: hassfest refuses unknown keys there.
- **Forced Snooze on a blocked task** over **obeying the button set**: a walk with no
  verb that advances it sends the same task each time.

## One-way doors

- Stored shapes: the profile and its filter keys, the notification keys above, and the
  `status`, `style`, `urgency` and verb values.
- The action string and the `home_keeper_<notification_id>` tag. Old buttons stay on
  phones, so the 4-field action still decodes.
- `home_keeper.notify` fields (`notification`, `profile`, `target`, `status`,
  `when_empty`) and its `{matched, sent}` response.
- The `notification_strings/<lang>.json` key names.
