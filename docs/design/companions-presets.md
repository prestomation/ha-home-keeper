---
title: Companions and presets
summary: Lists companion integrations and turns matched entities into managed sensor tasks.
implements:
  - custom_components/home_keeper/companions.py
  - custom_components/home_keeper/companions_catalog.py
  - custom_components/home_keeper/declarative_companions.py
  - custom_components/home_keeper/declarative_companion_sync.py
  - custom_components/home_keeper/declarative_presets.py
  - custom_components/home_keeper/declarative_presets_catalog.py
  - custom_components/home_keeper/declarative_preset_text.py
  - custom_components/home_keeper/frontend/src/panel-declarative.ts
  - custom_components/home_keeper/frontend/src/declarative-filters.ts
  - custom_components/home_keeper/frontend/src/preset-picker.ts
  - custom_components/home_keeper/frontend/src/preset-nudge.ts
  - custom_components/home_keeper/frontend/src/preset-summary.ts
  - custom_components/home_keeper/frontend/src/panel-preset-nudge.ts
related: [sensor-tasks, store, events-api, transfer, frontend]
source_hash: 5bef7a92a59a
---

# Companions and presets

A companion is another integration that works with Home Keeper. Settings → Companions lists
the connected companions and the glue integrations that Home Keeper suggests. A declarative
companion is a spec that Home Keeper runs itself: it makes 1 managed sensor task for each
entity it selects. A preset is a declarative companion spec that ships as data.

## Goals

- **G1. Two discovery paths, one list.** An integration announces itself, or Home Keeper
  detects a known upstream and suggests its glue. The panel shows one merged list.
- **G2. Tasks from entities, with no code.** A spec gives each matched entity a task with
  a templated name and notes and a sensor trigger.
- **G3. Tasks follow the registry.** Tasks follow entities that appear, go, move or get a
  new name, and keep their completion history. The companion owns only the fields it writes.
- **G4. Presets are data.** 1 catalog row per integration gives its presets in 16
  languages, and the Tasks tab suggests the presets that match entities in the home.

## Non-goals

- Home Keeper does not import a companion or edit its settings. Configure opens the
  companion's integration page. The integrator contract is in
  [../INTEGRATING.md](../INTEGRATING.md) and [../GLUE_INTEGRATIONS.md](../GLUE_INTEGRATIONS.md).
- The sensor watcher arms and clears a materialized task (sensor-tasks).

## Design

### Discovery: push and pull

- **Push.** An integration calls `home_keeper.register_companion`.
  `companions.REGISTER_COMPANION_SCHEMA` bounds each field and accepts only an http(s)
  `docs_url`. `companions.CompanionRegistry` keeps the descriptors in memory on `hass.data`.
  At setup Home Keeper fires `home_keeper_register_companions`, so companions register again.
- **Pull.** `companions_catalog.CATALOG` maps a popular upstream to its glue. The pure
  merge, `companions_catalog.build_companion_list`, marks a registered companion or an
  installed glue `connected`, and an upstream with no glue `suggested`, unless the
  `dismissed_companions` option names the glue.
- `CompanionRegistry.reconcile` runs on each coordinator refresh and registration. It fires
  `home_keeper_companion_connected` or `_suggested` only for a domain that enters the state,
  and only after `async_at_started`, so a restart announces nothing again.

### The spec

`declarative_companions.normalize_declarative_companion` validates a spec. The store keeps
specs under `declarative_companions`, keyed by `id`. Besides `name`, `description`,
`enabled` and `preset_id`, a spec has a `selection` (target integration, domain, device
class, entity regex, `translation_keys`, device/area/label lists and 4 exclusion lists, all
ANDed), a `trigger` (a sensor binding with no entity, checked by `models.normalize_sensor`),
and a `task_template` (`name_template`, `notes_template`, `labels`, and `task_names`, which
maps a `translation_key` to the `{{ task_name }}` text). `per_entity_overrides` is reserved.
The `translation_key` is the best selector, because a rename or a language change keeps it.
`declarative_companions.summarize_keys` lists the keys, which Home Assistant hides.

### The sync pass

`declarative_companion_sync.DeclarativeCompanionSync` runs a pass at setup, then on each
entity, device and area registry event through a debouncer, so a burst costs 2 passes. A
spec change (`SIGNAL_DECLARATIVE_SPECS_CHANGED`) gets its own pass. For each enabled spec:

1. `declarative_companions.expand_spec` matches the registry snapshot. The match key is
   `(spec_id, entity_registry_id)`, so a rename keeps the task. Disabled entities and Home
   Keeper entities never match. More than `MAX_DECLARATIVE_MATCH_HARD` matches is an error.
2. Jinja renders name and notes (`template_context.template_variables`). No live state
   makes a key `stale`.
3. `declarative_companions.reconcile_declarative_tasks` creates a dormant task for a new
   match, writes the owned fields of an existing one, deletes a lost key's task, and pauses
   a disabled entity's task. A `stale` key or a blank name keeps the task name and notes.
4. When the task set changed, the pass marks new ids (`sensor_watcher.async_mark_tasks_new`)
   and reloads the entry for the device-page entities. Else it refreshes the coordinator.

A disabled spec pauses its tasks (`declarative_companions.pause_spec_tasks`): it switches
each off with a `paused` marker in its `source`, and enable switches on the marked ones. A
task a person switched off stays off. A deleted spec removes its tasks. Calls that change a
spec await `declarative_companion_sync.async_settle`, so they answer after the reload.

### Ownership on a task

`declarative_companions.build_managed_by` stamps `managed_by`: Home Keeper's config entry,
`deletion_protected`, and `locked_fields` (name, recurrence type, device, area, `sensor`,
and `notes` when `declarative_companions.owns_notes`). `labels` is never locked; spec
labels change only on a spec save (`declarative_companions.apply_template_label_diff`).
`completion_blocked` copies `clear_on_recover`: when the watcher closes the task, Done is
withheld. `declarative_companions.merge_sensor_binding` keeps a `usage` meter `baseline`.
On an arm, `DeclarativeCompanionSync.async_refresh_task_notes` renders the notes again.

### Presets as data

`declarative_presets.CATALOG_PRESETS` starts with 3 general presets.
`declarative_presets_catalog.INTEGRATIONS` has 1 row per integration: domain, brand, icon,
upstream `source` file, a `verified` pin, and duties. A duty has a name id in
`declarative_preset_text.DUTY_NAMES`, a shape, keys and a limit. At import,
`declarative_presets._integration_presets` makes 1 preset per shape, platform, state and
device class group. The 6 `SHAPES` give a `threshold`, `state` or `template` trigger (the
template converts time units to hours), always with `clear_on_recover`.
`declarative_presets.localized_task_template` puts unedited preset text into the Home
Assistant language. Text a user edited stays as written.

Upkeep: `ci/check_preset_keys.py` reports keys changed upstream since `verified.ref`, and
`ci/find_preset_candidates.py` lists uncovered integrations. The weekly `preset-upkeep`
skill reads both, fixes the catalog, moves the pins and opens 1 draft PR.

### Panel

- `panel-declarative.ts` draws the Companions list, the preset picker and the add/edit
  dialog, with More filters (`declarative-filters.ts`) and a live preview: up to 10 rendered
  rows, the count, a template-trigger verdict per row, and Exclude.
- `preset-picker.ts` puts integration presets with matches first, then general presets,
  then the rest behind Show all. `preset-summary.ts` shows the source preset, the changed
  sections, and each reading against the preset limit.
- `preset-nudge.ts` and `panel-preset-nudge.ts` suggest presets that match entities and
  have no companion. A one-time dialog adds the checked presets with at most `ONE_STEP_MAX`
  matches; a card above the task list holds the rest. The `shown` and `dismissed` lists
  live in per-user data (`home_keeper_preset_nudge`) and only grow, so copies merge by union.

## Trade-offs

- **Pure core, thin Home Assistant layer** over one module: the selection, diff and
  ownership rules are under the mutation gate. Jinja and registries stay in the sync.
- **Pause** over **delete** for a disabled spec or entity: the completion history stays.
- **Translation keys** over entity-id patterns for presets: stable across renames and
  languages, but an integration with no keys needs a regex.

## One-way doors

- The stored spec, its service fields, and `source.declarative_companion` on a task.
- Preset ids (`<domain>_<shape>[_<platform>][_<state>]`) in `preset_id`, and the user-data
  key `home_keeper_preset_nudge`.
- The `register_companion` descriptor fields and the 3 companion events.
