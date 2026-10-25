---
title: Cost totals
summary: Maintenance spend and appliance purchase totals, as sensors and in the panel.
implements:
  - custom_components/home_keeper/cost_summary.py
  - custom_components/home_keeper/frontend/src/panel-spend.ts
related: [completions, appliances, coordinator-entities, frontend]
source_hash: ae6fd0bcd39f
---

# Cost totals

A completion can record a `cost` ([completions](completions.md)), and an appliance can
record its purchase `cost` ([appliances](appliances.md)). Home Keeper adds them up. The
totals are sensors for dashboards and automations, and a strip above the task list in the
panel.

## Goals

- **G1. 1 calculation.** The sensors and the panel get their numbers from the same pure
  functions, so they always agree.
- **G2. Totals follow the data.** A new, changed or deleted cost changes the totals with no
  action from the user.
- **G3. Usage through native entities.** Each total is a `sensor` in the Home Assistant
  currency, so a dashboard, a statistics graph or an automation can use it.
- **G4. The records behind a total.** The panel shows the records that make a total, and
  each record opens its history.

## Non-goals

- A spending report, a chart or a cost per appliance. `IDEAS.md` keeps those.
- Budgets, alerts or a second currency. The cost is a number in the Home Assistant
  currency.
- A store of its own. The totals read the task and appliance records each time.

## Design

### The calculation

`cost_summary.py` is pure. `spend_records(tasks, assets, tz=)` gives 1 record for each
completion that has a cost: `ts`, `cost`, `who`, `task_id`, `task_name`, `asset_id` and
`archived`, newest first by the real time. It reads `task["completions"]` and the
`task_history` that an appliance keeps for its deleted tasks (`archived: True`). A skip
has no cost. A bad time drops the record; a bad cost reads as 0, the same as
`appliance_report._num`. A time with no zone gets `tz`.

`spend_summary(records, now=, windows=)` gives, for each window of N days, the `total`,
the `count` and `since` (`now` minus N days, inclusive), and for all time the `total`, the
`count` and `first`. Each total is rounded once. `purchase_total(assets)` sums the
appliance `cost` and counts the appliances that have one.

A deleted standalone task keeps no history, so its cost leaves the totals. A deleted task
of an appliance stays in the totals, because the appliance keeps its history. A log cut to
`MAX_COMPLETION_HISTORY`, or a use log that `reconcile.trim_use_completions` cuts, drops
the cost of each removed entry, so the all-time total can go down.

### The options

`cost_windows` is a list of 1 to 4 whole days in `1..3650`, default `[30, 60]`.
`cost_summary.normalize_windows` sorts it, drops duplicates and bad items, and gives the
default for a list with no good item. `cost_summary_panel` (default on) shows or hides the
panel strip. Both are panel options, not in the options flow. A change reloads the entry.

### The sensors

`sensor.py` adds, on the service device, 1 `HomeKeeperSpendSensor` for each window
(`home_keeper_spend_<days>d`, translation key `spend_window`), 1 for all time
(`home_keeper_spend_all`, `spend_all`) and 1 `HomeKeeperPurchaseSensor`
(`home_keeper_purchases`, `purchases_total`). The device class is `monetary` and the unit
is `hass.config.currency`. The all-time and purchase sensors have the state class `total`.
A window sensor has none, because its value goes down as time passes. Each one calculates
again on each coordinator update, so the clock moves the windows. A window that the user
removes is pruned at the reload. Attributes: `count`, plus `first` for all time.

### The panel

`home_keeper/get_spend` is an open read. It gives `windows`, `all_time`, `purchases` and
`records`. `panel-spend.ts` draws 1 toggle button for each total. The open total lists its
records. A record opens `/tasks/<id>/history`, or for a deleted task
`/appliances/<id>/history`. The purchases total opens the appliance list.

Above the task list, `spendStrip(p, 'compact')` puts the totals on 1 line. A phone hides
that strip. There, `spendButton` in the task list bar shows the total of the first period
in whole units, and opens `spendSheet`: the full strip in a modal sheet. The
strip and the button do not show when there is no record and no priced appliance. The open
total and the open sheet are panel state, not part of the URL. Settings → Cost tracking
edits the 2 options.

## Trade-offs

- **Calculate on each read** over **stored totals**: no second copy that can disagree with
  the records, at the cost of 1 pass over the completions on each update.
- **Open purchase total** over **admin only**: the appliance record is already open to all
  users ([architecture](architecture.md)), and a sensor cannot be admin-only.
- **Keep the cost of a deleted appliance task** over **drop it**: the money was spent, and
  the appliance history still shows the record.

## One-way doors

- The unique ids `home_keeper_spend_<days>d`, `home_keeper_spend_all` and
  `home_keeper_purchases`, and the translation keys `spend_window`, `spend_all` and
  `purchases_total`.
- The sensor attributes `count` and `first`.
- The options `cost_windows` and `cost_summary_panel`.
- The `home_keeper/get_spend` response keys.
