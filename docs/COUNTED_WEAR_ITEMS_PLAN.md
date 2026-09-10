# Counted wear items — implementation plan

> Closes the "manual usage counters" request in
> [#306](https://github.com/prestomation/ha-home-keeper/issues/306). Written September
> 2026, after the design dialogue on the issue and a mockup round.

---

## 1. The CHANGELOG entry this ships

Two bullets, because the naming half stands on its own.

```markdown
- **Counted wear items.** Set a wear item to repeat every so many uses instead of
  every so many months. Complete its use task from an automation, a tag scan or the
  panel to count 1 use, and the replacement task comes due when the count is reached.
  (Fixes #306)
- **Wear item actions.** Choose what a wear item's task is called: Replace, Clean,
  Service, Renew, Sharpen, Rotate or Inspect. An existing wear item keeps Replace.
```

`v0.23.0b1` is already tagged (`0db9983`), so this work opens **`0.23.0b2`**: bump
`manifest.json` and `const.PANEL_VERSION`, and add a `## [0.23.0b2]` section.

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

So Home Keeper stores no counter. **A use is a completion**, and
`home_keeper.complete_task` is already the "this happened" API — reachable from an
automation, a script, an NFC tag scan, the Done button, the per-task `button` entity,
the to-do list and a notification action. The count is the length of a list the store
already keeps, and each entry already carries a timestamp, a note, a cost, a photo and
who.

**No new service. No new entity. No new stored number. No new event.**

Mockups: `docs/mockups/306-*.png`.

---

## 3. Decisions already made

| | Decision | Why |
|---|---|---|
| **Two tasks** | A wear item measured in uses generates a **use task** and a **replacement task** | One task cannot mean both "I wore it" and "I renewed it". One task is also off by one: the 10th tap is the hike, not the wash |
| **Never due** | The use task carries `next_due: null` for its whole life | `isOverdue` is false with no `next_due`, so the filter pills, the overdue `binary_sensor`, the Profiles and the notifications all stay correct with no change. An always-due task would pin every one of them forever |
| **Its own section** | A `usage` status bucket, beside the `shopping` bucket that already gives a buy reminder its own section | `card-filter.statusBucket` line 150 is the precedent, and its comment is written for exactly this problem |
| **To-do list: yes** | The use task appears as an undated item | It is the one-tap surface people already have on their phone |
| **Calendar: no** | No change needed | The calendar builds events from `next_due`. No date, no event |
| **Retention** | Keep the newest `min(max(2 × replace_interval, 50), 500)` use completions, and never trim an entry newer than the last replacement | The load-bearing window is "uses since the last replacement"; trimming it would silently break the reminder. 2 intervals is what `usage_interval_stats` needs. Self-scaling, so no new option |

---

## 4. Data model

### 4.1 The part (`assets.py`)

`_normalize_part` gains 4 optional fields. All absent on every existing part, so there
is no migration.

| Field | Type | Meaning |
|---|---|---|
| `replace_unit` | now also `"uses"` | The existing field gains 1 value beside `days` / `weeks` / `months` |
| `use_noun` | `str` | What 1 use is called, singular: `wear`, `hike`, `cycle`. Empty means `use` |
| `use_task_name` | `str` | Optional override for the use task's name. Empty means the localized `Use {asset}` |
| `action` | closed set | `replace` (default) / `clean` / `service` / `renew` / `sharpen` / `rotate` / `inspect` |

`replace_interval` is reused as the target, unchanged.

New predicates beside `part_tracks_stock`:

```python
def part_counts_uses(part: dict) -> bool   # type == wear and replace_unit == "uses" and replace_interval
def part_use_noun(part: dict) -> str       # "wear", falling back to "use"
def use_retention_cap(part: dict) -> int   # min(max(2 * interval, 50), 500)
```

### 4.2 The two tasks (`reconcile.py`)

Both are reconciler-owned through the existing `source.part` key, so
`is_manual_part_link` and the orphan sweep keep working. They are told apart by a new
`source.part.role` of `"use"` or `"replace"`; an absent role reads as `"replace"`, so
every existing derived task keeps its identity with no migration.

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
- `recurrence_type: "triggered"` — dormant until armed, armed by the reconciler,
  completed by hand. This is the existing shape for "something else decides when this
  is due", and it already has the right to-do and calendar behaviour while dormant.
- Name from the action template: `Renew {part} ({asset})`.
- **It always exists**, dormant, rather than being minted at the target like a buy
  task. Its completion history is the renewal history — cost, note, photo, who — and a
  task that is deleted and re-minted each cycle loses it.

### 4.3 The count

Pure, in `reconcile.py`:

```python
def uses_since_replacement(use_task: dict, replace_task: dict) -> int
```

The count is the number of use-task completions whose `ts` is later than the
replacement task's `last_completed` (all of them when it has never been completed).

**Reset is implicit.** Completing the replacement task moves `last_completed` forward,
so the next count starts from zero with no field to write and nothing to keep in sync.

---

## 5. What arms the replacement task

The count changes on a completion, which is a store mutation, not an asset edit — so
the reconciler alone is not enough. This mirrors stock exactly: an `adjust_part_stock`
crossing may create or retire a buy task, and `coordinator.async_settle_buy_tasks()` is
the settle step.

Add `coordinator.async_settle_use_tasks()`, called from the same places
`async_settle_buy_tasks` is called, plus after any completion of a part-derived use
task. It:

1. recomputes the count for each counted wear item,
2. calls `store.trigger_task` on the replacement task when the count reaches the
   target and it is dormant (this fires the existing `home_keeper_task_triggered`),
3. trims the use task's completion list to `use_retention_cap`, never removing an entry
   newer than the last replacement.

Completing the replacement task early, while the count is below the target, is allowed
and simply restarts the count — the same rule a usage task already follows, where Done
re-anchors the meter.

---

## 6. Files to change

### Backend

| File | Change |
|---|---|
| `const.py` | `REC_USE`, `UNIT_USES`, `PART_ACTIONS`, `USE_TASK_NAME_TEMPLATES`, `ACTION_TASK_NAME_TEMPLATES` (16 locales each), `USE_RETENTION_*` limits, `PANEL_VERSION` bump |
| `models.py` | `RECURRENCE_TYPES` gains `REC_USE`; `normalize_fields` early-returns for it; `build_task` forces `next_due = None`; `merge_update` never recomputes it |
| `assets.py` | The 4 part fields, their validation, `part_counts_uses`, `part_use_noun`, `use_retention_cap` |
| `reconcile.py` | Build both tasks, the `role` key, `uses_since_replacement`, the trim rule, orphan handling for the pair |
| `store.py` | Settle after a use completion |
| `coordinator.py` | `async_settle_use_tasks` |
| `todo.py` | Leave `REC_USE` out of the dateless-drop tuple, with a comment saying why |
| `calendar.py` | No change. Add an assertion that a `use` task yields no event |
| `manifest.json` | Version bump |

`api_surface.py` needs **no** new `ServiceSpec` or `EventSpec` — the feature adds
neither. Confirm `test_api_surface.py` stays green rather than assuming it.

`transfer.py` needs no change: new part fields ride the export automatically, and
`tests/unit/test_transfer_roundtrip.py` is what proves it.

### Frontend

| File | Change |
|---|---|
| `card-filter.ts` | A `usage` bucket in `statusBucket`, above the `shopping` line |
| `panel-types.ts` | `usage` in `PANEL_BUCKETS` |
| `panel-controls.ts` | The Usage filter pill and its scope |
| `panel-lists.ts` | The use row: meta line, the `17 of 25 wears` status chip, keep Done |
| `panel-detail.ts` | The count chip and meter on the appliance page's part row |
| `forms.ts` | `uses` in the unit selector; the `use_noun`, `use_task_name` and `action` fields; the summary line naming both generated tasks |
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
| Stored asset | `replace_unit: "uses"`, `use_noun`, `use_task_name`, `action` |
| Stored task | `recurrence_type: "use"` |
| Stored task | `source.part.role` of `"use"` / `"replace"`, absent meaning `"replace"` |
| Service input | `add_task` and `update_task` accept `recurrence_type: "use"` |
| Event payload | `home_keeper_task_completed` for a use carries the ordinary task spine; nothing new, but the *meaning* of a completion on this task type is now "1 use" |
| Panel + Profiles | The `usage` status-bucket string, read by the card filter and by Profile matching in both TypeScript and Python |
| Behaviour | The completion trim. Once history is trimmed it is gone, and no export brings it back |

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
bash ci/test-mutation-python.sh            # ≥80% on changed functions
bash ci/test-mutation-frontend.sh
vale README.md CHANGELOG.md                # whole files, not just added lines
```

New tests:

- `tests/unit/test_reconcile_uses.py` — the pair is created, the count is right across a
  replacement, the trim never eats a load-bearing entry, an orphan removes both tasks.
- `tests/unit/test_models_use.py` — a `use` task never gets a `next_due`, from
  `build_task` and from every `merge_update` path.
- `tests/unit/test_assets_part_uses.py` — field validation and the predicates.
- `tests/integration/test_use_tasks.py` — completing the use task arms the replacement
  at the target; completing the replacement restarts the count; the use task stays off
  the calendar and on the to-do list. This tier is the one that can see the HA
  contracts, per the #183 lesson.
- `tests/e2e/tests/` — the Usage section renders and the Done button counts. A capture
  is documentation, not coverage, so assert on the section here as well as shooting it.

Screenshots (hard gate, desktop **and** phone) for: the Tasks list Usage section, the
part editor, and the appliance page part row. Add each to
`tests/e2e/screenshots.capture.ts` including its `setViewportSize(PHONE)` step, named
with a `-mobile-` segment. Extend `tests/e2e/walkthrough.capture.ts` to step through
creating a counted wear item and completing a use.

`README.md` gets a section under **Parts & wear items** with the use cases and a
screenshot.

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

---

## 10. A rule this work has to settle

`AGENTS.md` says: *"Never comment on a GitHub issue … Adding a comment to an issue by
hand, or by asking an agent to, is still off-limits."*

The mockups for this feature were posted to #306 by an agent at the maintainer's
request. Either the rule is amended to allow maintainer-directed posts, or that was a
one-off and the rule stands. Decide before the implementation PR, and make the change
in `AGENTS.md` (and `.amazonq/rules/` if it becomes a convention) in the same PR, so
the next session does not have to guess.
