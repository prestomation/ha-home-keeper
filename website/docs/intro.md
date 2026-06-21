---
sidebar_position: 1
slug: /intro
title: Introduction
---

# Home Keeper

Track home **maintenance** and **chores** in Home Assistant — fridge/furnace filter
changes, water filters, taking medicine, and anything else that recurs.

![Home Keeper task list](/img/screenshots/1-panel-task-list.png)

## Features at a glance

- **Tasks, four ways** — **floating** (every N units after last done), **fixed**
  (anchored calendar schedule), **one-off** (do-once, on a chosen due date), and
  **triggered** (condition-driven, no schedule — armed/cleared by another integration).
- **Used through native HA entities** — a `todo` list, an upcoming-tasks `calendar`,
  and per-device **button / next-due sensor / overdue binary_sensor** on a task's
  device page.
- **Dashboard task card** — a bundled, auto-registered `custom:home-keeper-card` with
  one-tap **Done**, inline add/edit, and rich filtering/grouping.
- **Appliances & virtual devices** — give "dumb" appliances a real device page,
  structured metadata (with optional tracked-date sensors), **parts & wear items**,
  **spare-part inventory**, and a CSV **home-inventory export** for insurance.
- **Events & automation triggers** — a bus event for every meaningful change, plus
  visual-editor **device triggers** like *"Task became overdue."*
- **Services for everything** — every data action is a `home_keeper.*` service for
  automations, scripts, and voice.
- **Localized in 16 languages**, following your Home Assistant language.
- **Open to other integrations** — they can contribute their own recurring tasks and
  stay in sync with completions.

## Where to next

- New here? Start with [Installation](/docs/guide/installation), then the
  [core concepts](/docs/guide/concepts).
- Building an integration that talks to Home Keeper? See the
  [Developer Guide](/developer/integrating).
