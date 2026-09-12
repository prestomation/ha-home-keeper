# Counted wear items — implementation plan

> Closes the "manual usage counters" request in
> [#306](https://github.com/prestomation/ha-home-keeper/issues/306). Written September
> 2026, after the design dialogue on the issue, a mockup round, and a review of the
> plan against the code on `main` (`591db64`).

---

## 1. The CHANGELOG entry this ships

Two bullets, because the naming half stands on its own.

```markdown
- **Counted wear items.** Set a wear item to repeat every so many uses, or after so
  many months, whichever comes first. Complete its use task from an automation, a tag
  scan or the panel to count 1 use. (Fixes #306)
- **Wear item actions.** Choose what a wear item's task is called: Replace, Clean,
  Service, Renew, Sharpen, Rotate or Inspect. An existing wear item keeps Replace.
```

`v0.23.0b2` is a **published tag** at `591db64`, which is the current `main`. So this
work opens **`0.23.0b3`**: bump `manifest.json` and `const.PANEL_VERSION`, and add a
`## [0.23.0b3]` section. Editing the `0.23.0b2` section instead fails
`changelog-release-gap`.

---

## 2. Context

A usage/meter task needs a numeric entity. Many real intervals have no such entity:
wears of a rain jacket, hikes in a pair of boots, washing cycles, charging cycles,
uses of a tool. `docs/USAGE_MAINTENANCE_GAP_ANALYSIS.md` records this as **G5** and
`docs/SENSOR_TASKS_PLAN.md` §8 deferred it as `mode: "count"`. The workaround today is
an HA `counter` helper plus an automation.

The issue dialogue moved the target twice, and both moves made the work smaller.

1. The maintainer asked whether a **wear item** could model it. The reporter agreed it
   covers most of the list, and narrowed the ask to *event-counted usage rather than
   time-based replacement*.
2. The reporter then withdrew the request for Home Keeper to own a counter: *"perhaps
   Home Keeper doesn't even need to implement its own counter logic."*

So **a use is a completion**, and `home_keeper.complete_task` is already the "this
happened" API — reachable from an automation, a script, an NFC tag scan, the Done
button, the per-task `button` entity, the to-do list and a notification action. The
count is derived from a list the store already keeps, and each entry already carries a
timestamp, a note, a cost, a photo and who.

**Be accurate about what this avoids.** Home Keeper still owns and persists the
counting state: the use task's `completions[]` *is* the count, the trim rule in §3
exists to keep that state correct, and `uses_since_replacement` is counting logic we
write and maintain. Measured in bytes this is more storage than an integer, not less.
What the design avoids is a new **numeric field, entity, service and event**, and the
`counter` helper the user would otherwise create and wire themselves.

It is also not quite the reporter's proposal. They suggested Home Keeper lean on an HA
`counter`; this design does its own counting and represents it as a log instead. The
agreement is on the outcome — no counter object for the user to manage — not on the
mechanism. The reporter accepted the two-task model in the mockup round: *"I think the
two-task model in your mockups is actually a better fit than the separate counter I
initially suggested."*

Mockups: posted on #306, at commit `2cfa5bc`.

---

## 3. Decisions already made

| | Decision | Why |
|---|---|---|
| **Two tasks** | A wear item measured in uses generates a **use task** and a **replacement task** | One task cannot mean both "I wore it" and "I renewed it". One task is also off by one: the 10th tap is the hike, not the wash |
| **Never due** | The use task carries `next_due: null` for its whole life | `isOverdue` is false with no `next_due`, so the filter pills, the overdue `binary_sensor`, the Profiles and the notifications all stay correct with no change. An always-due task would pin every one of them forever |
| **Its own section** | A `counted` status bucket, beside the `shopping` bucket that already gives a buy reminder its own section | `card-filter.statusBucket` is the precedent, and its comment is written for exactly this problem |
| **Not `usage`** | The bucket is `counted`, not `usage` | `SENSOR_MODE_USAGE` already claims "usage" for the meter-bound sensor task. Both are user-facing, and the house rule is one approved name per thing |
| **To-do list: yes** | The use task appears as an undated item | It is the one-tap surface people already have on their phone |
| **Calendar: no** | No change needed | The calendar builds events from `next_due`. No date, no event |
| **Time backstop** | A counted wear item can also carry "or every N months", and the replacement task arms on whichever comes first | The reporter asked for it in all 3 of their comments (*"DWR treatment every 25 wears **or every 12 months**"*). `sensor.also_every` is the same feature on a meter task, so the shape is already established |
| **No combinator** | The backstop is always "whichever comes first" | A usage task offers `any`/`all` because a "no earlier than" floor is real for a service interval. For a wear item it is not, and the field would be a one-way door bought for nothing |
| **Retention** | Keep the newest `min(max(2 × target, 50), 500)` use completions, and never trim an entry newer than the last replacement | The load-bearing window is "uses since the last replacement"; trimming it would silently break the reminder. 2 intervals is what `usage_interval_stats` needs. Self-scaling, so no new option |
| **Target ceiling** | A `uses` target is capped at **250** | `recurrence._record_entry` trims *every* completion list to `MAX_COMPLETION_HISTORY = 500`, blindly and before the rule above ever runs. `MAX_INTERVAL` is 10,000, so a 5,000-use target would silently lose load-bearing entries and read low forever. 250 makes `2 × target` land exactly on the global cap |

---

## 4. Data model

### 4.1 The part (`assets.py`)

`_normalize_part` gains 5 optional fields. All absent on every existing part, so there
is no migration.

| Field | Type | Meaning |
|---|---|---|
| `replace_unit` | now also `"uses"` | Validated against a **new** `PART_REPLACE_UNITS`, not `UNITS` — see below |
| `replace_also_every` | `{interval, unit}` or `None` | The optional time backstop. Same `{interval, unit}` shape and rules as `sensor.also_every`, `unit` from `UNITS` |
| `use_noun` | `str` | What 1 use is called, singular: `wear`, `hike`, `cycle`. Empty means `use` |
| `use_task_name` | `str` | Optional override for the use task's name. Empty means the localized `Use {asset}` |
| `action` | closed set | `replace` (default) / `clean` / `service` / `renew` / `sharpen` / `rotate` / `inspect` |

`replace_interval` is reused as the target, unchanged apart from the 250 ceiling that
applies only when the unit is `uses`.

**`replace_unit` must not just gain a value.** `assets._normalize_part` validates it
against `UNITS`, which is the *same* list `models.normalize_fields` uses for a floating
task's `unit`. Adding `"uses"` there would make `recurrence_type: "floating", unit:
"uses"` a valid task that no recurrence branch can compute. So `const.py` grows
`PART_REPLACE_UNITS = [*UNITS, UNIT_USES]` and only `assets.py` reads it.

New predicates beside `part_tracks_stock`:

```python
def part_counts_uses(part: dict) -> bool   # type == wear and replace_unit == "uses" and replace_interval
def part_use_noun(part: dict) -> str       # "wear", falling back to "use"
def part_action(part: dict) -> str         # "renew", falling back to "replace"
def use_retention_cap(part: dict) -> int   # min(max(2 * target, 50), MAX_COMPLETION_HISTORY)
```

### 4.2 The two tasks (`reconcile.py`)

Both are reconciler-owned through the existing `source.part` key, so
`is_manual_part_link` and the orphan sweep keep working. They are told apart by a new
`source.part.role` of `"use"` or `"replace"`; an absent role reads as `"replace"`, so
every existing derived task keeps its identity with no migration.

**`existing_by_key` has to carry the role.** It is keyed `(asset_id, part_id)` today,
and one part now owns 2 tasks. Left alone, the second task overwrites the first in the
index and the orphan sweep deletes whichever one lost. The key becomes
`(asset_id, part_id, role)`.

**Use task**
- `recurrence_type: "use"` — a new type. It has no cadence at all, which no existing
  type describes: `floating`/`fixed` carry an interval, `one-off` carries a date, and
  `todo.py` treats a dateless `sensor`/`triggered`/`one-off` as "off every time
  surface", which is the opposite of what this needs.
- `next_due` is always `None`. `models.normalize_fields` returns early for it exactly
  as it does for `REC_SENSOR`, and `merge_update` never recomputes a due date.
- Name: `part.use_task_name`, else the localized `Use {asset}` template.
- Completing it records a completion and nothing else.

**Replacement task**
- `recurrence_type: "triggered"` — dormant until armed, armed by the settle step,
  completed by hand. This is the existing shape for "something else decides when this
  is due", and it already has the right to-do and calendar behaviour while dormant.
- **`build_task` creates a triggered task ARMED, not dormant.** `compute_next_due`
  returns `now` for `REC_TRIGGERED` (the re-arm contract), so the reconciler must set
  `next_due = None` on the freshly built task, exactly as `build_task` itself does for
  `REC_SENSOR`. Getting this wrong ships every counted wear item overdue on creation.
- Name from the action template: `Renew {part} ({asset})`.
- **It always exists**, dormant, rather than being minted at the target like a buy
  task. Its completion history is the renewal history — cost, note, photo, who — and a
  task that is deleted and re-minted each cycle loses it.

### 4.2b Two things the plan missed, found by building it

Both were invisible to the unit tier, and both are now covered by a test.

**`_PART_SCHEMA` in `__init__.py` is a strict voluptuous schema.** Every new part
field has to be declared there or `add_asset` and `update_asset` answer `400`. The
unit tests call `assets._normalize_part` directly and never cross the service
boundary, so all of them passed while the whole feature was unreachable from an
automation. `tests/integration/test_use_tasks.py` is what found it.

**`mergePartForm` cleared `replace_unit` when the interval was empty.** Harmless
while every unit measured time — the field re-seeds to `months` — and a dead control
the moment `uses` existed: picking it before typing a target discarded the choice, so
the counting fields the unit reveals never appeared and the form looked broken.
Storage is unaffected by keeping it, because `assets._normalize_part` writes
`replace_unit` only when `replace_interval` is set.

### 4.3 A new recurrence type touches `recurrence.py`, not only `models.py`

`recurrence.py` has 6 branch points that key on the recurrence type, and a `use` task
reaches every one of them. Two `raise ValueError` on an unrecognized type outright
(`compute_next_due`, `apply_completion`); 4 more read `rec_type not in (REC_TRIGGERED,
REC_SENSOR)` and would call `compute_next_due` on a `use` task, hitting the same raise
(`snooze_task`, `remove_completion`, `move_completion`, `skip_occurrence`). **Every one
of them must treat `REC_USE` exactly as it treats `REC_TRIGGERED`: leave `next_due`
alone at `None`.** Without this the first completion of a use task raises before it
records anything.

### 4.4 The count

Pure, in `reconcile.py`:

```python
def uses_since_replacement(use_task: dict, replace_task: dict) -> int
```

The count is the number of use-task completions whose `ts` is later than the
replacement task's `last_completed` (all of them when it has never been completed).

**Reset is implicit.** Completing the replacement task moves `last_completed` forward,
so the next count starts from zero with no field to write and nothing to keep in sync.

The time backstop shares that anchor, so both halves reset together on one completion.
It is due at `last_completed + replace_also_every`, falling back to the part's
`last_replaced` and then the task's `created` while there has been no replacement —
the same ladder `sensor_tasks.backstop_due` walks.

---

## 5. What arms the replacement task

The count changes on a completion, which is a store mutation, not an asset edit — so
the reconciler alone is not enough. This mirrors stock exactly: an `adjust_part_stock`
crossing may create or retire a buy task, and `coordinator.async_settle_buy_tasks()` is
the settle step.

Add `coordinator.async_settle_use_tasks()`. It:

1. recomputes the count for each counted wear item,
2. calls `store.trigger_task` on the replacement task when the count reaches the target
   **or** the time backstop is due, and the task is dormant (this fires the existing
   `home_keeper_task_triggered`),
3. trims the use task's completion list to `use_retention_cap`, never removing an entry
   newer than the last replacement.

**It is called from 2 places, not 12.** `async_settle_buy_tasks` already documents
itself as "the single decision point ... any surface that can change a part's
low/enabled state (stock adjust, task completion)", and has 12 call sites. Calling the
use settle from inside it picks up all 12 for free. The second place is
`coordinator._async_update_data`, which already ticks on `SCAN_INTERVAL` and already
re-evaluates sensor tasks there — that tick is what makes the time backstop fire,
since no completion happens when a month simply passes.

Completing the replacement task early, while the count is below the target, is allowed
and simply restarts the count — the same rule a usage task already follows, where Done
re-anchors the meter.

### 5.1 A use completion must not consume a spare

`store.complete_task` branches on `_part_source(updated)` alone and calls
`_stamp_part_replacement`, which sets `part["last_replaced"] = today` and calls
`consume_part_stock`. A use task carries a part source, so without a gate **every wear
of the jacket would stamp a DWR treatment and draw a spare out of inventory**. The
gate is one condition: skip when the role is `use`.

---

## 6. Files to change

### Backend

| File | Change |
|---|---|
| `const.py` | `REC_USE`, `UNIT_USES`, `PART_REPLACE_UNITS`, `PART_ACTIONS`, `MAX_USE_TARGET`, `MIN_USE_RETENTION`, `USE_TASK_NAME_TEMPLATES`, `ACTION_TASK_NAME_TEMPLATES` (16 locales each), `PANEL_VERSION` bump |
| `models.py` | `RECURRENCE_TYPES` gains `REC_USE`; `normalize_fields` early-returns for it; `build_task` forces `next_due = None`; `merge_update` never recomputes it |
| `recurrence.py` | **All 6 branch points** treat `REC_USE` as `REC_TRIGGERED` — see §4.3 |
| `assets.py` | The 5 part fields, their validation against `PART_REPLACE_UNITS`, the 250 target ceiling, `part_counts_uses`, `part_use_noun`, `part_action`, `use_retention_cap` |
| `reconcile.py` | The role in `existing_by_key`, both tasks, the explicit dormant `next_due`, `uses_since_replacement`, `backstop_due`, the trim rule, orphan handling for the pair |
| `store.py` | Role-gate `_stamp_part_replacement`; settle after a use completion |
| `__init__.py` | The 4 new part keys in `_PART_SCHEMA` — a strict schema, so an undeclared key is a 400 |
| `coordinator.py` | `async_settle_use_tasks`, called from `async_settle_buy_tasks` and `_async_update_data` |
| `todo.py` | Leave `REC_USE` out of the dateless-drop tuple, with a comment saying why |
| `calendar.py` | No change. Add an assertion that a `use` task yields no event |
| `transfer.py` | A `use` row in `_PROBE_TASKS`, so the probe recognizes the type's fields |
| `api_surface.py` | The `recurrence_type` field description gains `use` |
| `services.yaml` | `use` in both `recurrence_type` selectors, described as reconciler-owned |
| `manifest.json` | Version bump |

`api_surface.py` needs **no** new `ServiceSpec` or `EventSpec` — the feature adds
neither. Confirm `test_api_surface.py` stays green rather than assuming it.

`recurrence_type: "use"` is accepted by `add_task` and `update_task` for parity with
every other type, but the **panel does not offer it**: a free-standing use task with no
part counts toward nothing. `services.yaml` says so.

### Frontend

| File | Change |
|---|---|
| `card-filter.ts` | A `counted` bucket in `statusBucket`, **beside the `monitored` check** — `if (!task.next_due) return 'none'` sits above the `shopping` line, so a dateless task never reaches it |
| `panel-types.ts` | `counted` in the bucket types and the filter union |
| `panel-controls.ts` | The Counted filter pill and its scope |
| `panel-lists.ts` | The use row: meta line, the `17 of 25 wears` status chip, keep Done |
| `panel-detail.ts` | The count chip and meter on the appliance page's part row |
| `forms.ts` | `uses` in the unit selector; the also-every backstop, `use_noun`, `use_task_name` and `action` fields; the summary line naming both generated tasks |
| `utils.ts` | `isUseTask`, the count formatter |
| `types.ts` | The `Part` and `Task` additions |

### Strings

`strings.json` + 16 `translations/*.json`, and 16 frontend `locales/*.json`. The action
templates are 7 actions × 16 locales, so draft them in one pass and check the parity
tests early — `test_translations_parity.py` and `i18n-parity.test.js` are strict.

---

## 7. One-way doors

Everything here lands in stored data, a service input or an event payload, so renaming
it later breaks somebody's automation.

| Surface | Committed shape |
|---|---|
| Stored asset | `replace_unit: "uses"`, `replace_also_every: {interval, unit}`, `use_noun`, `use_task_name`, `action` |
| Stored asset | A `uses` target is capped at 250, so a document carrying a larger one is rejected on import |
| Stored task | `recurrence_type: "use"` |
| Stored task | `source.part.role` of `"use"` / `"replace"`, absent meaning `"replace"` |
| Service input | `add_task` and `update_task` accept `recurrence_type: "use"` |
| Event payload | `home_keeper_task_completed` for a use carries the ordinary task spine; nothing new, but the *meaning* of a completion on this task type is now "1 use" |
| Panel | The `counted` status-bucket string, read by the card filter |
| Behaviour | The backstop is "whichever comes first" with no combinator |
| Behaviour | The completion trim. Once history is trimmed it is gone, and no export brings it back |

The bucket is **not** a Python surface. `profiles.py` matches on a status tier plus
`exclude_shopping`, and has no bucket concept — an earlier draft of this plan claimed
otherwise.

**Profiles need no new option either.** `matches_filter` opens with `if
task.get("next_due") is None: return False`, so a use task cannot match a Profile at
all — not even a `status: all` one. An `exclude_counted` toggle was drafted and then
cut: it would have been a stored one-way door that could never change an outcome. So a
use task appears on Home Keeper's own `todo` entity (which is not Profile-driven) and
stays off every Profile-synced list, which is the right split with no code.

---

## 8. Verification

Run in this order; do not use CI as the test runner.

```bash
source .venv/bin/activate
pytest tests/unit -v                       # pure logic
pytest tests/unit -m property              # invariants
mypy custom_components/home_keeper
bash ci/test-frontend.sh
bash ci/e2e-up.sh                          # docker + playwright
bash ci/test-mutation-python.sh            # >=80% on changed functions
bash ci/test-mutation-frontend.sh
vale README.md CHANGELOG.md                # whole files, not just added lines
```

New tests:

- `tests/unit/test_reconcile_uses.py` — the pair is created, the replacement task is
  born dormant, the count is right across a replacement, the backstop arms on time
  alone, the trim never eats a load-bearing entry, an orphan removes both tasks.
- `tests/unit/test_models_use.py` — a `use` task never gets a `next_due`, from
  `build_task` and from every `merge_update` path.
- `tests/unit/test_recurrence_use.py` — each of the 6 branch points leaves a `use`
  task's `next_due` at `None` instead of raising.
- `tests/unit/test_assets_part_uses.py` — field validation, the predicates, the 250
  ceiling, and that `"uses"` is refused as a floating task's `unit`.
- `tests/integration/test_use_tasks.py` — completing the use task arms the replacement
  at the target; the backstop arms it on time alone; completing the replacement
  restarts both halves; a use completion consumes **no** stock and does not stamp
  `last_replaced`; the use task stays off the calendar and on the to-do list. This tier
  is the one that can see the HA contracts, per the #183 lesson.
- `tests/e2e/tests/` — the Counted section renders and the Done button counts. A
  capture is documentation, not coverage, so assert on the section here as well as
  shooting it.

Screenshots (hard gate, desktop **and** phone) for: the Tasks list Counted section, the
part editor, and the appliance page part row. Add each to
`tests/e2e/screenshots.capture.ts` including its `setViewportSize(PHONE)` step, named
with a `-mobile-` segment. Extend `tests/e2e/walkthrough.capture.ts` to step through
creating a counted wear item and completing a use.

`README.md` gets a section under **Parts & wear items** with the use cases and a
screenshot. `.amazonq/rules/writing-style.md` gets a glossary row for **counted wear
item**.

---

## 9. Deferred

- **Automatic counting.** A counter that watches a state change and counts for you —
  "add 1 each time the washer reaches finished". This is G5's real prize and it is
  smaller under this design than under any other: a state change calls
  `complete_task`, and nothing new holds a number. Ship the manual path first.
- **A numeric usage source.** Binding a wear item to an existing entity — an odometer,
  a cycle sensor — so Home Keeper reads a number instead of counting taps. A real
  second shape, and not what #306 asks for.
- **A tag on a part.** `tags.py` already routes a scan to a task, so binding a tag to
  the use task needs nothing new; it is listed here only because it is worth a bullet
  of its own rather than being buried in this one.
- **An `all` combinator on the backstop.** "Not before 6 months *and* not before 25
  wears" is a real service interval on a machine. It is not a wear item, and the field
  can be added later without moving anything this plan commits.
