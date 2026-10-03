---
title: Glue integrations
summary: How to write a small integration that connects a third-party integration to Home Keeper.
---

# Glue integrations

A **glue integration** is a small, standalone Home Assistant integration. Its only job is
to **connect another integration to Home Keeper**. It has no schedule logic and no UI. It
watches the signals of the other integration and changes them into Home Keeper service
calls. It also listens for Home Keeper completions and sends them back.

With glue, a third-party integration can work with Home Keeper **without changes to it**.
The reference example is
[Home Keeper / Battery Notes](https://github.com/prestomation/ha-home-keeper-battery-notes),
which connects [Battery Notes](https://github.com/andrew-codechimp/HA-Battery-Notes) to
Home Keeper.

## When to use a glue integration

Use the glue pattern when:

- The source integration **already shows the state you need** (an event, a sensor, a
  `binary_sensor`) but does not know about Home Keeper.
- You **cannot or do not want to change** the source integration: it is third-party,
  or the Home Keeper link is optional and must not be a hard dependency.
- The mapping is *"when this condition is true, a task is due; when it is resolved, the
  task is done."*

If you own the source integration, you do not need glue. Call the Home Keeper services
directly from it (see [INTEGRATING.md](INTEGRATING.md)). Glue is for the case where the
2 sides must stay separate.

## The shape of the glue

A glue integration is a normal custom integration with a config entry. In
`async_setup_entry` it:

1. **Finds** the things to track in the source integration. Battery Notes glue lists
   the Battery Notes devices or subscribes to their events.
2. **Maps** each one to a Home Keeper **triggered** task (armed when the condition is
   true, dormant at other times) with `home_keeper.add_task`,
   `home_keeper.trigger_task` and `home_keeper.complete_task`.
3. **Listens** to `home_keeper_task_completed`, so a completion made *in Home Keeper*
   goes back to the source integration, with loop prevention.

All of this is the **triggered-task contract** in
[INTEGRATING.md §7](INTEGRATING.md#7-condition-driven-triggered-tasks). The glue is a
thin client of it. Guard every call with
`hass.services.has_service("home_keeper", "<service>")`, so the glue does nothing when
Home Keeper is not installed.

## Example: Battery Notes

Battery Notes tracks the battery of each device and sets a **low-battery** signal when the
battery needs replacement. The glue maps that signal to a Home Keeper triggered task:

| Battery Notes says… | Glue calls | Result in Home Keeper |
|---|---|---|
| battery went **low** (first seen) | `add_task` with `recurrence_type: "triggered"` | a *"Replace battery"* task, **armed / due-now**, attached to the battery's device |
| battery went **low** again later | `home_keeper.trigger_task` | the existing task re-arms (history preserved) |
| battery **replaced** | `home_keeper.complete_task` (with an `origin`) | the task records a completion and goes **dormant** |
| user ticks the task off **in Home Keeper** | (listener reacts to `home_keeper_task_completed`, `origin = None`) | glue tells Battery Notes the battery was replaced |
| every battery type it knows about | `add_asset` once, then `update_managed_asset` | a managed **Batteries** appliance with 1 consumable part per battery type |
| the type and count a low device takes | `set_task_consumable` with that device's `quantity` | the *"Replace battery"* task reads *"Takes 2 AAA, 2 left"* |
| battery **replaced**, from either side | (no extra call) | the completion takes 2 AAA off that part's stock |
| stock at or below its reorder point | (no extra call) | a *"Buy AAA"* task, and a line on the shopping list |

The appliance is **managed**. The glue owns its name and its list of parts. The user owns
every stock number. A type that the user did not count stays untracked and opens no buy
task. See [INTEGRATING.md §8](INTEGRATING.md#8-managing-an-appliance) for the
`managed_by` block, `update_managed_asset`, and the `quantity` on a consumable link.

The task **stays across cycles**. The glue does not delete it and make it again, so its
completion history grows. You learn the real cadence ("this smoke-detector battery lasts
about 13 months").

### Keep the 2 sides in sync without loops

A feedback loop is possible: a replacement completes the task, Home Keeper fires
`home_keeper_task_completed`, the listener marks the battery replaced in Battery Notes,
and that can complete the task again. Stop it as
[INTEGRATING.md §4](INTEGRATING.md#4-two-way-sync-and-loop-prevention) describes:

- When the **glue** completes a task, pass a known `origin`, such as your domain.
  The listener **ignores events whose `origin` is its own**.
- On the inbound path (a completion that the glue did not start), apply the side effect
  **without** a second call to `complete_task`.

Each guard stops the loop. Use both.

## Reconcile on restart

Triggered tasks stay, so on `async_setup_entry` the glue must reconcile, not make the
tasks again:

- Call `home_keeper.list_tasks` and match on your `source` namespace to find your tasks.
- For each tracked thing: if no task exists, call `add_task`. Then **arm or clear** it
  (`trigger_task` / `complete_task`) to match the *current* state of the source.
- Call `delete_task` only when the tracked thing is gone permanently.

See [INTEGRATING.md §5](INTEGRATING.md#5-lifecycle) for the full lifecycle. See
[INTEGRATING.md §6](INTEGRATING.md#6-declaring-managed-ownership-optional) to declare
`managed_by`. Home Keeper then shows a *"Managed by …"* chip, locks the fields the user
must not edit, and cleans up orphaned tasks if the glue is removed.

## Testing

Test the glue end-to-end against the fake that Home Keeper includes. It needs no panel,
storage, or entities. See
[INTEGRATING.md → Testing your integration](INTEGRATING.md#testing-your-integration).
