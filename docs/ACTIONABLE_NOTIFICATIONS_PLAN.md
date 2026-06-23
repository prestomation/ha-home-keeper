# Actionable Notifications (mobile push with Mark-done / Snooze / Skip)

**Status: proposed.** This plan adds a **built-in notification sender** so Home
Keeper can push a mobile-app **actionable notification** when a task becomes
overdue (and, optionally, due-soon) — with tappable action buttons (**Mark done**,
**Snooze**, **Skip occurrence**, **Open in Home Keeper**) that route straight back
into the integration. Because the callback lands inside Home Keeper, the action
**recalculates the schedule correctly** — completing advances recurrence, snoozing
re-arms a fresh reminder — which is precisely the gap the popular
[*Actionable Task Reminder* blueprint](https://community.home-assistant.io/t/actionable-task-reminder-a-powerful-task-reminder-automation/636946)
can't close (it knows nothing about intervals). See `IDEAS.md` →
"Actionable (snoozable) notifications".

The feature is **opt-in and configured two ways that share one options object**:
the Home Assistant **options flow** and a new **Settings → Notifications** card in
the panel (the same dual-surface pattern the problem-sensor sync already uses — see
`options.py`). The **button set is user-configurable**.

---

## 1. What already exists (and what this reuses)

- **Edge-triggered overdue / due-soon transitions.** `transitions.detect_transitions`
  (driven from `coordinator._async_update_data`) already fires
  `home_keeper_task_overdue` / `home_keeper_task_due_soon` **once per `next_due`
  value**, silently baselined on startup so a restart never replays a storm
  (`docs/EVENTS.md` → "Time-based transitions"). The notification sender hooks the
  **same chokepoint**: when a transition fires and notifications are enabled for that
  kind, build and send the push. No new scheduling machinery.
- **Completion chokepoint.** `store.complete_task()` is the single mutation that
  advances recurrence, stamps history, resets sensor baselines, consumes spare
  stock, and fires `home_keeper_task_completed` with an `origin` echo
  (`custom_components/home_keeper/store.py`). The **Mark done** action just calls it
  with `origin="home_keeper_notification_action"` (loop-safe, like the
  problem-sensor sync's `ORIGIN_PROBLEM_SENSOR_SYNC`).
- **Shared options object + dual edit surfaces.** `options.py`
  (`current_options` / `async_set_options`) is the single source of truth edited by
  the **options flow** (`config_flow.HomeKeeperOptionsFlow`), the
  **`home_keeper.set_options` service**, and the **panel** (over the
  `home_keeper/get_options` + `home_keeper/set_options` websocket commands, rendered
  as autosaving `ha-form` cards in `panel.ts` `_renderSettingsForm`). New
  notification settings slot straight in — add keys/defaults/normalization in
  `options.py`, a schema branch in `config_flow.py`, and a card in `panel.ts`.
- **Service-first + event-for-every-state-change conventions.** Per `AGENTS.md` /
  `.amazonq/rules/`, the new mutations (**snooze**, **skip**) ship as
  `home_keeper.*` services (with `services.yaml` + `strings.json` parity) that the
  notification-action handler *delegates to*, each firing a
  `home_keeper_<noun>_<verb>` event documented in `docs/EVENTS.md` and surfaced in
  `device_trigger.py`.
- **Pure / HA-aware split.** Like `events.py` (pure payload builders) and
  `recurrence.py` (pure engine taking explicit `now`), the notification **payload
  builder** and the **action decoder** are pure and unit-testable; only the
  sender/listener touch HA.

---

## 2. Product shape

### 2a. What the user gets

When a task crosses overdue (and/or enters the due-soon window), every configured
mobile target receives a push like:

> **Home Keeper — Replace furnace filter**
> Overdue by 2 days.
> [ Mark done ] [ Snooze 1 day ] [ Open ]

- **Mark done** → completes the task (advances recurrence), clears the notification.
- **Snooze** → pushes `next_due` forward by the configured amount **without**
  recording a completion or advancing recurrence; a fresh reminder fires when the
  snooze expires (the edge state re-arms because `next_due` changed).
- **Skip occurrence** → advances to the next scheduled occurrence **without**
  recording a completion (useful for a fixed schedule you're deliberately missing).
- **Open in Home Keeper** → deep-links to the task's panel detail page
  (`/home-keeper/...`); a client-side URI action, no backend callback.

### 2b. Configurability (the answer to "configurable button set")

All settings live on the config entry's `options` (defaults keep the feature
**off**, so existing installs are unchanged):

| Option key (`const.py`) | Type | Default | Meaning |
|---|---|---|---|
| `OPTION_NOTIFY_ENABLED` | bool | `False` | Master switch for the built-in sender. |
| `OPTION_NOTIFY_TARGETS` | `list[str]` | `[]` | `notify.mobile_app_*` service names to push to. |
| `OPTION_NOTIFY_ON_OVERDUE` | bool | `True` | Send when a task becomes overdue. |
| `OPTION_NOTIFY_ON_DUE_SOON` | bool | `False` | Send when a task enters the due-soon window. |
| `OPTION_NOTIFY_ACTIONS` | `list[str]` | `["complete","snooze","open"]` | **Which buttons appear**, ordered. Members: `complete`, `snooze`, `skip`, `open`. |
| `OPTION_NOTIFY_SNOOZE_HOURS` | int | `24` | Snooze duration for the **Snooze** button. |

Notes:
- The action list is clamped to the platform's button cap (iOS shows ~3–4; Android
  more). Document the iOS limit; truncate gracefully.
- **Targeting:** mobile actionable notifications require the legacy
  `notify.mobile_app_<device>` service (the `data.actions` payload isn't supported by
  the newer `notify.send_message` entity API), so we store **service names**. The
  backend enumerates available targets via
  `hass.services.async_services().get("notify", {})` filtered to `mobile_app_*` and
  returns them from `get_options` so the panel can render a checklist; the options
  flow builds a `SelectSelector` from the same live list.

Per-task overrides (e.g. "never notify for this chore") are **out of scope for v1**
— see §8.

---

## 3. Backend changes

### 3a. New store mutations — `snooze_task` and `skip_task`

In `store.py`, mirroring `complete_task`'s shape (validate → mutate dict → `_save`
→ fire event), and **rejecting synced problem-sensor tasks** via the existing
`_reject_synced_problem` guard:

- **`snooze_task(task_id, *, by=None, until=None, origin=None)`** — sets
  `next_due = until` or `now + by` (default `OPTION_NOTIFY_SNOOZE_HOURS`), leaving
  `last_completed`, `completions`, `anchor`, and recurrence config untouched. Fires
  `EVENT_TASK_SNOOZED` with the task spine plus `snoozed_until`. Because `next_due`
  changed, the coordinator's edge state re-arms and a new overdue/due-soon fires when
  the snooze lapses — no separate timer needed.
- **`skip_task(task_id, *, origin=None)`** — advances to the **next** occurrence
  without recording a completion. Add a pure `recurrence.skip_occurrence(task, now)`
  next to `apply_completion`: for `fixed` it walks the schedule forward past `now`;
  for `floating` it sets `next_due = now + interval·unit`; for `one-off` it goes
  dormant (`next_due = None`). Fires `EVENT_TASK_SKIPPED`.

**Risk to verify during implementation:** confirm nothing recomputes/clobbers a
fixed task's `next_due` on load/normalize (snooze writes a transient override that
must survive until the next completion). Trace `recurrence.compute_next_due`
call-sites in `models.normalize_*` / coordinator refresh and add a regression test.

New constants in `const.py`:
`EVENT_TASK_SNOOZED = f"{DOMAIN}_task_snoozed"`,
`EVENT_TASK_SKIPPED = f"{DOMAIN}_task_skipped"`,
`ORIGIN_NOTIFICATION_ACTION = f"{DOMAIN}_notification_action"`, and the six
`OPTION_NOTIFY_*` keys.

### 3b. New services — `snooze_task`, `skip_task`

Per the service-first convention: schemas + handlers in `__init__.py`, registered
and added to `_SERVICES`; `services.yaml` + `strings.json` parity. Websocket
commands are optional UI sugar and not required for v1 (the panel doesn't yet expose
snooze/skip buttons — see §4), but if added they **delegate to the same store
methods**.

### 3c. Notification payload builder — `notifications.py` (pure)

`build_notification(task, *, kind, actions, snooze_hours, now) -> dict` returns the
`notify` service `data` payload:

- `title` / `message` from the task name + overdue/due-soon framing (localized).
- `data.tag = f"home_keeper_{task_id}"` — a **stable tag** so a re-notification
  replaces the prior one and so we can **clear** it on completion.
- `data.actions` built from the configured, ordered `actions` list. Each action's
  identifier **encodes the verb and task id**:
  `f"HOME_KEEPER::{verb}::{task_id}"` (the action string is the only field reliably
  echoed back in `mobile_app_notification_action`). The **open** action instead
  carries a `uri` to the panel detail page.
- `data.group` so a household's notifications stack sensibly.

Pure and HA-free → unit-tested in `tests/unit`.

### 3d. Sender — hooked into the coordinator

Where `coordinator._async_update_data` fires the transition events (and only when
`_events_enabled`, preserving startup baselining), also: if `OPTION_NOTIFY_ENABLED`
and the kind is enabled, for each fired `overdue`/`due_soon` event call each
configured `notify.mobile_app_*` target with `build_notification(...)`. Sends are
best-effort (`try/except`, log at debug) so a missing/renamed target never breaks the
refresh loop.

### 3e. Action listener — `notification_actions.py`

Registered in `async_setup_entry` (cleanup via `entry.async_on_unload`), subscribes
to the `mobile_app_notification_action` event:

1. Pure `decode_action(action_str) -> (verb, task_id) | None`.
2. Dispatch on `verb`: `complete → store.complete_task`,
   `snooze → store.snooze_task`, `skip → store.skip_task` — each with
   `origin=ORIGIN_NOTIFICATION_ACTION`; `open` is handled client-side (no event).
3. **Clear the notification**: call the originating target with
   `{"message": "clear_notification", "data": {"tag": f"home_keeper_{task_id}"}}`.
4. `await coordinator.async_request_refresh()` so entities/panel reflect the change.

Unknown/foreign actions are ignored (the global event bus carries other
integrations' actions too — the `HOME_KEEPER::` prefix scopes ours).

### 3f. Device triggers + event docs

Add `task_snoozed` / `task_skipped` to `device_trigger.py` `TASK_TRIGGERS` with
translation-parity labels, and document both events in `docs/EVENTS.md` (catalog row
+ note that they ride the task spine; `task_snoozed` adds `snoozed_until`). Per
`AGENTS.md`, an event isn't done until it's in `EVENTS.md` and `device_trigger.py`.

---

## 4. Frontend — Settings → Notifications card

In `panel.ts` `_renderSettingsForm`, add a third autosaving `_settingsCard`
("Notifications") above/below the existing problem-sync and General cards, driven by
a new `notificationsSchema()` in `forms.ts`:

- A master **enabled** boolean.
- A **targets** multi-select (`ha-form` select) populated from the available
  `mobile_app_*` notify services returned by `get_options` (extend its websocket
  response + `HomeKeeperOptions` type to carry `notify_available_targets`).
- **On overdue** / **On due soon** booleans.
- An **actions** multi-select (`complete` / `snooze` / `skip` / `open`).
- A **snooze hours** number box.

Reuses the existing autosave path (`_saveOptions → api.setOptions`), so no new
client plumbing beyond the schema, the i18n keys (`locales/*`), and the type. The
backend `options.py` (`current_options` / `_normalize` / `_LIST_OPTIONS`) and
`config_flow.py` schema gain the same six keys with matching coercion (booleans,
the int, and the two string lists).

> **UI gate (AGENTS.md):** this adds a new panel surface, so the PR **must** embed a
> current Playwright screenshot of the Settings → Notifications card
> (`tests/e2e/screenshots.capture.ts` → `docs/images/`), and a capture step for it is
> added in the same PR. README gets a feature section with use-cases + screenshot.

---

## 5. Testing

- **Unit (`tests/unit`, pure):** `build_notification` (titles, tag, action encoding,
  action-set ordering/clamping, open-URI); `decode_action` (valid / foreign /
  malformed); `recurrence.skip_occurrence` (fixed walk-forward across `now`, floating,
  one-off → dormant); `snooze_task`/`skip_task` recurrence math; the fixed-schedule
  **no-clobber** regression from §3a.
- **Integration (`tests/integration`):** firing a synthetic
  `mobile_app_notification_action` drives `complete`/`snooze`/`skip` through the
  store and emits the right events with the right `origin`; problem-sensor tasks
  reject snooze/skip; sender calls the configured `notify` service when a transition
  fires (and not when disabled).
- **E2E (`tests/e2e`):** screenshot capture of the new Settings card.

---

## 6. Docs & changelog

- `docs/EVENTS.md` — `home_keeper_task_snoozed` / `_skipped` rows + payload notes.
- `docs/INTEGRATING.md` — a short note that the actions reuse `complete_task` /
  the new snooze/skip services with the `home_keeper_notification_action` origin.
- `README.md` — a **Notifications** feature section (use-case + how to configure +
  screenshot), since it's a headline feature (`AGENTS.md`).
- `services.yaml` + `strings.json` — the two new services and the new options-flow
  fields (localization parity).
- `CHANGELOG.md` — user-facing **Added** entry.
- `.amazonq/rules/` — if any new convention emerges (e.g. the action-string
  encoding scheme), record it.

---

## 7. Implementation order (incremental, each independently testable)

1. **Snooze/skip core:** `const.py` events/origin, `recurrence.skip_occurrence`,
   `store.snooze_task`/`skip_task`, services + YAML/strings, `EVENTS.md`,
   `device_trigger.py`, unit/integration tests. *(No notifications yet — usable via
   service/automation.)*
2. **Options:** the six `OPTION_NOTIFY_*` keys in `const.py` / `options.py` /
   `config_flow.py`, `get_options` target enumeration.
3. **Sender + builder:** `notifications.py` + coordinator hook + unit tests.
4. **Action listener:** `notification_actions.py` + setup wiring + integration tests.
5. **Panel:** Settings → Notifications card, i18n, types; e2e screenshot; README.
6. Amazon Q (Cue) review after each push per `AGENTS.md`.

---

## 8. Deferred / future

- **Per-task notification overrides** (mute a chore, per-task targets/snooze).
- **Repeat reminders / escalation** ("re-nudge every N hours until done", escalate to
  another target). The edge model already gives one reminder per `next_due` and a
  fresh one after snooze; recurring nags are a separate feature.
- **Assignee-aware routing** (notify the person a chore is assigned to) — depends on
  the not-yet-built assignees feature (`IDEAS.md`).
- **A shipped blueprint** as a power-user alternative to the built-in sender (the
  snooze/skip services + action listener built here are exactly what such a blueprint
  would need, so it's purely additive later).
- **Persistent (non-mobile) notifications** via `persistent_notification` for users
  without the companion app.
