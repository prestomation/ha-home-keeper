---
sidebar_position: 1
slug: /integrating
title: Integrating with Home Keeper
---

# Integrating with Home Keeper

This guide is for **authors of other Home Assistant integrations** who want to push
recurring tasks into Home Keeper and keep them in sync with completions — for example a
battery integration that schedules "replace battery", a plant integration that schedules
"water the fern", or a pet integration that schedules "trim nails".

Home Keeper is the recurring-task engine. **Your integration owns the schedule
configuration**; it talks to Home Keeper purely over the Home Assistant **event bus and
services**. There is no Python import in either direction and no hard dependency: if Home
Keeper isn't installed, your calls are simply skipped.

:::info Home Keeper knows nothing about your integration
The `source` and `origin` values below are *opaque* to Home Keeper — it stores and
echoes them verbatim and never branches on their contents. Everything domain-specific
lives in your integration.
:::

## At a glance

| You want to… | Do this |
|---|---|
| Create a recurring task | Call `home_keeper.add_task` with a `source` namespaced under your domain |
| Create a *condition-driven* task | Call `home_keeper.add_task` with `recurrence_type: "triggered"` (no schedule) |
| Learn the new task's id | Read `task_id` from `add_task`'s response (`return_response=True`) |
| React when a task is completed | Subscribe to the `home_keeper_task_completed` event |
| Complete a task from your side | Call `home_keeper.complete_task` with a unique `origin` |
| Re-arm a triggered task | Call `home_keeper.trigger_task` when the condition becomes true again |
| Avoid infinite loops | Filter the event by `origin`, and apply your side-effect without re-calling `complete_task` |
| Remove a task | Call `home_keeper.delete_task` |

Guard **every** service call with
`hass.services.has_service("home_keeper", "<service>")` so your integration works fine
when Home Keeper is absent.

:::note Full contract being ported
This page is the landing point for the Developer Guide. The complete integration
contract — task creation, two-way completion sync, loop avoidance, and the full events
reference — lives in
[`docs/INTEGRATING.md`](https://github.com/prestomation/ha-home-keeper/blob/main/docs/INTEGRATING.md)
and [`docs/EVENTS.md`](https://github.com/prestomation/ha-home-keeper/blob/main/docs/EVENTS.md)
and is being ported into per-topic pages here.
:::
