# Usage-based maintenance: gap analysis

> **Purpose:** Compare Home Keeper's sensor-based tasks against
> [`BambamNZ/maintenance-tracker`](https://github.com/BambamNZ/maintenance-tracker), a
> purpose-built HA integration for usage-based maintenance reminders — then work out
> which missing *primitives* were worth building, and what else each one unlocks
> beyond the case that prompted it. Written August 2026, alongside the 0.12.0 work
> that closed the top two gaps.

---

## Contents

1. [Why this comparison](#why-this-comparison)
2. [What `maintenance-tracker` does](#what-maintenance-tracker-does)
3. [Parity matrix](#parity-matrix)
4. [The gaps](#the-gaps)
5. [Primitives — shipped and proposed](#primitives--shipped-and-proposed)
6. [Use cases each primitive unlocks](#use-cases-each-primitive-unlocks)
7. [Bambu Lab: the case that prompted this](#bambu-lab-the-case-that-prompted-this)

---

## Why this comparison

David Venter (`BambamNZ`) built a whole integration to answer a question Home Keeper
claims to answer: *"remind me when this machine has run long enough to need
servicing."* His worked example — *"P2S Nozzle Clean"*, driven off a Bambu Lab
printer's cumulative hours sensor — is squarely in our problem space.

That is the useful kind of competitor: not a broad rival, but a sharp instrument built
by someone who hit a specific wall. Reading it as a **requirements document** tells us
exactly which walls exist.

Three of them turned out to be real, and none of them were "Home Keeper can't do
usage-based maintenance" — it has had `recurrence_type: "sensor"` with `mode: "usage"`
since 0.9. They were narrower and more embarrassing than that.

---

## What `maintenance-tracker` does

Nine modules, MIT, one config entry per schedule — HA's own **helper pattern**
(Threshold, Utility Meter), not one entry per device. Several schedules can hang off
one sensor.

| Piece | Behaviour |
|---|---|
| `store.py` | Persists `{baseline_hours, last_service_date, notified}` per entry in its own `.storage` file. The docstring is explicit about why: recorder history and `RestoreState` are both wrong tools for an indefinitely growing service log. |
| `config_flow.py` | Name + source sensor + **hours threshold** and/or **days threshold** + **logic** (`or` default / `and`) + notify toggle. At least one threshold required. Options flow retunes all of it in place. |
| `data.py` | Reacts to source-sensor state changes (no polling). `is_due` = `hours_since ≥ threshold_hours` combined per `logic` with `days_since ≥ threshold_days`. |
| `sensor.py` | Four sensors: hours since service, days since service, hours remaining, days remaining. "Remaining" reports `unavailable` rather than a misleading `0` when its threshold isn't configured. |
| `binary_sensor.py` | `service_due`, device_class `problem`, exposing every raw figure as attributes for dashboards/automations. |
| `button.py` | Reset — re-baselines hours to the current reading, restarts the day count, clears the notification. |

It is a **signal**, not a task manager: no completion history, no notes/cost/photo, no
appliance metadata, no calendar or to-do surface. You bring your own automation.

---

## Parity matrix

| Capability | `maintenance-tracker` | Home Keeper *before* 0.12 | Home Keeper *now* |
|---|---|---|---|
| Meter-based due ("every N units of use") | ✅ hours only | ✅ any numeric entity or attribute | ✅ |
| **Time backstop ("…or every N months")** | ✅ `threshold_days` | ❌ **no cadence at all on a sensor task** | ✅ `sensor.also_every` |
| **AND/OR between the two** | ✅ `logic` | ❌ | ✅ `sensor.combinator` (`any` / `all`) |
| Backstop fires while the sensor is offline | ✅ (day count is wall-clock) | ❌ n/a | ✅ evaluated with no reading |
| Progress readable at a glance | ✅ four sensors | ⚠️ one unlabelled string | ✅ meter bar + `usage_*` attributes |
| Unit label on the target | ✅ inherited from source | ❌ bare number | ✅ `sensor.unit`, prefilled from the entity |
| Reset the counter without "completing" | ✅ button | ⚠️ undocumented `baseline` write | ✅ `home_keeper.set_task_meter` |
| Many schedules per sensor | ✅ one entry each | ✅ plain tasks | ✅ |
| Meter reset / replacement handled | ⚠️ manual button only | ✅ auto, debounced over two ticks | ✅ |
| Completion **history** (when, who, cost, note, photo) | ❌ | ✅ | ✅ |
| To-do / calendar / mobile actionable notifications | ❌ | ✅ | ✅ |
| Appliance metadata, parts, stock draw-down | ❌ | ✅ | ✅ |
| Ownership by a managing integration (`managed_by`) | ❌ | ✅ | ✅ |
| Predicted due date from observed usage rate | ❌ | ❌ | ❌ **(open — see G3)** |
| Cycle / state-change counting | ❌ (needs a numeric sensor) | ❌ | ❌ **(open — see G5)** |

---

## The gaps

### G1 — "300 hours **or** 6 months, whichever first" *(closed in 0.12.0)*

The blocking one. `models.normalize_fields` early-returns for `REC_SENSOR`, so a
sensor task carried **no `interval`/`unit` at all**. Every real service interval in a
manual has two halves, because wear happens whether the machine runs or not.

It was already on our own deferred list (`SENSOR_TASKS_PLAN.md` §8, *"Time-based
fallback safety net"*) — `maintenance-tracker` is evidence that the deferral was
costing users, not just polish.

**Shipped as** `sensor.also_every: {interval, unit}` + `sensor.combinator`. Two design
points worth recording:

- **Anchored to `last_completed`, falling back to the task's `created`** — deliberately
  *not* to the meter baseline. A meter reset (a replaced controller, a rolled-over
  counter) is not a service, and must not silently push the calendar half out.
- **Evaluated even when the bound entity is unavailable.** The watcher used to
  `continue` on a missing reading. That is exactly the state an idle or unplugged
  machine sits in — the one whose annual service you most want to hear about. Now a
  usage task with a backstop is evaluated with `reading=None`; the meter half simply
  can't be met, and the baseline is left alone.

### G2 — Progress was a bare string *(closed in 0.12.0)*

The panel rendered `"120 of 300 used (sensor.x)"`. No unit (none was stored), no bar,
and the per-task next-due sensor entity exposed no baseline/target/remaining at all.
`maintenance-tracker` shipped four numeric entities for precisely this.

**Shipped as** a `sensor.unit` display label (prefilled in the panel from the bound
entity's `unit_of_measurement`), a progress bar with a *"180 h to go"* line, and
`usage_consumed` / `usage_remaining` / `usage_percent` / `usage_target` / `usage_unit`
/ `backstop_due` attributes on the task's existing next-due sensor. One entity per task
with attributes, rather than four new entities per task, keeps Home Keeper's entity
model intact while making the numbers automatable.

While in there: the dashboard card's recurrence filter was missing `one-off` and
`sensor` entirely.

### G3 — No predicted due date *(open — now the top gap)*

Sensor tasks are excluded from the calendar, hidden from the to-do list while dormant,
and `home_keeper_task_due_soon` can never fire (they go 0 → due-now with no lead time).
So a usage task is **invisible until the instant it fires**.

`maintenance-tracker` doesn't solve this either — but with `also_every` shipped, half
the problem is already solved: `sensor_tasks.backstop_due()` returns a real timestamp.
The remaining half is projecting the *meter* from an observed rate of change
(`completions[]` cadence, or recorder history), which would give "due in about three
weeks at your current print rate" for every use case below.

### G4 — No explicit meter reset *(closed in 0.12.0)*

Writing `sensor.baseline` through `update_task` worked, but was undocumented, and
AGENTS.md requires every data action to be a service. **Shipped as**
`home_keeper.set_task_meter`. Note the watcher's own baseline bookkeeping stays silent
(internal state); a *user* reset fires `home_keeper_task_updated`.

Home Keeper's answer is arguably better than a reset button: completing the task
already re-baselines **and** records what happened, so the reset service is the
narrower "I did it before you were watching" escape hatch rather than the primary path.

### G5 — No cycle counting *(open)*

"Descale every 50 dishwasher cycles" needs a persisted count of tracked state
transitions, not a numeric sensor. Deferred at `SENSOR_TASKS_PLAN.md` §8 as
`mode: "count"`. `maintenance-tracker` can't do this either — it *requires* a
monotonic numeric sensor — so this is beyond parity, and it gates a large class of use
cases (see below).

Today the workaround is a `counter` helper plus an automation, which works because the
entity picker is unfiltered and the meter-reset debounce handles the user zeroing it.

### G6 — Repair issue for a vanished bound entity *(open, low)*

Neither side notices when a bound entity disappears. `SENSOR_TASKS_PLAN.md` §8.

### Non-gaps

Worth stating so we don't over-build toward a competitor that is smaller by design:
notification parity (our actionable notifications and full event lifecycle exceed a
persistent notification), many-schedules-per-sensor, and meter-reset handling (ours is
automatic and debounced; theirs is a manual button) were already ahead.

---

## Primitives — shipped and proposed

| | Primitive | Status |
|---|---|---|
| **P1** | Time backstop on a usage task (`also_every` + `combinator`) | ✅ 0.12.0 |
| **P2** | Progress as data (`unit` label, `usage_*` attributes, meter bar) | ✅ 0.12.0 |
| **P3** | Predicted `next_due` for usage, from observed rate of change | Proposed — highest value |
| **P4** | `set_task_meter` service | ✅ 0.12.0 |
| **P5** | `mode: "count"` — persisted state-change counter | Proposed |
| **P6** | Compound conditions across multiple sensors | Proposed (stretch) |

---

## Use cases each primitive unlocks

Grouped by the primitive that gates them. Every sensor named here exists in Home
Assistant today, via a core or popular HACS integration.

### Unlocked by P1 (usage **or** time) — the largest class

This is the shape almost every manufacturer's service schedule is written in.

- **Car oil change every 8,000 km *or* 12 months** — odometer from an OEM/OBD
  integration. The single most-requested version of this, and unexpressible before.
- **Cabin and engine air filter every 15,000 km *or* 24 months**; brake fluid strictly
  by time on the same appliance.
- **HVAC filter every 500 run-hours *or* 3 months** — run-hours via a `history_stats`
  helper on the fan.
- **Whole-house water filter every 4,000 L *or* 6 months** — water meter.
- **Standby generator: monthly test run *and* every 100 engine hours** — the
  `combinator: "all"` case, where neither half alone should trigger the work.
- **Mower / chainsaw / outboard engine oil every 50 run-hours *or* annually** —
  seasonal equipment that sits idle all winter is precisely what the
  offline-evaluation fix is for.
- **Solar inverter fan clean per MWh produced *or* annually.**

### Unlocked by P5 (cycle counts)

- **Dishwasher descale every 50 cycles**; washing-machine drum clean every 40 washes.
- **Espresso machine: descale every 300 brews, backflush every 100 shots.**
- **Garage door opener service every 5,000 open/close cycles.**
- **Sump / well pump: impeller check every N starts** — short-cycling is itself an
  early failure signal.
- **Home battery recondition every N charge cycles.**

### Already expressible, but only *visible* with P2/P3

These worked before and read better now; P3 is what would put them on the calendar and
in the weekly digest instead of appearing the moment they're already due.

- Robot vacuum brush every 200 h, filter every 50 h, mop pad by area cleaned.
- Pool pump run-hours, plus filter backwash on a pressure **threshold**.
- CPAP filter by hours of use; air-purifier filter by run-hours or filter-life %.
- Aquarium UV bulb by run-hours; water change by volume.
- Laser-cutter lens clean and CNC spindle service by spindle hours.
- Every 3D-printer item in the section below.

### The through-line

P1 turns Home Keeper from "time-based chores, plus a niche meter mode" into a general
**duty-cycle maintenance tracker** — the thing that knows a machine's schedule is
written in two units at once. P3 is what makes that visible *before* it's overdue,
which is the whole point of a reminder.

---

## Bambu Lab: the case that prompted this

`IDEAS.md` said no cumulative counter existed for these printers. **It was wrong.**
`greghesp/ha-bambulab` exposes `sensor.<printer>_total_usage_hours`:
`SensorStateClass.TOTAL_INCREASING`, `SensorDeviceClass.DURATION`, hours,
`EntityCategory.DIAGNOSTIC`, no per-model `exists_fn` gate (only `available_fn`-gated
on the printer reporting `info.usage_hours`).

It counts **printer usage hours, not strictly print hours** — worth saying plainly in
user-facing copy — but that is close enough for a service interval, and it is exactly
the sensor `maintenance-tracker` was pointed at.

So the companion glue (`ha-home-keeper-bambu-lab`) can bind maintenance tasks straight
to it with no synthesized `utility_meter` / `history_stats` helper. That work — an
opinionated catalog of printer maintenance items with sourced default intervals, each
individually enableable and user-adjustable — is designed in that repo's
`docs/MAINTENANCE_CATALOG_PLAN.md`. It reverses the glue's previous roadmap position
that wear data should be *"modeled in the Bambu Lab integration itself, not invented
here"*: `maintenance-tracker` is evidence that people will happily pick an interval
themselves, and a good default beats a blank field.
