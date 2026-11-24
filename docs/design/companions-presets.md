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
  - custom_components/home_keeper/preset_registry.py
  - custom_components/home_keeper/frontend/src/panel-declarative.ts
  - custom_components/home_keeper/frontend/src/declarative-filters.ts
  - custom_components/home_keeper/frontend/src/preset-picker.ts
  - custom_components/home_keeper/frontend/src/preset-nudge.ts
  - custom_components/home_keeper/frontend/src/preset-summary.ts
  - custom_components/home_keeper/frontend/src/panel-preset-nudge.ts
related: [sensor-tasks, store, events-api, transfer, frontend]
source_hash: 5dfc1d4ff9f0
---

# Companions and presets

A companion is another integration that works with Home Keeper. Settings → Companions lists
the connected companions and the glue integrations that Home Keeper suggests. A declarative
companion is a spec that Home Keeper runs: 1 managed sensor task for each entity it selects.
A preset is a declarative companion spec that ships as data, or that a companion registers.

## Goals

- **G1. Two discovery paths, one list.** An integration announces itself, or Home Keeper
  detects a known upstream and suggests its glue. The panel shows one merged list.
- **G2. Tasks from entities, with no code.** A spec gives each matched entity a task with
  a templated name and notes and a sensor trigger.
- **G3. Tasks follow the registry.** Tasks follow entities that appear, go, move or get a
  new name, and keep their completion history. The companion owns only the fields it writes.
- **G4. Presets are data.** 1 catalog row per integration gives its presets in 17
  languages, and the Tasks tab suggests the presets that match entities in the home.

## Non-goals

- Home Keeper does not import a companion or edit its settings. Configure opens the
  companion's integration page. The integrator contract is in
  [../INTEGRATING.md](../INTEGRATING.md) and [../GLUE_INTEGRATIONS.md](../GLUE_INTEGRATIONS.md).
- The sensor watcher arms and clears a materialized task (sensor-tasks).

## Design

### Discovery: push and pull

- **Push.** An integration calls the admin-only `home_keeper.register_companion`.
  `companions.REGISTER_COMPANION_SCHEMA` bounds each field and accepts only an http(s)
  `docs_url`. `companions.CompanionRegistry` keeps the descriptors in order on `hass.data`.
  At setup Home Keeper fires `home_keeper_register_companions`, so companions register again.
- **Pull.** `companions_catalog.CATALOG` maps a popular upstream to its glue.
  `companions_catalog.build_companion_list` marks a registered companion or an installed glue
  `connected`, and an upstream with no glue `suggested`, unless `dismissed_companions` names it.
- `CompanionRegistry.reconcile` runs on each coordinator refresh and registration. It fires
  `home_keeper_companion_connected` or `_suggested` only for a domain that enters the state,
  and only after `async_at_started`, so a restart announces nothing again.

### The spec

`declarative_companions.normalize_declarative_companion` validates a spec, which the store
keeps under `declarative_companions` by `id`. Besides `name`, `description`, `enabled` and
`preset_id`, a spec has a `selection` (target integration, domain, device class, entity regex,
`translation_keys`, device/area/label lists and 4 exclusion lists, all ANDed), a `trigger` (a
sensor binding with no entity, checked by `models.normalize_sensor`), and a `task_template`
(`name_template`, `notes_template`, `labels`, and `task_names`: a `translation_key` to the
`{{ task_name }}` text). `per_entity_overrides` is reserved. A translation key survives a
rename or a language change, and `declarative_companions.summarize_keys` lists them.

### The sync pass

`declarative_companion_sync.DeclarativeCompanionSync` runs a pass at setup and when its
listeners start, then on each registry event through a debouncer (a burst costs 2 passes).
A spec change (`SIGNAL_DECLARATIVE_SPECS_CHANGED`) gets its own pass. For each enabled spec:

1. `declarative_companions.expand_spec` matches the registry snapshot by
   `(spec_id, entity_registry_id)`, so a rename keeps the task. Disabled entities and Home
   Keeper entities never match. More than `MAX_DECLARATIVE_MATCH_HARD` matches is an error.
2. Jinja renders name and notes (`template_context.template_variables`). No state: `stale`.
3. `declarative_companions.reconcile_declarative_tasks` adds a dormant task for a new match,
   writes the owned fields, deletes a lost key's task, and pauses or deletes a disabled
   entity's task by `has_history`. A `stale` key or a blank name keeps name and notes.
4. When the task set changed, the pass marks new ids (`sensor_watcher.async_mark_tasks_new`)
   and reloads the entry for the device-page entities. Else it refreshes the coordinator.

A disabled spec pauses its tasks (`declarative_companions.pause_spec_tasks`) with a `paused`
marker in `source`, and enable switches on the marked ones. A task a person switched off stays
off. A deleted spec removes its tasks. A spec change awaits `async_settle` and the reload.

### Ownership on a task

`declarative_companions.build_managed_by` stamps `managed_by`: Home Keeper's config entry,
`deletion_protected`, and `locked_fields` (name, recurrence type, device, area, `sensor`, and
`notes` when `declarative_companions.owns_notes`). Spec labels change only on a spec save
(`declarative_companions.apply_template_label_diff`). `completion_blocked` copies
`clear_on_recover`. `declarative_companions.merge_sensor_binding` keeps a meter `baseline`.

### Presets as data

`declarative_presets.CATALOG_PRESETS` starts with 3 general presets.
`declarative_presets_catalog.INTEGRATIONS` has 1 row per integration: domain, brand, icon,
upstream `source`, a `verified` pin, and duties, each with a name id in
`declarative_preset_text.DUTY_NAMES`, a shape, keys and a limit.
`declarative_presets._integration_presets` makes 1 preset per shape, platform, state and device
class group. The 6 `SHAPES` give a `threshold`, `state` or `template` trigger (in hours for a
time), always with `clear_on_recover`. Unedited preset text follows the Home Assistant language
(`localized_task_template`). The weekly `preset-upkeep` skill reads `ci/check_preset_keys.py`
and `ci/find_preset_candidates.py` and opens 1 draft PR.

### Companion presets

A companion sends catalog rows to the admin-only `home_keeper.register_presets`.
`preset_registry.validate_row` checks the row format for shipped and companion rows.
`preset_registry.build_registration` builds them with `_integration_presets`, so a row has no
Jinja. `duty_names` need `en`. Ids are `<companion>/<id>`. `preset_registry.transition` makes
each state of `companions.PresetRegistryHolder`, memory on `hass.data`, and its 2 events, which
fire after start and on a change. The unload of a companion's last config entry removes its
presets. `companions.async_merged_presets` feeds the list. An added spec is a copy.

### Panel

- `panel-declarative.ts` draws the Companions list, the preset picker and the add/edit dialog,
  with More filters (`declarative-filters.ts`) and a live preview of up to 10 rows with Exclude.
  A list row shows the logo, a shape badge and `preset-summary.companionOrigin`.
- `preset-picker.ts` puts integration presets with matches first, then general presets, then
  the rest behind Show all. `preset-picker.presetFromBadge` says "From <companion>".
  `preset-summary.ts` shows the source preset, the changes, and each reading against the limit.
- `preset-nudge.ts` and `panel-preset-nudge.ts` suggest presets that match entities and have
  no companion: a one-time dialog for up to `ONE_STEP_MAX` matches, then a card. The `shown`
  and `dismissed` lists live in per-user data (`home_keeper_preset_nudge`) and only grow.

## Trade-offs

- **Pure core, thin Home Assistant layer** over one module: the rules are under the mutation gate.
- **Pause** over **delete** for a disabled spec, or an entity's task with history.
- **Translation keys** over entity-id patterns: stable over renames, but some need a regex.
- **Memory** over **storage** for companion presets: a removed companion leaves no rows.

## One-way doors

- The stored spec, its service fields, and `source.declarative_companion` on a task.
- Preset ids (`<domain>_<shape>[_<platform>][_<state>]`) in `preset_id`, and the user-data
  key `home_keeper_preset_nudge`.
- The `register_companion` descriptor fields and the 3 companion events.
- The `register_presets` fields, the row format, `<companion>/<id>`, the 2 preset events,
  and `source` and `provided_by` in the preset list.
