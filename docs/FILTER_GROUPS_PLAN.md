# Profile filter groups

A [Profile](../README.md#profiles-saved-filters-you-reuse-everywhere) is a saved task
filter: a status tier plus label, area, device, and companion filters. A Profile now
holds one or more **groups** instead of one flat filter, so it can express an OR of
rules and not only an AND. See
[issue #291](https://github.com/prestomation/ha-home-keeper/issues/291). This plan
describes work already implemented on this branch. It ships in 0.22.0b4.

## 1. Use cases

A flat filter is one AND-ed set of include lists plus one set of exclusions. It cannot
express an OR of two unrelated rules, and it cannot ask for every listed label on a
task instead of any one of them. Filter groups fix both gaps: a Profile now holds a
list of groups, each its own AND-ed rule with its own `labels_match` and its own
exclusions, and the Profile selects a task that matches any one active group.

| Use case | Flat filter result | Groups |
| --- | --- | --- |
| Kitchen tablet list: anything urgent, plus every Battery Notes task | Labels AND Companions gives only the urgent battery tasks | `labels: [urgent]` \| `companions: [battery_notes]` |
| Kids chore list: `kids` chores except the garage and workshop, plus dog tasks only in the yard | One exclusion applies to the whole filter, and Areas `yard` also limits the `kids` chores | `labels: [kids], exclude_areas: [garage, workshop]` \| `labels: [dog], areas: [yard]` |
| Handyman list: every task on the furnace and water heater, plus anything labelled `pro`, never a buy reminder | Devices AND Labels gives only `pro` tasks on those 2 devices | `devices: [furnace, water_heater], exclude_shopping: true` \| `labels: [pro], exclude_shopping: true` |
| Vet prep: tasks that carry both `dog` and `vet` | A label list means "any listed label", so walks and the cat show up | `labels: [dog, vet], labels_match: all` |
| Partner digest: kitchen and laundry tasks not owned by the printer companion, plus every task on the car | Areas AND Devices gives nothing, because a car task has no kitchen area | `areas: [kitchen, laundry], exclude_companions: [bambu_lab]` \| `devices: [car]` |

Each case is 1 Profile with 2 groups, or 1 group with `labels_match: all`. The
**Include** status stays 1 value per Profile in every case.

## 2. Data model

A profile's `filter` block:

```
filter: {
  status: "all" | "overdue" | "due_soon",
  groups: [
    {
      labels: [id, ...], labels_match: "any" | "all",
      areas: [id, ...], devices: [id, ...], companions: [domain, ...],
      exclude_labels: [id, ...], exclude_areas: [id, ...],
      exclude_devices: [id, ...], exclude_companions: [domain, ...],
      exclude_shopping: bool,
    },
    ...
  ],
}
```

This is the one stored shape. Nothing reads a flat `labels`/`areas`/`devices`/
`companions`/`exclude_*` key on `filter` any more.

- **Group-match rule.** A task matches one group when every include list that carries
  a value matches, and no exclude list hits. `labels` reads by `labels_match`: `any`
  wants one of the listed labels on the task, `all` wants every one of them. An
  exclusion wins inside its own group only, so a task an exclusion drops in one group
  can still match a sibling group.
- **Active-group rule.** A group with any list or `exclude_shopping` set is active. A
  task matches the Profile when it matches any active group.
- **Empty-group rule.** A group with nothing set is not active. An inactive group is
  dropped from the OR rather than treated as "match everything", so a blank group
  beside a filled-in one never widens the Profile. A filter left with no active group
  has no include gate and selects every task in its status tier.
- **Status stays per Profile.** `status` sits on `filter`, not on a group, so every
  group in a Profile answers the same "which due-state" question.
- **`labels_match` values and default.** `any` (default) or `all`. An unrecognized
  value falls back to `any`, so a bad value widens a group instead of narrowing it to
  nothing.

## 3. Backend and matcher parity

[`profiles.py`](../custom_components/home_keeper/profiles.py) holds the pure, HA-free
model:

| Function | Role |
| --- | --- |
| `normalize_group` | Coerce one group to its fixed key set; clamp `labels_match` |
| `normalize_groups` | Coerce a `groups` list; always return at least one group |
| `normalize_filter` | Coerce `filter` to `{groups, status}`; drop any flat key |
| `migrate_filter_v1` | Wrap one legacy flat filter in a single group |
| `migrate_options_v1` | Run `migrate_filter_v1` over every profile in an options blob |
| `check_profiles_use_groups` | Raise if a filter still carries a flat key |
| `_group_active` | Whether a group carries any value |
| `_group_matches` | Whether one group selects a task (the AND, then the exclusions) |
| `matches_filter` | The full gate: enabled, scheduled, status, then the OR of groups |

[`tests/fixtures/profile_filter_cases.json`](../tests/fixtures/profile_filter_cases.json)
is the cross-language contract: 69 `{task, filter, expected}` cases, loaded and
asserted by both the Python unit tier and a vitest suite. Each task carries its
**effective** label and area ids (its own plus any inherited from its device and
area), since each language resolves that inheritance before the shared matcher runs.

The TS twin, in
[`card-filter.ts`](../custom_components/home_keeper/frontend/src/card-filter.ts):
`groupMatches` mirrors `_group_matches`, `profileMatches` mirrors `matches_filter`, and
`filterTasks` (the card's own selection) ORs the card's `groups` the same way. The
fixture is what keeps the two implementations from drifting apart.

## 4. Migration

A stored Profile's filter is converted once, by a config-entry migration, not read in
two shapes forever.

- `migrate_filter_v1` converts one filter: the pre-groups flat keys become a single
  group, with `labels_match: any` since that was the only rule the flat shape had.
- `migrate_options_v1` runs `migrate_filter_v1` over every profile in an options blob,
  leaving every other option untouched.
- `async_migrate_entry` (in
  [`__init__.py`](../custom_components/home_keeper/__init__.py)) runs
  `migrate_options_v1` and writes the result back with `version=2`, when Home Assistant
  loads an entry whose stored version is 1. The version comes from
  [`config_flow.py`](../custom_components/home_keeper/config_flow.py)'s
  `HomeKeeperConfigFlow.VERSION = 2`.

The bump is a **major** version, not a minor one, because the two versions disagree
about how to read the same key. A v1 Home Keeper reading a v2 filter finds no flat
include list at all: it would widen every Profile to its whole status tier, which for
a synced Profile means pushing every task in the house onto that to-do list. A major
version makes Home Assistant refuse to load a v2 entry with an older integration
instead. A downgrade then needs a backup restored first, the honest failure instead of
a silent one.

A lazy alternative was rejected: keep reading the flat keys forever, alongside
`groups`, and treat either shape as valid input. That would mean two live matcher
paths, in two languages, kept in parity forever, rather than one converted shape
checked by one fixture. The migration is the one-time cost that keeps `matches_filter`
and `groupMatches` reading exactly one filter shape.

## 5. Services and websocket

| Surface | What changed |
| --- | --- |
| `home_keeper.set_options` service | `SET_OPTIONS_SCHEMA` runs `check_profiles_use_groups` on `profiles`; a flat key raises `vol.Invalid` |
| `home_keeper/set_options` websocket command | Same validator, wired into the command schema in [`websocket_api.py`](../custom_components/home_keeper/websocket_api.py) |
| `home_keeper.list_profiles` service | Returns each profile's `filter.groups`; never a flat key |
| `home_keeper/get_profiles` websocket command | Same, for the dashboard card's profile picker |
| `home_keeper/get_options` websocket command | Returns `groups` inside every profile's `filter`, alongside the rest of the options blob |
| `home_keeper.notify` service, `status` override | Unchanged: `with_status` still swaps `filter.status` for one call; groups are untouched |
| Dashboard card `profile:` config key | Unchanged: still resolves a saved Profile by id or name and applies its `filter` as it stands |

The validator is `check_profiles_use_groups` (`profiles.py`), shared by both write
paths. Its error text:

> `profile filter uses groups since 0.22.0b4; move labels/areas/devices/companions and
> exclude_* into filter.groups`

Both paths **refuse** a legacy filter rather than dropping the unread keys and saving
the rest. A silent drop would still accept the call and save a filter with no include
gate, which selects the profile's whole status tier. For a synced Profile, every task
in the house lands on that to-do list, with no error to explain why.

## 6. Frontend

[`group-editor.ts`](../custom_components/home_keeper/frontend/src/group-editor.ts) is
one groups editor, shared by the panel's profile editor and the card's own editor.
`ha-form` has no repeatable-list field, so no Home Assistant component can render "add
a group, edit its fields, delete it" on its own. `group-editor.ts` is that one builder.
Each caller supplies its own `ha-form` constructor and its own label strings: the
panel translates, the card editor stays English-only.

The panel's profile editor
([`panel-settings.ts`](../custom_components/home_keeper/frontend/src/panel-settings.ts),
`profileEditor`) is three `ha-form`s over one profile: a head form (name, status), the
groups editor, and the sync group. All three save through one debounce key per
profile, so whichever form fires last still writes the head, the groups, and the sync
setting together. Saving one form alone can never wipe a list or a group edited in
another.

The dashboard card's config gains a `groups` key
([`card.ts`](../custom_components/home_keeper/frontend/src/card.ts)), read by
`filterTasks` the same way a Profile's `groups` are read. `setConfig` calls
`liftLegacyCardConfig`, which rewrites the old flat `labels`/`areas`/`devices`/
`label_match` keys into one `groups[0]` entry. The lift happens in the card, not the
backend, because Home Assistant has no mechanism to rewrite a saved dashboard. A
storage-mode dashboard is rewritten the next time its own card editor saves, but a
YAML dashboard keeps the old keys until a person edits it by hand, so
`liftLegacyCardConfig` is permanent code, not a one-release shim. `label_match`
becomes `labels_match` inside the lifted group, so the card selects the same tasks it
did before, under the new key name.

## 7. Testing

| Tier | Result |
| --- | --- |
| Python unit (pytest) | 1973 pass |
| Frontend unit (vitest) | 1366 pass |
| Python mutation (mutmut, changed functions) | 98.65%, then the 4 surviving mutants killed |
| Frontend mutation (Stryker, changed lines) | 98.3% |
| Integration (Docker) | 197 pass, including 13 migration tests |
| e2e (Playwright) | 282 pass, including a new settings case: add a group, then read back 3 groups over `list_profiles` |
| mypy | 0 errors, run inside the Home Assistant `stable` image |
| vale | Hit set unchanged from `main` |

The 13 migration tests live in
[`tests/integration/test_migration.py`](../tests/integration/test_migration.py). They
boot Home Assistant from a v1-seeded entry and assert: the seeded legacy profile reads
back with `groups` and no flat key; every profile does, not only the seeded one; the
entry on disk is version 2; and both write paths (`set_options` the service, and the
websocket command) refuse each of the 9 flat keys, changing nothing on the refusal.

## 8. Docs

[`README.md`](../README.md)'s Profiles section is rewritten: "How filters combine"
covers the group-match rule and the OR of groups with the kids/dog worked example,
"Exclusions" covers the per-group exclude lists and `exclude_shopping`, and the
`custom:home-keeper-card` options list documents `groups`. `CHANGELOG.md` gets an
`0.22.0b4` **Added** bullet for filter groups and a **Changed** bullet each for the
Profile filter services and the card filter keys. `.amazonq/rules/architecture-and-code.md`
gets a rule bullet pinning the one-shape-only design, the v1→v2 migration, and the
card's permanent legacy lift. Two new screenshots ship:
`docs/images/profile-filter-groups.png` (desktop) and
`docs/images/profile-mobile-filter-groups.png` (phone), both a Profile with two groups
and the OR divider between them; `docs/images/profiles-card.png` and
`docs/images/47-panel-profile-sync.png` are refreshed. The walkthrough capture gets a
beat on `.hk-filter-groups` for the two-group profile it already seeds.

## 9. One-way doors

- `filter.groups`: key name, list, order round-trips stably; `filter.status` stays at
  the top.
- Per-group keys `labels`, `labels_match` (`any`|`all`, default `any`), `areas`,
  `devices`, `companions`, `exclude_labels`, `exclude_areas`, `exclude_devices`,
  `exclude_companions`, `exclude_shopping`. Empty include = any; empty exclude =
  nothing; exclusions win inside their group only.
- Active-group rule: a group with any value is active; empty groups are ignored beside
  an active one; no active group = every task in the status tier.
- Config entry `VERSION = 2`; the v1→v2 conversion is permanent code; a v1 reader
  refuses a v2 entry, so a downgrade needs a backup.
- Flat keys are refused on `set_options` (service and websocket); `list_profiles`,
  `get_profiles`, `get_options` return `groups` only.
- Card key `groups`; legacy card keys `labels`/`areas`/`devices`/`label_match` are
  lifted on read forever and never written by the editor.
- Not one-way: form field names, DOM ids/classes, locale keys, screenshot names, TS
  names.

## 10. Rollout

This work ships as one pull request, labelled `preview-release`, in the `0.22.0b4`
beta. On first start after the update, Home Assistant runs `async_migrate_entry`
before it sets up the config entry: it converts every stored Profile and writes one log
line, `Migrated Home Keeper options to version 2: N profile filter(s) now use filter
groups`. A user sees no prompt and takes no action; a Profile that used the flat filter
before the update selects the same tasks after it, now as one group.
