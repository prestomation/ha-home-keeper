# Sensor-Based Tasks (usage meters + numeric thresholds)

**Status: proposed.** This plan adds a new recurrence kind whose due-state is
derived by Home Keeper from a bound **numeric sensor** instead of (or alongside)
the clock. Today a task can recur by elapsed *time* (`floating` / `fixed`), be a
one-shot (`one-off`), or be armed/cleared by an external owner (`triggered`). A
sensor-based task closes the obvious maintenance gap: "service this after **N
hours of runtime** / **N km** / **N cycles**", or "raise this the moment a reading
**crosses a limit**" — derived automatically from an existing Home Assistant
entity, with no automation to wire up.

The design deliberately reuses the machinery already proven by the **triggered**
recurrence type and the **`device_class: problem` binary-sensor sync**
(`problem_tasks.py` / `problem_sync.py`): a sensor task's `next_due` *is* its state
(`None` = dormant, a timestamp = armed/due-now), so it slots into every existing
time surface (to-do list, calendar, per-task device entities, `*_overdue` events)
with zero new surface work. What is new is a small, pure **evaluator** that maps a
live sensor reading + the task's stored state to an arm/clear decision, plus an
HA-aware **watcher** that feeds it.

---

## 1. What already exists (and what this reuses)

- **The armed/dormant state model.** `REC_TRIGGERED` already encodes exactly the
  state a sensor task needs: `next_due = None` (dormant, invisible to every time
  surface) vs. `next_due = <timestamp>` (armed/due-now). See `const.py`
  (`REC_TRIGGERED`) and `recurrence.compute_next_due` / `apply_completion`'s
  triggered branch. Sensor tasks adopt the same convention — no new "due" surface.
- **A sensor → task precedent.** `problem_sync.py` enumerates eligible
  `binary_sensor` entities, subscribes to their state changes
  (`async_track_state_change_event`) and entity-registry updates, and drives a
  **pure** reconciler (`problem_tasks.reconcile_problem_tasks`) that the store wraps
  with persistence + events. The HA-free/HA-aware split and the live-subscription
  lifecycle (`async_on_unload`, resubscribe on registry change) are the template
  for the sensor **watcher** — with one key simplification (see §4).
- **Edge-triggered baselining.** `transitions.detect_transitions` (driven from the
  coordinator) already fires each time-based transition *once* per `next_due`, and
  is silently baselined on startup so a restart never replays a storm. The
  threshold evaluator borrows the same "remember last observed state in coordinator
  memory, baseline on startup" pattern for crossing detection.
- **Per-recurrence validation + editor branches.** `models.normalize_fields`
  already early-returns per recurrence type (triggered carries no schedule; one-off
  carries only `due`), and `forms.ts` (`taskSchema` / `taskFormData` /
  `buildTaskPayload`) already renders distinct fields per type. Sensor tasks add one
  more branch in each.
- **Service-first convention.** `add_task` / `update_task` already accept the full
  task shape; we extend their schema (with `services.yaml` + `strings.json` parity)
  rather than inventing a side channel. No new options-flow toggle is needed because
  sensor tasks are **user-created**, not auto-synced (§4).

---

## 2. Product shape — two modes in v1

A new recurrence type **`sensor`** (`REC_SENSOR = "sensor"`), carrying a `sensor`
config block on the task dict. v1 ships two evaluation modes:

### 2a. `usage` — a meter, generalizing `floating` from time to sensor units

The headline maintenance case. `floating` says "due `interval·unit` after the last
completion"; `usage` says "due after the bound meter advances `target` **units**
since the last completion". Examples:

- Oil change after **15,000 km** (bind to an odometer `sensor`).
- Filter / belt service after **500 hours** of runtime (bind to a runtime-hours
  sensor, e.g. from a utility-meter or a device's own hours counter).
- Descale after **50 cycles** (bind to a monotonically rising cycle counter).

Math (pure, robust to meter resets):

```
delta = current_reading - baseline
armed when delta >= target
```

`baseline` is the reading captured at **creation** and **reset to the current
reading on completion** — i.e. completing the task "resets the counter", exactly
like `floating` resets its clock. If `current_reading < baseline` (the meter was
reset / rolled over / replaced), re-baseline to the current reading so the task
doesn't get stuck armed forever. (A future enhancement can predict a real
`next_due` date from the historical rate of change so usage tasks also feed
"due-soon"/calendar; v1 keeps `next_due` as armed-now/dormant — see §8.)

### 2b. `threshold` — armed on a numeric crossing

"Raise this when a reading crosses a limit." Examples:

- Replace filter when airflow drops **below 60 %**.
- Check coolant when temperature climbs **above 90 °C**.

Config: a `comparison` (`>=`, `<=`, `>`, `<`, `==`, `!=`) against a fixed `value`,
with an optional **`for_seconds`** hold (the condition must stay true that long
before arming, to debounce noisy sensors), and an optional **`attribute`** so the
reading can come from an entity attribute instead of its state (e.g.
`climate.living_room` → `current_temperature`).

Semantics — **arm on the crossing edge, clear on completion** (not on recovery):

- Arm on a `false → true` transition of the comparison (after the optional hold).
- Once armed it **stays** armed until the user completes it — a filter you need to
  replace doesn't un-need replacing just because airflow briefly recovered.
- After completion the task goes dormant and re-arms only on a *fresh* crossing
  (the edge must go false then true again). This makes it a maintenance *trigger*,
  distinct from the problem-sensor mirror, which tracks the live condition and
  auto-clears on recovery. (A `clear_on_recover` flag to opt into mirror-style
  behaviour is a deferred enhancement — §8.)

Both modes share the triggered state model, so an armed sensor task shows in the
to-do list, on the calendar (as due-now), lights the per-task overdue
binary_sensor, and fires `home_keeper_task_overdue` — all for free.

---

## 3. Data model & pure layer

### Task dict — new `sensor` block

```jsonc
"sensor": {
  "entity_id": "sensor.car_odometer",
  "mode": "usage",                 // "usage" | "threshold"
  "attribute": null,               // optional: read this attribute instead of state
  // usage:
  "target": 15000,                 // arm when current - baseline >= target
  "baseline": 41230.0,             // reading at creation / last completion
  // threshold:
  "comparison": ">=",              // >=, <=, >, <, ==, !=
  "value": 90.0,
  "for_seconds": 0                 // optional hold before arming
}
```

Only the keys relevant to `mode` are stored. The block is additive and read with
`.get()`, so no storage migration is needed (`STORAGE_VERSION` unchanged).

### `models.py`

- `normalize_fields`: add a `REC_SENSOR` branch (alongside the existing `triggered`
  / `one-off` early returns) that validates the `sensor` block: `entity_id`
  required and well-formed; `mode ∈ {usage, threshold}`; per-mode required fields
  (`target > 0` for usage; `comparison ∈ COMPARISONS` + numeric `value` for
  threshold); `for_seconds >= 0`; `attribute` optional string. Reject unknown
  modes/comparisons loudly at the edge (raise `TaskValidationError`, localized via
  `strings.json` → `exceptions`).
- `build_task`: for a usage task with no explicit `baseline`, leave it `None` so the
  watcher stamps it from the live reading on first evaluation (the store/watcher is
  HA-aware; `models` stays HA-free).
- `merge_update`: carry the `sensor` block through edits; treat `recurrence_type ==
  REC_SENSOR` like `REC_TRIGGERED` for the "don't recompute `next_due` from a
  schedule" guard (sensor `next_due` is owned by the evaluator, not schedule math).

### `recurrence.py`

- `compute_next_due`: `REC_SENSOR` → `now` (arming reads as due-now, mirroring the
  triggered branch). The evaluator decides *whether* to arm; this only ever (re)arms.
- `apply_completion`: `REC_SENSOR` → `next_due = None` (dormant), like triggered.
  Baseline reset for usage is the store's job (it has the live reading); recurrence
  stays pure. History is still recorded so cadence accumulates.
- `remove_completion`: treat `REC_SENSOR` like `REC_TRIGGERED` (armed/dormant state
  is sensor-driven, not history-driven — undoing a completion must not re-arm).

### New pure module `sensor_tasks.py` (HA-free, unit-tested)

Mirrors `problem_tasks.py` — a pure transformation over plain dicts + readings:

```python
def sensor_config(task) -> dict | None          # task["sensor"] accessor
def bound_entity_id(task) -> str | None

# Returns one of "arm" | "rebaseline" | None plus any baseline change.
def evaluate_usage(task, *, reading: float, now) -> Decision
# Returns "arm" | None plus the new condition_met edge flag.
def evaluate_threshold(task, *, reading: float, condition_met_prev: bool,
                       crossed_at: datetime | None, now) -> Decision
```

`evaluate_threshold` keeps the `false→true` edge and the `for_seconds` hold in the
returned state (held in coordinator memory, baselined on startup — never persisted,
so a restart can't spuriously arm). `evaluate_usage` is stateless beyond the
persisted `baseline`.

---

## 4. HA-aware layer — `sensor_watcher.py`

Mirrors `ProblemSensorSync`'s lifecycle but is **simpler in one important way**:
sensor tasks are **user-created** (the user picks the entity + condition in the
editor or via `add_task`), so the watcher does **not** enumerate the registry,
auto-create/delete tasks, or need exclusion options / entry reloads. It only
*evaluates existing sensor tasks*. That removes the whole reconcile-then-reload
dance that `problem_sync` needs.

Responsibilities:

1. **Track the bound entity set.** Collect `bound_entity_id(task)` across all
   enabled `REC_SENSOR` tasks; `async_track_state_change_event` on that set.
   Resubscribe when tasks change (hook the existing coordinator refresh / a store
   listener) — same `async_on_unload` teardown as `problem_sync`.
2. **Evaluate on state change.** When a bound entity changes, read its numeric
   state (or `attribute`), run the evaluator for each task bound to it, and apply
   the decision through the store (§5).
3. **Periodic re-evaluation.** Piggy-back on the coordinator's 5-minute
   `_async_update_data` to re-evaluate all sensor tasks. This covers `for_seconds`
   holds (re-check after the hold elapses) and any reading that changed without a
   delivered event. For tighter holds, optionally schedule an
   `async_track_point_in_time` at `crossed_at + for_seconds` (v1 may rely on the
   5-minute tick and document the granularity).
4. **Unavailable handling.** A bound entity that is `unknown`/`unavailable`/missing
   is skipped (no arm/clear); optionally surface a repair issue after a grace
   period (deferred — §8), reusing the orphan-detection spirit of `managed_by`.

Wiring in `__init__.py` mirrors `problem_sync`: construct after first refresh,
attach to the coordinator, start listeners **after** platforms forward and **after**
`enable_transition_events()` so boot silently baselines (no overdue storm).

---

## 5. Store integration (`store.py`)

- **Arming.** Generalize `trigger_task` to also accept `REC_SENSOR` (today it
  rejects non-triggered types), so arming a sensor task reuses the existing
  `EVENT_TASK_TRIGGERED` path and the `origin` authorization marker. The watcher
  passes an internal origin (cf. `ORIGIN_PROBLEM_SENSOR_SYNC`) so user surfaces
  can't manually arm a sensor task out of band.
- **Clearing = completion.** Completion already flows through `complete_task` →
  `recurrence.apply_completion` (sets `next_due = None` for `REC_SENSOR`). For a
  **usage** task, `complete_task` additionally **re-stamps `sensor.baseline`** from
  the live reading (the store is HA-aware) so the meter resets. A small,
  well-commented addition at the single completion chokepoint.
- **Baseline bootstrap.** A new helper (called by the watcher) stamps an initial
  `baseline` for a usage task whose `baseline is None`, persisting once.
- No new reconciler/`reconcile_*` method is required (no auto-creation). Evaluation
  results are applied via the existing `trigger_task` / `complete_task`
  chokepoints, so all existing events fire unchanged.

`coordinator.py`: call the watcher's evaluation pass from `_async_update_data`
(after `_purge_expired_one_offs`), and keep the bound-entity subscription in sync.

---

## 6. Frontend (`forms.ts` + panel) — UI gate applies

- **`taskSchema`**: add `sensor` to the recurrence-type selector and a new
  conditional branch rendering: an **entity picker** (numeric domains — `sensor`,
  `number`, `input_number`, `counter`), an optional **attribute** field, a **mode**
  select (`usage` / `threshold`), and the mode's fields — `target` for usage;
  `comparison` + `value` + `for` (seconds) for threshold.
- **`taskFormData` / `buildTaskPayload`**: map the `sensor` block to/from the form
  (a nested object, like the cadence subfields), emitting only the keys for the
  chosen mode.
- **Task detail page**: show **progress** for a sensor task — usage as
  "`current − baseline` / `target` units" (a small bar + remaining), threshold as
  "current vs. limit". Reuse the existing detail-page rendering; escape all
  user/sensor content (`escapeHTML`).
- **(Optional) per-task `sensor` entity** exposing usage progress / remaining as a
  real HA entity (reuse the per-task `sensor` platform), so "remaining < 10 % →
  notify" works without the panel. Nice-to-have; can land in a follow-up.
- **Hard gate:** any PR touching `frontend/src/` must capture Playwright
  screenshots of the new editor branch (and detail progress) under `docs/images/`
  and embed them in the PR body (see AGENTS.md "Workflow"). Add a capture step for
  the sensor-task editor to `tests/e2e/screenshots.capture.ts`.

---

## 7. Services, events, docs, quality

- **`services.yaml` + `strings.json`**: extend `add_task` / `update_task` with the
  sensor fields (`sensor_entity_id`, `sensor_mode`, `sensor_attribute`,
  `sensor_comparison`, `sensor_value`, `sensor_for`, `sensor_target`), with full
  localization parity, and document them in the field descriptions. Add any new
  validation messages under `exceptions`.
- **Events**: no new event types — arming fires `EVENT_TASK_TRIGGERED`, clearing
  fires `EVENT_TASK_COMPLETED`, and the periodic transition fires
  `EVENT_TASK_OVERDUE` exactly as for triggered tasks. Document the sensor-task
  lifecycle in `docs/EVENTS.md` (which events to expect, in what order).
- **`README.md`**: new "Usage- & sensor-based tasks" section with the use cases
  (runtime/distance/cycle meters; numeric thresholds), how to create one (panel +
  service), and screenshot(s) under `docs/images/` (relative path). Documenting a
  headline feature in README is a hard gate (AGENTS.md).
- **`docs/INTEGRATING.md`**: note that, alongside external `triggered` tasks and the
  automatic problem-sensor mirror, Home Keeper can self-derive due-state from a
  numeric sensor; clarify that this is internal (no contribution API needed).
- **`.amazonq/rules/`**: record the new recurrence type and the "evaluator is pure,
  watcher is HA-aware, no auto-creation" convention so both Amazon Q and Claude pick
  it up (AGENTS.md requires rules to move with conventions).
- **Typing / quality scale**: keep `mypy` clean (run locally with HA installed),
  update `quality_scale.yaml` if a rule's status changes, localize all user-facing
  exceptions.
- **`CHANGELOG.md`**: add an `### Added` entry (user-facing feature).

---

## 8. Explicitly deferred (with hook points)

Kept out of v1 to keep it reviewable; each has a natural seam:

- **State-change counting** ("descale after 50 on/off cycles"). A variant of
  `usage` where the "meter" is a persisted count of tracked transitions rather than
  a numeric reading. Needs a persisted counter (incremented in the watcher's
  state-change callback) — slot a `mode: "count"` into the same `sensor` block.
- **Compound conditions** (AND/OR across multiple sensors). Generalize the `sensor`
  block to a list of conditions + a combinator; the evaluator already returns a
  single decision, so it can fold a list.
- **Predicted `next_due` for usage** — derive a real future due date from the
  historical rate of change (using `completions[]` cadence) so usage tasks feed
  "due-soon"/calendar like time-based ones. Pure addition to the evaluator.
- **`clear_on_recover`** — opt a threshold task into mirror-style behaviour
  (auto-clear when the reading recovers), bridging toward how the problem-sensor
  sync behaves. One flag + one evaluator branch.
- **Unavailable-entity repair issues** — surface a Home Assistant repair when a
  bound entity goes missing past a grace period (reuse the `managed_by` orphan
  spirit).
- **Time-based fallback safety net** — let a sensor task also carry a
  floating/fixed cadence as a backstop ("or every 12 months, whichever first").
  Additive on top of the `sensor` block.

---

## 9. Tests

Mirror the existing split (unit = pure, integration = HA runtime, e2e = browser):

- **`tests/unit/test_models.py`**: sensor-block validation (good/bad modes,
  comparisons, missing `target`/`value`, negative `for_seconds`).
- **`tests/unit/test_sensor_tasks.py`** (new): `evaluate_usage` (arm at target,
  meter reset re-baseline, exact-boundary) and `evaluate_threshold` (each
  comparison, `false→true` edge only, `for_seconds` hold, attribute read, re-arm
  only after going false, dormant after completion).
- **`tests/unit/test_recurrence_*`**: `apply_completion` / `compute_next_due` /
  `remove_completion` for `REC_SENSOR` (dormant on completion, due-now on re-arm,
  undo doesn't re-arm).
- **`tests/integration/test_sensor_watcher.py`** (new): a state change arms the
  task; completion clears it and re-baselines a usage task; the periodic pass
  honours a `for` hold; an `unavailable` entity is skipped; boot baselines without a
  spurious arm.
- **`tests/e2e/`**: create a sensor task through the editor and assert it renders;
  add the capture step + screenshot.

Run `pytest tests/unit -v`, the full HA-backed suite, `mypy`, and the e2e harness
locally before pushing (AGENTS.md — never use CI as the test runner).

---

## 10. Suggested order

1. `const.py` (`REC_SENSOR`, `COMPARISONS`, internal origin) + `models.py`
   validation + `recurrence.py` branches — with unit tests.
2. Pure `sensor_tasks.py` evaluator — with unit tests.
3. `store.py` (`trigger_task` accepts sensor; `complete_task` re-baselines usage;
   baseline bootstrap) — with unit/integration tests.
4. `sensor_watcher.py` + `coordinator.py` + `__init__.py` wiring — integration
   tests.
5. `services.yaml` + `strings.json` + exceptions.
6. `forms.ts` editor branch + detail progress (+ optional per-task sensor entity) —
   **screenshots**.
7. Docs (`README.md`, `EVENTS.md`, `INTEGRATING.md`, `.amazonq/rules/`,
   `CHANGELOG.md`) + e2e capture step.
</content>
</invoke>
