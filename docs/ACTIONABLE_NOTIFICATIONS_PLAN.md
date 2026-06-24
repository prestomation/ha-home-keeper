# Actionable Notifications (per-person chore queues via mobile push)

**Status: proposed.** This plan adds **built-in actionable notifications** so Home
Keeper can push a mobile-app notification — with tappable buttons (**Mark done**,
**Snooze**, **Skip occurrence**, **Open in Home Keeper**) that route straight back
into the integration. Because the callback lands inside Home Keeper, the action
**recalculates the schedule correctly** — completing advances recurrence, snoozing
re-arms a fresh reminder — which is precisely the gap the popular
[*Actionable Task Reminder* blueprint](https://community.home-assistant.io/t/actionable-task-reminder-a-powerful-task-reminder-automation/636946)
can't close (it knows nothing about intervals). See `IDEAS.md` →
"Actionable (snoozable) notifications".

The design centres on two things:

1. **Notification profiles** — named, filtered configs ("Me", "Wife"), each with its
   own targets, **label/area filters**, button set, and snooze duration. Multiple
   household members each get *their own* chore list.
2. **A pull-based "walk"** — an automation calls a Home Keeper **service** (e.g. from
   a "Chores" calendar event) to ask *"what's due for this profile right now?"* HK
   sends the **first** matching task; when the user actions it, the **next** one
   arrives — a guided sweep through the queue, one notification at a time.

The automatic "send the moment a task goes overdue" sender is just **one trigger
source** feeding the same profiles. The whole feature is **opt-in** (no profiles =
nothing happens) and configured two ways that share one stored object: the Home
Assistant **options flow** and a new **Settings → Notifications** card in the panel
(the dual-surface pattern problem-sensor sync already uses — see `options.py`).

---

## 1. What already exists (and what this reuses)

- **Edge-triggered overdue / due-soon transitions.** `transitions.detect_transitions`
  (driven from `coordinator._async_update_data`) already fires
  `home_keeper_task_overdue` / `_due_soon` **once per `next_due` value**, baselined
  silently on startup (`docs/EVENTS.md`). The *automatic* trigger source hooks this
  chokepoint; the *on-demand* service is independent of it.
- **Completion chokepoint + origin echo.** `store.complete_task()` is the single
  mutation that advances recurrence, stamps history, resets sensor baselines, consumes
  stock, and fires `home_keeper_task_completed` with an `origin` echo. The **Mark
  done** action calls it with `origin="home_keeper_notification_action"` — loop-safe,
  like the problem-sensor sync's `ORIGIN_PROBLEM_SENSOR_SYNC`.
- **Task filtering by label/area/device already exists in the panel.** The dashboard
  card and list view filter tasks by HA label (the task spine carries `labels`), area,
  and device. Profile filters reuse the **same predicate** — factor it into a pure
  `tasks.matches_filter(task, filt)` so the panel, the card, and the notifier share
  one definition of "this task belongs to this list".
- **Shared options object + dual edit surfaces.** `options.py`
  (`current_options` / `async_set_options`) is edited by the options flow, the
  `set_options` service, and the panel (over `home_keeper/get_options` +
  `home_keeper/set_options`, rendered as autosaving `ha-form` cards in `panel.ts`
  `_renderSettingsForm`). The **profile list** lives here.
- **List-shaped CRUD + service-first conventions.** Tasks/assets already model
  list-shaped user data with CRUD services + websocket commands and a
  `home_keeper_<noun>_<verb>` event per change. Profiles and the new **snooze/skip**
  mutations follow the same mould.
- **Pure / HA-aware split.** Payload **builder**, **action decoder**, **filter
  predicate**, and **queue/next-due selection** are pure and unit-testable (like
  `events.py` / `recurrence.py`); only the sender/listener touch HA.

---

## 2. Product shape

### 2a. Use cases

- **"What's due when I want to know."** A calendar event *Chores* (or a time
  trigger, or an NFC tag, or a dashboard button) → automation → `home_keeper.notify`
  targeting my profile → my phone buzzes with the first due chore. I tap **Done**, the
  next one appears. I sweep my list in a couple of taps, and the schedule advances
  correctly behind each tap.
- **Per-person lists.** Two profiles, "Me" (label `mine`) and "Wife" (label `hers`),
  each targeting that person's phone. One shared automation fans out — each person
  walks only *their* chores. (Pairs naturally with the future **assignees** feature:
  swap the label filter for an assignee filter later.)
- **Automatic nudge.** A profile can also fire **automatically** when a matching task
  goes overdue/due-soon — the original "don't make me ask" behaviour — without an
  automation.

### 2b. Notification profiles

A profile is a dict stored in `options[OPTION_NOTIFY_PROFILES]` (a list). Defaults:
**no profiles**, so existing installs are unchanged.

| Field | Type | Meaning |
|---|---|---|
| `id` | str | Stable id (survives rename); action strings reference it. |
| `name` | str | Display name ("Me", "Wife", "Kitchen"). |
| `targets` | `list[str]` | `notify.mobile_app_*` services to push to. |
| `filter` | dict | `{labels, areas, devices, status}` — which tasks belong to this list. `status` ∈ `all` / `overdue` / `due_soon` (default `overdue`). Empty filter = everything. |
| `actions` | `list[str]` | **Ordered button set**: members of `complete` / `snooze` / `skip` / `open`. |
| `snooze_hours` | int | Snooze duration for this profile's **Snooze** button (default 24). |
| `style` | str | `walk` (one at a time, advances on action — default) / `digest` (single summary push) / `separate` (one push per task). |
| `auto` | dict | Automatic triggering: `{overdue: bool, due_soon: bool}` (both default `false` — profile is on-demand unless opted in). |
| `quiet_hours` | dict\|null | Optional `{start, end}`; suppress *automatic* sends in this window (on-demand always sends). |

Notes:
- **Targeting** uses the legacy `notify.mobile_app_<device>` service (the newer
  `notify.send_message` entity API doesn't carry the `data.actions` payload
  actionable notifications need), so we store **service names**. The backend
  enumerates available `mobile_app_*` targets via `hass.services.async_services()`
  and returns them from `get_options` so the panel renders a checklist; the options
  flow builds its `SelectSelector` from the same live list.
- **Button cap.** iOS shows ~3–4 actions, Android more — clamp `actions` gracefully
  and document it.

### 2c. The "walk" (pull, one-at-a-time) — and why it needs no stored cursor

When `style: walk`, sending computes the profile's **due queue** — tasks matching
`filter`, sorted **most-overdue-first** (then by `next_due`, then name) — and pushes a
notification for **just the first**. The action buttons carry the profile id:
`HOME_KEEPER::{verb}::{task_id}::{profile_id}`.

On any action (`complete` / `snooze` / `skip`), the listener applies the mutation and
then **re-sends the profile's first remaining due task**. This is **stateless**: all
three actions remove the task from the *due* set —

- `complete` → recurrence advances, `next_due` moves to the future,
- `snooze` → `next_due` pushed out,
- `skip` → advances to the next occurrence,

— so simply "recompute the due queue and send its head" naturally advances the walk.
No queue snapshot to persist or invalidate; concurrent edits, a task completed
elsewhere, or a new overdue task all just fall out of the next recomputation. When the
queue is empty, send a localized **"All caught up 🎉"** closing notification (or clear,
per a profile flag).

> Trade-off vs. a stored ordered cursor: the stateless walk can re-surface a task the
> user *snoozed for 1h* if they keep walking within that hour only if the profile's
> `status` is `all` — under the default `overdue`/`due_soon` status the snoozed task is
> out of window and won't reappear. Documented; acceptable for v1.

### 2d. The `notify` service

`home_keeper.notify` — the on-demand entry point:

| Field | Notes |
|---|---|
| `profile` | Name/id of a saved profile (uses its targets/filter/actions/style). |
| *inline overrides* | `target`, `labels`, `areas`, `devices`, `status`, `actions`, `snooze_hours`, `style` — for ad-hoc sends without a saved profile, or to override one. |
| `max` | Cap tasks considered (default unbounded; `walk` always sends 1 at a time regardless). |

`supports_response: optional` → returns `{matched: N, sent: <task_id|null>}` so an
automation can branch ("nothing due → say so on a speaker"). Calling with a `digest`
profile sends one summary listing the matched tasks; `separate` sends one push each.

---

## 3. Backend changes

### 3a. New store mutations — `snooze_task` / `skip_task`

In `store.py`, mirroring `complete_task` (validate → mutate → `_save` → fire event),
**rejecting synced problem-sensor tasks** via `_reject_synced_problem`:

- **`snooze_task(task_id, *, by=None, until=None, origin=None)`** — sets
  `next_due = until` or `now + by` (default the profile's `snooze_hours`), leaving
  `last_completed`, `completions`, `anchor`, recurrence config untouched. Fires
  `EVENT_TASK_SNOOZED` (spine + `snoozed_until`). The changed `next_due` re-arms the
  coordinator edge state so a fresh overdue/due-soon fires when the snooze lapses.
- **`skip_task(task_id, *, origin=None)`** — advances to the **next** occurrence with
  no completion recorded, via a new pure `recurrence.skip_occurrence(task, now)`:
  `fixed` walks the schedule forward past `now`; `floating` → `now + interval·unit`;
  `one-off` → dormant; `triggered`/`sensor` → dormant (clears the arm). Fires
  `EVENT_TASK_SKIPPED`.

**Risk to verify:** confirm nothing recomputes/clobbers a fixed task's `next_due` on
load/normalize/refresh (snooze writes a transient override that must survive until the
next completion). Trace `recurrence.compute_next_due` call-sites; add a regression test.

### 3b. New services

- **`home_keeper.notify`** (§2d) — resolves a profile (or inline args), computes the
  due queue via the pure filter+sort, and dispatches to the sender.
- **`home_keeper.snooze_task` / `skip_task`** — schema + handler in `__init__.py`,
  registered + added to `_SERVICES`; `services.yaml` + `strings.json` parity. The
  notification-action listener delegates to these (and to `complete_task`).
- **Profile CRUD.** v1 can edit the whole `OPTION_NOTIFY_PROFILES` list through the
  existing `set_options` path (panel saves the list). A thin
  `home_keeper.set_notification_profile` / `delete_notification_profile` pair
  (delegating to an `options.py` helper that upserts/removes by `id`) is the
  service-first nicety; add if cheap, otherwise document `set_options` as the API.

New constants in `const.py`: `EVENT_TASK_SNOOZED`, `EVENT_TASK_SKIPPED`,
`ORIGIN_NOTIFICATION_ACTION`, `OPTION_NOTIFY_PROFILES`.

### 3c. Pure helpers (unit-tested, HA-free)

- `tasks.matches_filter(task, filter)` — the shared label/area/device/status predicate.
- `notifications.due_queue(tasks, filter, *, now)` — filter + sort (most-overdue-first).
- `notifications.build_notification(task, *, profile, snooze_hours, now)` — returns the
  `notify` `data`: localized `title`/`message`; `tag = f"home_keeper_{profile_id}"`
  (one rolling notification *per profile* so the walk replaces in place, not a pile);
  `data.actions` from the profile's ordered `actions`, each id
  `HOME_KEEPER::{verb}::{task_id}::{profile_id}`; the `open` action carries a `uri` to
  the panel detail page.
- `notifications.decode_action(action_str)` → `(verb, task_id, profile_id) | None`.

### 3d. Sender + listener (HA-aware)

- **Sender** (`notifications.py`): `async_send_for_profile(hass, profile, *, reason)` —
  computes the queue, builds payload(s) per `style`, calls each target service.
  Best-effort (`try/except`, debug log) so a renamed target never breaks anything.
  - *Automatic* source: in `coordinator._async_update_data`, after the transition
    events fire (and only when `_events_enabled`, preserving baselining), for each
    profile whose `auto.overdue`/`auto.due_soon` matches the fired kind **and** whose
    filter matches the task, send (respecting `quiet_hours`).
  - *On-demand* source: the `home_keeper.notify` service.
- **Listener** (`notification_actions.py`, wired in `async_setup_entry`, cleaned up via
  `entry.async_on_unload`): subscribes to `mobile_app_notification_action`,
  `decode_action`s, dispatches `complete`/`snooze`/`skip` (with
  `origin=ORIGIN_NOTIFICATION_ACTION`), clears the just-shown notification by `tag`,
  then for a `walk` profile **sends the next** due task (or the "all caught up" closer).
  Foreign actions (no `HOME_KEEPER::` prefix) are ignored.

### 3e. Events + device triggers

Add `task_snoozed` / `task_skipped` to `device_trigger.py` `TASK_TRIGGERS`
(translation-parity labels) and to `docs/EVENTS.md` (catalog rows; `task_snoozed`
adds `snoozed_until`). Per `AGENTS.md`, an event isn't done until it's in both.

---

## 4. Frontend — Settings → Notifications card

In `panel.ts` `_renderSettingsForm`, add a **Notifications** section that lists
profiles (like the Companions section lists companions) with **Add profile** and
per-row **Edit / Delete**. Each profile editor is an `ha-form` over a new
`notificationProfileSchema()` (`forms.ts`): name, targets multi-select (populated from
`get_options`' available targets), the `filter` group (label / area / device selectors
+ a `status` select), the ordered `actions` multi-select, `snooze_hours`, `style`,
`auto.overdue` / `auto.due_soon`, and optional `quiet_hours`. Saving writes the whole
profile list back through the existing autosave path (`_saveOptions → api.setOptions`);
`HomeKeeperOptions` + `get_options` gain `notify_profiles` and
`notify_available_targets`. i18n keys in `locales/*`.

> **UI gate (AGENTS.md):** new panel surface ⇒ the PR **must** embed a current
> Playwright screenshot of the Settings → Notifications card (capture step added in the
> same PR, PNG under `docs/images/`), and README gets a feature section + screenshot.

---

## 5. Testing

- **Unit (pure):** `matches_filter` (label/area/device/status combinations);
  `due_queue` ordering (most-overdue-first, ties); `build_notification` (tag per
  profile, action encoding incl. profile id, action-set ordering/clamp, open-URI,
  digest vs separate); `decode_action` (valid / foreign / malformed);
  `recurrence.skip_occurrence` (fixed walk-forward across `now` incl. DST, floating,
  one-off/triggered → dormant); snooze/skip recurrence math; the fixed-schedule
  **no-clobber** regression.
- **Integration:** a synthetic `mobile_app_notification_action` drives
  complete/snooze/skip through the store with the right events/origin **and** triggers
  the **next** walk send; `home_keeper.notify` sends the first due task for a profile,
  honours filters, and returns `{matched, sent}`; problem-sensor tasks reject
  snooze/skip; automatic source respects `auto`/`quiet_hours`; "all caught up" closer
  when the queue empties.
- **E2E:** screenshot of the Notifications card (with a sample profile).

---

## 6. Docs & changelog

- `docs/EVENTS.md` — `home_keeper_task_snoozed` / `_skipped`.
- `docs/INTEGRATING.md` — the `home_keeper.notify` service + the action/origin contract.
- `README.md` — a **Notifications** feature section: the per-person-chore-queue and
  calendar-driven use cases, how to configure profiles, screenshot.
- `services.yaml` + `strings.json` — `notify`, `snooze_task`, `skip_task` (+ profile
  CRUD if added) and any new options-flow fields, with localization parity.
- `CHANGELOG.md` — user-facing **Added** entry.
- `.amazonq/rules/` — record the action-string encoding scheme + the
  "one pure filter predicate shared by panel/card/notifier" convention.

---

## 7. Implementation order (incremental, each independently shippable)

1. **Snooze/skip core** — events/origin, `recurrence.skip_occurrence`, store methods,
   services, YAML/strings, `EVENTS.md`, `device_trigger.py`, tests. *(Usable via
   service/automation with no notifications yet.)*
2. **Filter predicate + due queue** — extract `matches_filter`, add `due_queue`, unit
   tests. (Also lets the panel/card de-duplicate their filter logic onto it.)
3. **Profiles in options** — `OPTION_NOTIFY_PROFILES` in `const.py` / `options.py` /
   `config_flow.py`; `get_options` target + profile enumeration.
4. **Sender + builder + the `notify` service** — `notifications.py`, on-demand path,
   digest/separate styles, unit/integration tests.
5. **Action listener + the walk** — `notification_actions.py`, advance-on-action,
   "all caught up" closer, integration tests.
6. **Automatic source** — coordinator hook honouring `auto`/`quiet_hours`.
7. **Panel** — Settings → Notifications profile editor, i18n, types; e2e screenshot;
   README.
8. Amazon Q (Cue) review after each push per `AGENTS.md`.

---

## 8. Deferred / future

- **Built-in per-profile schedule** (send "my chores" every weekday 6pm) so users
  needn't write the calendar/time automation. The on-demand service is the primitive;
  a schedule is sugar on top.
- **Assignee-aware routing** — once the assignees feature exists, a profile filters by
  *who's responsible* instead of by label (`IDEAS.md`).
- **Per-task notification overrides** (mute a chore; force a task into a profile).
- **Repeat / escalation** ("re-nudge every N hours until done"; escalate to another
  target). Today: one reminder per `next_due`, plus a fresh one after snooze.
- **Multiple snooze buttons** (1h / tonight / tomorrow) instead of one duration.
- **Non-mobile fallbacks** — `persistent_notification` and TTS/speaker targets for the
  `digest` style (actionable buttons stay mobile-only; a spoken/visual summary works
  anywhere).
- **A shipped blueprint** as a power-user alternative — the snooze/skip services +
  action listener built here are exactly what it would need, so it's purely additive.
