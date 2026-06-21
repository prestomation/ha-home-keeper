# Glue integrations

A **glue integration** is a small, standalone Home Assistant integration whose only job
is to **bridge another integration to Home Keeper**. It owns no schedule logic and no UI
of its own — it watches the other integration's signals and translates them into Home
Keeper service calls (and listens for Home Keeper completions to translate back).

This is the lightest way to make a third-party integration "Home Keeper aware" **without
modifying it**. The reference example is
[Home Keeper — Battery Notes](https://github.com/prestomation/ha-home-keeper-battery-notes),
which connects [Battery Notes](https://github.com/andrew-codechimp/HA-Battery-Notes) to
Home Keeper.

## When to use a glue integration

Reach for the glue pattern when:

- The source integration **already exposes the state you care about** (an event, a sensor,
  a `binary_sensor`) but knows nothing about Home Keeper.
- You **can't or don't want to modify** the source integration (it's third-party, or the
  Home-Keeper link is opt-in and shouldn't be a hard dependency).
- The mapping is essentially *"when this condition is true, a task is due; when it's
  resolved, the task is done."*

If you own the source integration, you don't need glue — call the Home Keeper services
directly from it (see [INTEGRATING.md](INTEGRATING.md)). Glue exists precisely for the
case where the two sides must stay decoupled.

## The shape of the glue

A glue integration is a normal custom integration with a config entry. In
`async_setup_entry` it:

1. **Discovers** the things to track from the source integration (e.g. enumerates Battery
   Notes devices, or subscribes to its events).
2. **Maps** each one to a Home Keeper **triggered** task — armed when the condition is
   true, dormant otherwise — using `home_keeper.add_task` /
   `home_keeper.trigger_task` / `home_keeper.complete_task`.
3. **Listens** to `home_keeper_task_completed` so a completion made *in Home Keeper* is
   reflected back into the source integration (and vice-versa), with loop prevention.

Everything it does is the **triggered-task contract** already documented in
[INTEGRATING.md §7](INTEGRATING.md#7-condition-driven-triggered-tasks) — the glue
integration is just a thin client of it. Guard every call with
`hass.services.has_service("home_keeper", "<service>")` so the glue degrades to a no-op
when Home Keeper isn't installed.

## Worked example: Battery Notes

Battery Notes tracks each device's battery and flips a **low-battery** signal when it
needs replacing. The glue maps that one-to-one onto a Home Keeper triggered task:

| Battery Notes says… | Glue calls | Result in Home Keeper |
|---|---|---|
| battery went **low** (first seen) | `add_task` with `recurrence_type: "triggered"` | a *"Replace battery"* task, **armed / due-now**, attached to the battery's device |
| battery went **low** again later | `home_keeper.trigger_task` | the existing task re-arms (history preserved) |
| battery **replaced** | `home_keeper.complete_task` (with an `origin`) | the task records a completion and goes **dormant** |
| user ticks the task off **in Home Keeper** | (listener reacts to `home_keeper_task_completed`, `origin = None`) | glue tells Battery Notes the battery was replaced |

Because the task **persists across cycles** instead of being deleted and recreated, its
completion history accumulates — so you learn the real cadence ("this smoke-detector
battery lasts ~13 months") instead of losing it on every replacement.

### Keeping the two sides in sync without loops

The danger is a feedback loop: a replacement completes the task → Home Keeper fires
`home_keeper_task_completed` → the glue's listener marks it replaced in Battery Notes →
which might complete the task again. Break it exactly as
[INTEGRATING.md §4](INTEGRATING.md#4-two-way-sync-and-loop-prevention) describes:

- When the **glue** completes a task, pass a recognizable `origin` (e.g. your domain), and
  have the listener **ignore events whose `origin` is its own**.
- On the inbound path (a completion the glue did *not* initiate), apply the side-effect
  **without** calling `complete_task` again.

Either guard closes the loop; use both.

## Reconciling on restart

Triggered tasks are persistent, so on `async_setup_entry` the glue should reconcile rather
than blindly recreate:

- Call `home_keeper.list_tasks` and match on your `source` namespace to find tasks you
  already created.
- For each tracked thing: if no task exists, `add_task`; then **arm or clear** it
  (`trigger_task` / `complete_task`) to match the source integration's *current* state.
- Only `delete_task` when the tracked thing disappears for good.

See [INTEGRATING.md §5](INTEGRATING.md#5-lifecycle) for the full lifecycle, and
[INTEGRATING.md §6](INTEGRATING.md#6-declaring-managed-ownership-optional) for declaring
`managed_by` so Home Keeper shows a *"Managed by …"* chip, locks fields the user
shouldn't edit, and cleans up orphaned tasks if the glue is removed.

## Testing

Test the glue end-to-end against Home Keeper's bundled fake — no panel, storage, or
entities required. See [INTEGRATING.md → Testing your integration](INTEGRATING.md#testing-your-integration).
