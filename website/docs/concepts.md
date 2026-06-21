---
sidebar_position: 3
title: Core concepts
---

# Core concepts

A **task** has a name, notes, an optional device it's attached to, and a recurrence:

- **Floating** — measured from the last completion: *"replace the fridge filter every
  1 month after I last did it."* Completing the task resets the clock; a missed task
  stays overdue rather than silently rolling forward.
- **Fixed** — an anchored calendar schedule: *"take medicine every day at 8am"*,
  independent of when you actually complete it.
- **One-off** — *do-once*, on a chosen due date. After it's done it goes dormant and
  drops out of every active surface, landing in a collapsed **Completed** section.
- **Triggered** — *condition-driven, no schedule*. An owning integration arms it when
  a condition becomes true and clears it when resolved.

An **appliance** (asset) is the physical thing a task is about — a fridge, furnace, or
water heater. Appliances get a real device page so tasks, metadata, parts, and history
all hang off one place.

:::note Administration vs. usage
You **manage** tasks and appliances from the **Home Keeper** sidebar panel, and you
**use** them through native Home Assistant entities (to-do, calendar, device pages) and
the dashboard card. This separation is deliberate — administration stays in the panel.
:::

This section is being expanded with the full per-topic guides (tasks, completions,
appliances, the dashboard card, settings, services, and events). For now, the
[README](https://github.com/prestomation/ha-home-keeper#readme) covers every feature in
depth.
