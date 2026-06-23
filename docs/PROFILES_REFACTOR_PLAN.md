# Profiles refactor — make saved filters standalone & reusable

**Status: proposed (folds into PR #81 before merge).** The actionable-notifications
work introduced a "notification profile" that bundles two unrelated things: a **filter**
(which tasks — status + labels/areas/devices) and a **delivery** config (targets,
buttons, style, snooze, auto). This plan splits them so the **filter becomes a
standalone, reusable `Profile`**, and a **`Notification` is just one consumer** that
references a Profile and adds delivery. The same Profile can then drive **panel admin
filtering** and the **Lovelace card**, so "what counts as *my chores*" is defined once
and reused everywhere.

Because notifications are **not yet released** (only on this branch / the
`0.4.0.dev81` preview), we reshape the storage model now rather than ship the bundled
shape and rework it later — only the dev preview needs a light migration.

## 1. Data model

Two config lists on the entry options (edited via the panel / `set_options`, like
today):

```
profiles:      [ { id, name, filter: { status, labels, areas, devices } } ]
notifications: [ { id, name, profile_id, targets, actions, snooze_hours, style, auto } ]
```

- **`Profile`** = a named saved filter. `filter.status ∈ all | overdue | due_soon`;
  `labels`/`areas`/`devices` are id lists (OR within a list, AND across lists; empty =
  any). This is exactly today's notification `filter` block, lifted out and named.
- **`Notification`** = delivery binding: a `profile_id` (what's due) + the delivery
  fields that exist today (`targets`, `actions`, `snooze_hours`, `style`, `auto`). Its
  `name` is its own (e.g. "My chores → my phone").
- A Notification with a dangling `profile_id` (profile deleted) is treated as inert and
  surfaced in the UI as "needs a profile" rather than silently matching nothing.

## 2. Backend

- **New pure module `profiles.py`** — move `normalize_profile`/`normalize_profiles`/
  `resolve_profile`, the **filter predicate** `matches_filter`, and `due_queue` out of
  `notifications.py` into it (they're the reusable, notification-agnostic core).
  `notifications.py` keeps only delivery concerns (action verbs/styles, `encode/decode_action`,
  `build_notification`/`build_digest`/`build_all_clear`, and a new `normalize_notification`).
- **`const.py`**: add `OPTION_PROFILES = "profiles"`; rename
  `OPTION_NOTIFY_PROFILES` → `OPTION_NOTIFICATIONS = "notifications"`.
- **`options.py`**: normalize both lists; **cross-validate** that each notification's
  `profile_id` exists (else mark inert). Add the **migration** (§5).
- **`notifier.py`**: resolve a notification → its profile (`profiles.resolve_profile`)
  → `due_queue`. The coordinator's automatic source iterates `notifications` (not
  profiles) for `auto`.
- **Filter-input enrichment (parity, §4).** Keep `matches_filter` **pure** by feeding
  it a task pre-enriched with its *effective* area and labels (own + device + area
  inheritance). The HA-aware caller (notifier/coordinator) computes the enrichment from
  the device/area registries; the panel/card compute the same in TS. This is the one
  semantic subtlety to pin down — see §4.

## 3. Services & websocket

- **`home_keeper.notify`** — accept either `notification` (a saved Notification id/name
  → uses its profile + delivery) **or** `profile` (a Profile id/name) + inline delivery
  overrides (`target`/`actions`/`style`/`snooze_hours`) for ad-hoc sends. Returns
  `{matched, sent}` as today.
- **`home_keeper.list_profiles`** — response service returning the profiles (for
  automations/templates). Optionally extend `list_tasks` to accept a `profile` and
  return only matching tasks (the canonical Python predicate, handy for templates and
  as a card fallback).
- **Profile CRUD** rides the existing `set_options` path (the panel saves the whole
  list), mirroring how notifications/profiles are saved today; a thin
  `set_profile`/`delete_profile` pair can delegate to an `options` helper if we want
  service-first parity.
- **Websocket**: `get_options` already returns the full options object — extend it to
  carry `profiles` + `notifications`. Add **`home_keeper/get_profiles`** so the
  **Lovelace card** (which lives outside the panel) can resolve a selected profile
  without pulling all options.
- `services.yaml` + `strings.json` + 16-locale parity for the new/changed services.

## 4. Shared filter semantics & parity (the crux)

A Profile is applied by **two independent implementations**: Python (`profiles.matches_filter`,
for notifications) and TS (`card-filter.ts`, for the card + panel list). They must agree.

- **Pin the semantics in a spec**: a task matches when `status` matches its due-state
  and the task's **effective** labels/area/device clear the filters. "Effective" =
  the resolution the card already does (label on task **or** its device **or** its
  area; area = task's own else its device's). Today's Python predicate only checks the
  task's *own* fields — aligning on the effective semantics is the real work here.
- **Implementation**: enrich each task with `_effective_labels` / `_effective_area`
  before filtering. Backend computes it from the registries (HA-aware) and passes the
  enriched task into the pure predicate; the card/panel already have this in TS.
- **Conformance test**: a shared fixture `tests/fixtures/profile_filter_cases.json`
  (`{tasks, filter, expected_ids}` vectors) loaded by **both** `tests/unit/test_profiles.py`
  (Python) and a **vitest** test (TS), so the two predicates can't drift — the same
  guardrail style as the i18n parity tests.

## 5. Migration (dev-preview only)

On options load: if the legacy `notify_profiles` key is present (and `profiles`/
`notifications` are not), split each entry into a `Profile` (its `filter` + `name`) and
a `Notification` (its delivery fields + `profile_id` = the new profile's id), then drop
`notify_profiles`. Additive, no storage-version bump; a no-op for fresh installs.
(Released installs don't exist yet, so this only catches the `0.4.0.dev81` preview.)

## 6. Frontend (panel + card)

- **Types**: replace `NotificationProfile` with `Profile` and `Notification`.
- **Settings → Profiles** (new card): CRUD of profiles (name + status + labels/areas/
  devices), reusing the `ha-form` autosave pattern.
- **Settings → Notifications** (existing card): the per-notification editor drops the
  inline filter fields and gains a **Profile dropdown** (+ "Add profile" shortcut),
  keeping targets/buttons/style/snooze/auto.
- **Panel admin list view**: add a **Profile picker** to the list controls; selecting
  one applies its filter to the admin list (mapped onto the existing `card-filter`
  machinery the panel list already uses).
- **Lovelace card**: `HomeKeeperCardConfig` gains `profile?: string`; when set, the
  card resolves the profile (via `home_keeper/get_profiles`) and applies its filter.
  Card visual editor gets a **Profile dropdown**. Precedence: a selected profile
  supplies the *what-tasks* filter (status/labels/areas/devices); the card's own
  presentation options (sort/group/horizon/columns) stay independent; inline
  label/area/device fields are ignored while a profile is selected (documented).
- i18n keys for the Profiles card + the profile pickers (16-locale parity, vitest
  gate).
- **Screenshots** (UI gate): new Settings → Profiles card, the Notifications editor's
  profile dropdown, and the card editor's profile picker.

## 7. Testing

- **Unit (pure)**: `test_profiles.py` — normalize/resolve, `matches_filter` (incl.
  effective labels/area), `due_queue`; the **conformance fixture** shared with vitest.
- **vitest**: the TS side of the conformance fixture; card/panel profile application.
- **Integration**: `notify` with a `notification` and with a `profile`+inline; profile
  CRUD round-trips; dangling-`profile_id` handling; the migration.
- **e2e**: the three new/changed screenshots.

## 8. Docs

- `README.md`: a short **Profiles** subsection (saved filters reused by notifications,
  the admin list, and the card), with the screenshot; update the Notifications section
  to "pick a profile".
- `docs/EVENTS.md`: unchanged (profiles are config, not state — no events).
- `CHANGELOG.md`: fold into the (unreleased) notifications entry — describe the shipped
  shape (Profiles + Notifications), not the intermediate one.
- `services.yaml`/`strings.json` + locales; `.amazonq/rules/` if a convention emerges
  (e.g. "one Profile filter spec, two conformant implementations").

## 9. Rollout order (within #81, each step green before the next)

1. **Extract `profiles.py`** (pure move of predicate/queue/normalize) + rename options
   keys; keep notifications working against the new module. Unit tests move/extend.
2. **Split the model** in `options.py` (Profiles + Notifications) + the migration;
   `notifier`/coordinator resolve via `profile_id`.
3. **Effective-field enrichment + conformance fixture** (Python + vitest parity).
4. **Services/websocket**: `notify` (notification|profile), `list_profiles`,
   `get_profiles`; YAML/strings/locales.
5. **Frontend**: Profiles settings card, Notifications→profile dropdown, panel
   list-view profile picker, card `profile` config + editor; i18n; screenshots; README.
6. Amazon Q review after each push.

## 10. Open questions / deferred

- **Effective vs own-field filter semantics** (§4) — recommend effective (matches the
  card today); the cost is enrichment plumbing + the conformance fixture.
- **Profiles as first-class entities/services** (a `home_keeper.set_profile` service,
  or even exposing profiles as HA entities) vs options-list-only — start with the
  options list + `list_profiles`, defer entity exposure.
- **Per-notification inline filter override** on top of a referenced profile — defer;
  the ad-hoc `notify(profile=…, inline overrides)` path covers one-offs.
- **Profile-driven `todo`/`calendar` entities** (a to-do list per profile) — natural
  future consumer once profiles exist; out of scope here.
