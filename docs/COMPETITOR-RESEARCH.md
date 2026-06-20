# Competitor Research — Home Maintenance & Chore Tracking

> **Purpose:** Catalog competing products (Home Assistant integrations and standalone
> apps), their feature sets, and the features their users are actively requesting.
> Updated June 2026. Use this to prioritise Home Keeper work and spot gaps.

---

## Table of Contents

1. [Home Assistant Integrations](#home-assistant-integrations)
2. [Standalone & Self-Hosted Software](#standalone--self-hosted-software)
3. [Cross-Cutting User Pain Points](#cross-cutting-user-pain-points)
4. [Feature Gap Analysis](#feature-gap-analysis)
5. [Sources](#sources)

---

## Home Assistant Integrations

### Chore Helper
**Repo:** [bmcclure/ha-chore-helper](https://github.com/bmcclure/ha-chore-helper) | **Status:** Active | ⭐ ~150

**What it does:**
- Adds a new Helper type: a _Chore_ with configurable recurrence
- Two scheduling modes: **Every** (anchored to a start date) and **After** (resets from completion date)
- Time periods: daily, weekly, monthly, yearly, custom
- Creates a sensor (days until/since due) and a calendar entity
- Service calls: complete chore, add/remove/offset dates, update state
- Customisable icons per status (future / tomorrow / today / overdue)

**Limitations / complaints:**
- No management UI panel — configuration is through the HA helpers UI
- No appliance/device metadata
- No completion history persisted across cycles
- README self-describes it as "in its infancy and might not work well for your use case yet"
- 21 open issues; self-reported fragility

**User feature requests:**
- Front-end Lovelace card (mentioned in HA community thread as top open request)
- Chore assignment to household members
- Workday/holiday schedule awareness
- Better documentation

---

### Home Maintenance (TJPoorman)
**Repo:** [TJPoorman/home_maintenance](https://github.com/TJPoorman/home_maintenance) | **Status:** Active

**What it does:**
- Recurring task tracking (interval in days/weeks/months + last-performed date)
- Binary sensors activate when task is due
- Built-in UI panel (within HA)
- NFC tag scan-to-complete (integration broken — tag picker shows "Loading…" indefinitely)
- No YAML required; uses `.storage`

**Design philosophy:** Intentionally minimal — "not all feature requests will be
added … especially if the functionality already exists natively in Home Assistant."

**Limitations / complaints:**
- NFC tag picker is broken (19 open issues, 19 pending PRs)
- Panel lacks sorting, filtering, or search for large task lists
- Date formatting is US-only (confuses European users)
- No completion history, no appliance context

**User feature requests:**
- Locale-aware date formatting
- Sorting and filtering by due date/name
- Lovelace card with table view

---

### Activity Manager
**HA Community:** [Custom Component — Activity Manager](https://community.home-assistant.io/t/custom-component-activity-manager-keep-track-of-recurring-tasks/566733) | **Status:** Maintained

**What it does:**
- Recurring activities with configurable frequencies (days, hours, minutes, seconds)
- Resets timer on completion (floating-interval model)
- Category grouping with a companion Lovelace card
- "Due only" filtering in the card
- Replaced the older check-button-card

**Limitations / complaints:**
- Companion card does not work in non-management mode for some users
- No calendar entity
- No appliance metadata

**User feature requests:**
- Automation triggers when a task becomes overdue
- NFC tag integration
- Multi-language support (German specifically requested)

---

### Home Upkeep (Local Todo Addon)
**HA Community:** [New local todo addon for recurring household chores](https://community.home-assistant.io/t/new-local-todo-addon-for-recurring-household-garden-and-maintenance-chores/944727) | **Status:** Active addon

**What it does:**
- Interval-based scheduling that resets from completion date (not due date)
- **Seasonal constraints:** specify which calendar months a task is allowed (e.g. no hedge trimming in winter)
- Exposes tasks as standard HA `todo` entities — works with native UI and automations
- Custom UI panel alongside native interface

**Limitations:**
- Explicitly not a calendar ("not intended to alert you on a specific day/time")
- Automations cannot trigger on individual task completion — only list-level changes
- No completion history, no appliance context

**User feature requests:**
- User tagging for task assignment and accountability
- Non-admin dashboard access with restricted permissions

---

### Maintenance Supporter
**Repo:** [iluebbe/maintenance_supporter](https://github.com/iluebbe/maintenance_supporter) | **Status:** Very active | **Requires HA 2025.7+**
**HA Community:** [Sensor-Triggered, Adaptive Maintenance](https://community.home-assistant.io/t/custom-integration-maintenance-supporter-sensor-triggered-adaptive-maintenance-for-your-home/995556)

The most technically sophisticated HA maintenance integration. Positioned against calendar-based tools: *"Fixed-interval reminders either fire too early (wasting parts and effort) or too late (risking equipment damage)."*

**What it does:**
- **Five sensor-trigger types:**
  - Threshold (value exceeds/falls below limit, with optional duration)
  - Counter (absolute or delta mode)
  - State-change (count on/off transitions)
  - Runtime (accumulated operating hours, persisted every 5 min)
  - Compound (AND/OR combinations of the above)
- **Adaptive scheduling:** Exponential Weighted Averaging (EWA) after 2+ completions; Weibull reliability analysis after 5+
- Seasonal awareness (hemisphere detection), environmental correlation (temp, humidity, air quality)
- Six task types: cleaning, inspection, replacement, calibration, service, custom
- Multi-step checklists, NFC/QR scan-to-complete
- Per-object documentation URL ("where did I put that manual?")
- Operator mode for non-admin household members
- Completion actions: fire HA service on completion (e.g. reset a Roborock filter counter automatically)
- Mobile notifications with actionable buttons
- Sidebar panel + Lovelace cards + native calendar

**Limitations:**
- Requires HA 2025.7.0 or newer
- EWA needs 2+ completions before suggestions appear; Weibull needs 5+
- No nesting in compound triggers
- Maximum 500 history entries per task
- No appliance virtual-device creation
- 1 open issue (very few)

**Feature requests (resolved in updates):**
- One-time (non-recurring) tasks — added in v2.6.0
- Month/year interval units — added
- Contextual notification titles (device name instead of "Maintenance Overdue!") — added
- Manual documentation links per object — added

---

### Device Maintenance Monitor
**Repo:** [rafael-zilberman/device-maintenance-monitor-custom-component](https://github.com/rafael-zilberman/device-maintenance-monitor-custom-component) | **Status:** Active | 11 open issues

**What it does:**
- Tracks maintenance by: accumulated runtime hours, power-on cycle count, or fixed time interval
- Boolean sensor for maintenance due/not-due
- Reset button entity on completion
- Addresses variable-usage devices (e.g. air conditioner running 12 hrs/day in summer vs. idling in winter)

**Limitations:**
- Simple — no adaptive scheduling, no task history, no panel UI
- No appliance metadata, no notification system

---

### KidsChores (archived → ChoreOps)
**Repo:** [ad-ha/kidschores-ha](https://github.com/ad-ha/kidschores-ha) | **Status:** Archived March 2026 → superseded by ChoreOps

**What it did:**
- Multi-user profiles, customisable points currency (coins, stars, bucks, etc.)
- Chore assignment with recurring schedules and shared tasks
- Reward claiming, badge milestones with point multipliers
- Bonuses and penalties system
- Calendar integration + detailed statistics sensors
- 100% local processing
- English and Spanish

**Migration:** Users directed to [ChoreOps](#choreops).

---

### ChoreOps
**Repo:** [ccpk1/choreops](https://github.com/ccpk1/choreops) | **Status:** Very active (v1.0.0 March 2026) | **License:** GPL-3.0, free
**HA Community:** [ChoreOps — Level Up Your Household Tasks](https://community.home-assistant.io/t/choreops-level-up-your-household-tasks/995326)

Evolution of KidsChores — expanded to the whole household, not just kids. Re-architected to HA Platinum standards.

**What it does:**
- **Task models:** individual, shared, first-complete, rotation-based, per-assignee schedules
- **Advanced recurrence** with overdue handling and due-time windows
- **Gamification (optional):** XP/points (customisable icon and terminology), badges, cumulative ranks, periodic quests, streaks, achievement multipliers, challenges, claim-and-approve reward workflows
- Weekly activity reports (via service → markdown or notify/email)
- Daily/weekly/monthly/yearly/all-time statistics sensors
- Manual/automated bonuses and penalties
- Role-based access (approvers vs. assignees)
- Multi-instance support in a single HA install
- "Over-The-Air" dashboard generation system
- 10 open issues

**Limitations:**
- No appliance/device metadata
- No sensor-triggered maintenance
- Chore-management focused — not home-maintenance or asset lifecycle

---

### Vehicle Service Manager
**HA Community:** [Vehicle-Service-Manager](https://community.home-assistant.io/t/vehicle-service-manager/1012193) | **Status:** Limited adoption

**What it does:**
- Dual tracking: mileage (km/miles) + elapsed days simultaneously
- Links to existing odometer sensor in HA
- Pre-defined service templates (oil change, tyre rotation, etc.)
- Dashboard entities + automation triggers for notifications

**Limitations:**
- UI and translations primarily in German (English translation file contains German text)
- Requires separate companion card component
- Niche — vehicle-only, no home maintenance

---

### Donetick (Self-Hosted, with HA Integration)
**Repo:** [donetick/donetick](https://github.com/donetick/donetick) | **HA Integration:** [donetick/donetick-hass-integration](https://github.com/donetick/donetick-hass-integration) | **Status:** Active | **License:** Open source, free

A self-hosted (or cloud-hosted) task and chore manager with a dedicated HA integration.

**What it does:**
- Natural language task creation ("Take the trash out every Monday and Tuesday at 6:15 pm")
- Recurring tasks with rotation-based auto-assignment
- "Circles" for shared todo lists with family/housemates
- NFC scan-to-complete
- Optional point system
- Full history with notes; basic predictions for next due date
- REST API + webhooks
- Notifications via Telegram, Discord, Pushover, mobile apps (iOS/Android)
- **HA integration:** sensor per chore (status, assignee, due date, notes as attributes) + button entity to complete; separate todo lists per Donetick user
- Single Docker container with SQLite — no external database

**Limitations:**
- Requires self-hosting (technical barrier) or trusting their hosted service
- HA integration is a bridge to an external service — data does not live in HA
- No appliance/device metadata, no sensor-triggered maintenance

---

## Standalone & Self-Hosted Software

### Grocy
**Site:** [grocy.info](https://grocy.info/) | **Repo:** [grocy/grocy](https://github.com/grocy/grocy) | **Pricing:** Free (self-hosted)
**HA Integration:** Community-maintained (custom component + Lovelace card)

Self-hosted "ERP beyond your fridge" — the most complete open-source household management solution.

**What it does:**
- Grocery inventory with barcode scanning, expiry tracking, quantity management
- Chore scheduler (recurring tasks, due dates, multi-user assignment)
- Meal planning with recipe → inventory linkage
- Shopping list management
- Task and to-do management
- Custom fields on any entity
- HA community integration surfaces chores/tasks on dashboards and as automation triggers

**Limitations / complaints:**
- Requires technical setup (Docker or manual install)
- No official mobile app (browser-based; community apps available)
- UI is functional but dated — consistently cited as needing a "modern aesthetic refresh"
- Limited direct integration with external services
- HA integration is not first-party

**User feature requests:**
- Modern, redesigned UI
- Official mobile app
- Easier onboarding and setup
- Better consumption-pattern analytics

---

### HomeZada
**Site:** [homezada.com](https://www.homezada.com/) | **Pricing:** ~$59–99/year (Premium/Family); ~$15.95/month | Founded 2012

The most feature-rich paid home management platform.

**What it does:**
- Home maintenance calendar with reminders
- Home inventory (photos, values, documentation)
- Home value tracking (property data integration)
- Renovation project management (budgets, timelines, contractor info)
- Financial expense tracking (bank account connection)
- Zada AI assistant (photo → item value estimation, maintenance needs)
- Multi-home support (Family: up to 5 homes)

**Limitations / complaints:**
- Steep learning curve; "average user abandons setup before completing their first room"
- Mobile app described as "clunky" — lacks key desktop features
- Manual data entry is heavy — "everything is manual"
- Billing complaints: auto-renewal without clear warning, difficulty cancelling
- Interface designed for power users — overwhelming for most homeowners
- No smart-home / sensor integration

**User feature requests:**
- Simpler, more intuitive interface
- AI automation to reduce manual data entry burden
- Better mobile experience

---

### Homer
**Site:** [homer.co](https://www.homer.co/) | **Platform:** iOS + Android | **Pricing:** Freemium (paid tiers)
**Background:** Swedish app; absorbed Centriq's user base when Centriq shut down January 2025

Currently the leading mobile-first home management app after Centriq's shutdown.

**What it does:**
- AI retrieval of user manuals (chat with owner's manual)
- AI-powered maintenance scheduling
- Home inventory management
- Multi-room item capture
- Timeline view of all actions/updates
- "Big 5" guided appliance onboarding (photograph data plates)
- Centriq CSV importer

**Limitations:**
- Mobile-first — limited web interface
- No smart-home / sensor integration
- No self-hosting option

---

### Centriq (SHUT DOWN January 31, 2025)
**Former site:** centriq.com | **Status:** Dead — data deleted after export window closed

**What it did (reference only — informs what Centriq's ~100k users are now looking for):**
- Appliance nameplate scanning → auto-populated user manuals, recall alerts, parts info
- Warranty tracking, purchase date logging
- Service history per appliance
- Product manual library

**What users miss:**
- Product manual library (cited as "most-loved feature")
- Barcode/nameplate scanning for fast appliance onboarding
- Integrated warranty tracking

**Where users went:** Homer (closest migration path via CSV import), Dib, HomeBeacon, HomeZada.

---

### Tody
**Site:** [todyapp.com](https://www.todyapp.com/) | **Platform:** iOS + Android | **Pricing:** Free basic; ~$9.99–19.99/year premium | **Users:** >1 million

A cleaning-focused chore app with a cult following.

**What it does:**
- **Condition-based tracking** (visual green/yellow/red bars) rather than rigid calendar deadlines
- Room-by-room task organisation
- **FairShare (2025):** visualises household labour distribution between partners
- Gamification (Dusty mascot, monthly challenges, unlockable rewards)
- Focus timer (Pomodoro-style)
- Multi-user sync with shared leaderboards (premium)
- Vacation Mode (pause indicators while away)

**Limitations / complaints:**
- Cleaning-only — not general home maintenance or appliance tracking
- Subscription shift (was a one-time purchase) frustrated long-time users
- No strict calendar / date-based scheduling (condition-based model is confusing for some)
- No smart-home integration

**User feature requests (mostly satisfied):**
- Better partner/spouse chore splitting → addressed by FairShare
- Multi-device sync
- More robust accountability features

---

### OurHome
**Platform:** iOS + Android | **Pricing:** 100% free | **Rating:** 4.5/5 iOS, 3.9/5 Android

Family chore manager — most popular free option.

**What it does:**
- Chore assignment to family members, due dates, gamified points for kids
- Shared family calendar and grocery list
- Cross-platform sync (improved in 2025)
- Completion history and per-member progress tracking

**Limitations:**
- No rotating chore assignments
- No meal planner
- Not connected to smart home / sensors
- Infrequent updates

---

### Donetick (Hosted)
See [Donetick above](#donetick-self-hosted-with-ha-integration) — also available as a hosted SaaS at donetick.com for users who don't self-host.

---

### HomeBeacon
**Site:** homebeacon.app | **Pricing:** Free tier available | **Status:** Active (2025–2026 entrant)

Positioned explicitly as Centriq's free replacement.

**What it does:**
- Maintenance scheduling and equipment tracking
- Appliance inventory

**Limitations:**
- Very new, limited feature depth
- No smart-home integration

---

### BrightNest
**Pricing:** Free | **Platform:** Web + mobile

Educational home maintenance reminders.

**What it does:**
- Seasonal maintenance reminders
- Tips and how-to content
- Basic home profile

**Limitations:**
- No task tracking, no completion history
- Tips and reminders only — no diagnosis or repair guidance
- No appliance metadata
- No smart-home integration

---

### HomeBinder
**Pricing:** Free

**What it does:**
- Seasonal reminders, room organisation, appliance tracking, document storage
- Often pre-loaded by real estate agents at closing

**Limitations:**
- Strategic pivot toward moving concierge services — maintenance tracking investment declining
- No AI, no smart-home integration
- No completion history analytics

---

### HomeLedger / Dib / HomeOps (Emerging)
Several new entrants launched to fill the Centriq gap:

- **HomeLedger** — AI-powered scheduling, repair history, expense tracking, document/receipt/warranty storage
- **Dib (dib.io)** — AI inventory scanning, accepted Centriq CSV exports, automatic reminders
- **HomeOps** — offline-first, tracks assets, warranties, and maintenance privately (no cloud)
- **HomeBeacon** — free Centriq replacement focused on maintenance scheduling

All lack smart-home / sensor integration.

---

## Cross-Cutting User Pain Points

These requests appear independently across multiple integrations and standalone apps, indicating strong demand:

### 1. Floating recurrence (reset from completion, not calendar) — everywhere
The most universally cited gap. Users everywhere describe workarounds: five helper entities per task, CalDAV hacks, blueprint automation chains. Every HA forum thread on maintenance eventually describes this pain. Home Keeper already solves this.

### 2. Sensor / usage-based maintenance triggers
"My pool pump runs 12 hrs/day in summer and 2 in winter — a calendar reminder is wrong for both." Runtime hours, cycle counts, threshold crossings, power-on counts. Maintenance Supporter is the only HA integration addressing this. No standalone app does it. Strong demand, high implementation complexity.

### 3. Appliance metadata: warranty, manuals, serial numbers, purchase dates
Centriq's shutdown made this very loud (>100k displaced users). Users want: manual auto-retrieval, warranty-expiry alerts, purchase/install dates. All are already in Home Keeper's appliance model.

### 4. Chore assignment to household members / rotation
Requested in: Chore Helper thread (top open request), Home Upkeep users, OurHome reviews, virtually every standalone app. Most HA integrations have no concept of a person/assignee. ChoreOps is the only HA integration solving this fully.

### 5. Actionable / snoozable notifications
"Mark done" or "snooze 1 day" directly from a mobile push notification — without opening an app. Popular blueprint exists for this, but it can't recalculate the next due date (it knows nothing about intervals). The combination of snooze + recalculation is unsolved everywhere.

### 6. NFC tag scan-to-complete
Stick a tag on the appliance, tap phone to mark maintenance done. DIY guides proliferate (blog posts, Node-RED flows). The demand is clearly there. Home Maintenance (TJPoorman) tried it but the tag picker is broken. Maintenance Supporter and Donetick both implement it properly.

### 7. Kids' chores with gamification / family use case
Fully addressed by ChoreOps (HA) and OurHome/Tody/ChoreMonster (standalone). Large segment but distinct from the home-maintenance use case Home Keeper targets. Points, badges, streaks, parent-approval workflows.

### 8. Voice completion via HA Assist
"I just changed the furnace filter" → logs completion and recalculates next due date. Community blueprints exist for creating/listing to-do items by voice, but no clean path to mark a maintenance task done with interval recalculation. Home Keeper's `complete_task` service is automatable but no ready-made Assist intent exists.

### 9. Vehicle maintenance (mileage + time)
"Oil every 15,000 km or 12 months, whichever comes first." The Vehicle Service Manager addresses this in HA (German-only). Standalone: no home-maintenance app bundles it naturally (users request it on HomeZada forums; separate apps like CarDash exist). Cross-domain with home maintenance — a niche but vocal segment.

### 10. Simple onboarding / template catalog
Abandonment during setup is cited as the primary failure mode for HomeZada, Grocy, and HomeBinder. Users want "add a water heater" to pre-fill: anode rod replacement (12 mo), pressure-relief valve test (12 mo), etc. No competitor ships a proper starter template catalog.

### 11. Completion metadata (notes, cost, who did it, photo)
Users want to record what happened: "replaced with 3M filter #X, cost $18, spouse did it." HomeZada has cost tracking. No HA integration captures per-completion metadata beyond timestamp. Common in standalone maintenance logs.

### 12. Condition-based ("when dirty enough") vs. calendar scheduling
Tody's core insight: visual progress bars showing how "dirty" each area is, without hard due dates. Users who are flexible about timing prefer this model. No HA integration offers it.

### 13. Seasonal / weather-triggered tasks
"Drain garden hoses when forecast first dips below freezing." People build elaborate YAML automations for this. Home Keeper's triggered-task model already fits — nobody has written a blueprint that wires a weather entity to arm a triggered task.

### 14. Home sale / handoff documentation
Export full maintenance history + appliance docs + warranty info as a package for the next owner. Niche but clearly desired (Reddit threads, HomeZada feature). Home Keeper already has the appliance inventory CSV; a richer export is the gap.

### 15. Repair log (one-off, distinct from recurring maintenance)
"HVAC capacitor replaced, $180, ABC Heating, 2026-03" — a one-off event that doesn't repeat. Feeding repair-vs-replace analytics over the appliance's lifetime. No HA integration models this separately from recurring tasks.

### 16. Vacation / away-aware scheduling
Tody's Vacation Mode pauses task indicators. Users leave for 2 weeks; they don't want 14 "overdue" items on return for things that could have waited. Home Keeper has no equivalent.

---

## Feature Gap Analysis

### What Home Keeper has that most competitors lack

| Feature | HA competitors | Standalone apps |
|---|---|---|
| Triggered (condition-driven) tasks | None | None |
| Problem-sensor sync (auto-arm from `binary_sensor.problem`) | None | None |
| Appliance virtual devices + metadata | None | Homer, Centriq (RIP), HomeZada |
| Parts / wear items with inventory + low-stock events | None | None |
| Subdevice & related-device relationships | None | None |
| Home inventory CSV export | None | HomeZada, HomeLedger |
| Warranty date as automatable HA `date` sensor | None | N/A (no HA integration) |
| 16-language localisation | ChoreOps | Most standalone |
| All data actions as HA services | Partial (some integrations have basic services) | N/A |
| Cross-integration contribution API | None | N/A |

### What competitors have that Home Keeper lacks (potential future work)

| Feature | Who has it | Demand signal |
|---|---|---|
| Sensor/usage-based triggers (runtime hours, cycle counts, threshold) | Maintenance Supporter, Device Maintenance Monitor | Very high — multiple HA threads |
| Adaptive scheduling (learns from history) | Maintenance Supporter | Medium |
| Chore assignment to household members | ChoreOps, Home Upkeep, Tody, OurHome | Very high |
| Gamification (points, badges, streaks) | ChoreOps, KidsChores, OurHome, Tody | High (family segment) |
| Per-completion metadata (notes, cost, photo, who) | HomeZada, standalone apps | High |
| NFC scan-to-complete (working) | Maintenance Supporter, Donetick | Medium-high |
| Snooze / skip one occurrence | Various standalone | Medium-high |
| Vehicle / mileage-based maintenance | Vehicle Service Manager | Medium |
| Starter template catalog | None (requested everywhere) | Very high |
| Natural language task creation | Donetick | Medium |
| Vacation / away mode (pause scheduling) | Tody | Medium |
| Appliance barcode/nameplate scanning | Centriq (RIP), Homer, Dib | Medium |
| Voice completion via Assist | Blueprint workarounds | High |
| Actionable notifications (mark done from push) | Blueprint workarounds | High |
| Repair log (one-off events, separate from recurring) | HomeZada | Medium |
| Seasonal / weather-triggered arming | DIY YAML | Medium |

---

## Sources

### Home Assistant Integrations
- [ha-chore-helper GitHub](https://github.com/bmcclure/ha-chore-helper)
- [Chore Helper — HA Community thread](https://community.home-assistant.io/t/chore-helper-track-recurring-or-manual-chores-with-flexible-scheduling/557470)
- [home_maintenance GitHub (TJPoorman)](https://github.com/TJPoorman/home_maintenance)
- [Home Maintenance — HA Community thread](https://community.home-assistant.io/t/new-integration-home-maintenance-track-recurring-tasks-in-home-assistant/897324)
- [Activity Manager — HA Community thread](https://community.home-assistant.io/t/custom-component-activity-manager-keep-track-of-recurring-tasks/566733)
- [Home Upkeep addon — HA Community thread](https://community.home-assistant.io/t/new-local-todo-addon-for-recurring-household-garden-and-maintenance-chores/944727)
- [maintenance_supporter GitHub](https://github.com/iluebbe/maintenance_supporter)
- [Maintenance Supporter — HA Community thread](https://community.home-assistant.io/t/custom-integration-maintenance-supporter-sensor-triggered-adaptive-maintenance-for-your-home/995556)
- [device-maintenance-monitor GitHub](https://github.com/rafael-zilberman/device-maintenance-monitor-custom-component)
- [kidschores-ha GitHub](https://github.com/ad-ha/kidschores-ha)
- [KidsChores — HA Community thread](https://community.home-assistant.io/t/kidschores-family-chore-management-integration/827719)
- [ChoreOps GitHub](https://github.com/ccpk1/choreops)
- [ChoreOps — HA Community thread](https://community.home-assistant.io/t/choreops-level-up-your-household-tasks/995326)
- [Vehicle Service Manager — HA Community](https://community.home-assistant.io/t/vehicle-service-manager/1012193)
- [donetick/donetick GitHub](https://github.com/donetick/donetick)
- [donetick-hass-integration GitHub](https://github.com/donetick/donetick-hass-integration)
- [Donetick HA Community thread](https://community.home-assistant.io/t/donetick-a-user-friendly-task-and-chore-management-addon/749772)

### HA Community Feature Requests
- [WTH: Recurring interval for local todo tasks + sensor status](https://community.home-assistant.io/t/wth-recurring-interval-attribute-for-local-todo-tasks-task-status-by-sensor-statuses/812082)
- [To-do list — recurring task (Feature Request)](https://community.home-assistant.io/t/to-do-list-recurring-task/684471)
- [To-Do list "recurring" GUI feature request](https://community.home-assistant.io/t/to-do-list-recurring-feature-request-gui/857452)

### Standalone Software
- [Grocy — grocy.info](https://grocy.info/)
- [Grocy GitHub](https://github.com/grocy/grocy)
- [HomeZada — homezada.com](https://www.homezada.com/)
- [HomeZada Review 2026 — Smart Home Admin](https://www.smarthomeadmin.com/reviews/homezada-review)
- [Homer — homer.co](https://www.homer.co/)
- [Centriq shutdown alternatives — Dib blog](https://dib.io/blog/centriq-shutting-down-alternative)
- [Best Centriq Alternative — HomeBeacon](https://homebeacon.app/alternatives/centriq-alternative)
- [Tody App Review 2025 — Tidied Blog](https://www.tidied.app/blog/tody-app-review)
- [OurHome App Review 2025 — Tidied Blog](https://www.tidied.app/blog/ourhome-app-review)
- [Best Home Maintenance Tracking App 2026 — Real Estate Ledger](https://realestateledger.io/comparisons/best-home-maintenance-tracking-app)
- [HomeZada vs Centriq (2026) — Real Estate Ledger](https://realestateledger.io/comparisons/homezada-vs-centriq)
- [Donetick self-hosted review — XDA Developers](https://www.xda-developers.com/self-hosting-donetick-for-chores/)
