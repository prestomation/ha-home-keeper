# Glue integration candidates

Which Home Assistant integrations are worth writing a [glue integration](GLUE_INTEGRATIONS.md)
for, ranked by how many people run them.

This is a **research doc**, not a roadmap. It exists so the decision about what to
build next is made against real install counts instead of intuition. Numbers age;
re-run the method below before leaning on them.

## Method

Two feeds from Home Assistant's opt-in analytics, snapshotted **2026-08-26** (the
`current.last_updated` stamp carried by `data.json` itself):

- `https://analytics.home-assistant.io/custom_integrations.json` — custom/HACS
  integrations, keyed by domain, with a per-version breakdown. 4,225 entries.
- `https://analytics.home-assistant.io/data.json` — the full analytics dump; its
  `current.integrations` map holds core integration counts.

Both are drawn from the same 534,228 installations that report integration data (of
673,279 active installations), so the two sets are directly comparable. Counts in
this doc are marked `*` when they come from the core feed.

Caveats worth keeping in mind:

- **Opt-in only.** Absolute numbers under-report the real world. Relative ranking is
  the usable signal.
- **Popularity is not fit.** A large install base with no maintenance signal to read
  is worth less than a small one that exposes a life percentage and a reset button.
- **A core count and a custom count mean different things.** A custom integration is
  installed deliberately through HACS, so every count is a user who wanted it. A core
  integration is frequently added by discovery — a printer found over zeroconf, a
  vacuum picked up on the network — and its config entry says only that the device is
  on the LAN, not that its owner cares about maintaining it. Read the core-heavy tiers
  (printers, vacuums) as *reach*, and discount them against Battery Notes accordingly.
- **Entity names are unverified.** Every claim below about what an upstream exposes is
  drawn from that integration's own documentation, not from a device in hand or an
  entity registry dump. Confirm the actual entities before committing to a mapping —
  several integrations publish a life percentage only on some models.

**`battery_notes` sits at 14,437**, which makes it the yardstick: the existing glue's
upstream. Anything above that line has more reach than the one already shipped.

## What makes a good glue target

Battery Notes works as glue because it is *N replaceable things per device, each with
a life signal and a reset action*. That shape maps onto Home Keeper with almost no
logic in between, and `sensor_tasks.py` already covers the three signal shapes a
candidate can offer:

| Upstream signal | Home Keeper mode | Example |
|---|---|---|
| A meter that counts up (hours, cycles, kilometres, pages) | `usage`, with `also_every` as a time backstop | "every 10,000 km or 12 months, whichever comes first" |
| A numeric level that falls toward a limit | `threshold` | filter life crosses below 10% |
| A flag or string state | `state` | "filter needs cleaning" flips on |
| A date published ahead of time | `add_task` / `trigger_task` | bin collection tomorrow |

The second thing to look for is a **reset action** on the upstream — a button or
service that says "this consumable was replaced". That is what makes two-way sync
possible: it is the partner for the `home_keeper_task_completed` listener, exactly as
Battery Notes' "replaced" is today. A candidate with a life signal but no reset action
still works; it just syncs one way.

## Tier 1 — biggest reach, near-identical shape to Battery Notes

### Paper printers — ~204k

`ipp` 156,178\*, `brother` 46,350\*, `hpprinter` 1,654

Brother is the standout target. On its **laser** models it exposes *remaining life* for
the drum, fuser, belt, laser and PF kit alongside four toner levels — up to nine
consumables on a single device, which is the same multiplicity that makes Battery Notes
worth automating. Inkjets carry ink levels and little else, so the multiplicity
argument holds for part of that 46,350, not all of it; size the laser share before
leaning on it. IPP
carries marker levels across a much larger install base. Threshold tasks at a low-level
crossing, and this is the strongest tie-in to `inventory` / `shopping` in the whole
list: low toner is both a task and a reorder.

### Robot vacuums — ~95k

`roborock` 50,589\*, `dreame_vacuum` 15,017, `roomba` 11,047\*, `ecovacs` 10,076\*,
`xiaomi_cloud_map_extractor` 3,463, `robovac` 1,623

Filter, main brush, side brush, sensor-dirty and mop-pad "time left" sensors, plus a
per-consumable **reset button**. Six tasks per robot, and the reset gives the two-way
sync a real hook. Because a triggered task persists instead of being recreated, the
completion history accumulates into an actual observed cadence per consumable.

### Appliance care cycles — ~87k

`home_connect` 27,174\*, `lg_thinq` 24,898\*, `miele` 10,137\*, `smartthinq_sensors`
10,002, `home_connect_alt` 3,901, `hon` 3,331, `connectlife` 2,296,
`electrolux_status` 1,924

Cycle counters drive `usage` tasks: clean the washer drum every 30 washes, descale the
machine, rinse the dishwasher filter. LG's ThinQ surfaces a tub-clean counter directly.

### HVAC and boiler service — ~81k

`overkiz` 16,107\*, `midea_ac_lan` 12,627, `tado` 11,513\*, `melcloud` 6,889\*,
`daikin_onecta` 6,605, `daikin` 6,294\*, `vicare` 5,920\*, `sensibo` 5,894\*,
`panasonic_cc` 3,202

Two usable signals: a "filter needs cleaning" flag (`state` mode) and runtime or burner
hours (`usage` with an annual `also_every`). Viessmann via `vicare` is the cleanest of
these — burner hours and burner starts map onto a real service interval without
interpretation.

### Waste collection — ~34k

`waste_collection_schedule` 23,467, `afvalbeheer` 3,336, `afvalwijzer` 2,131,
`afvalinfo` 1,213, `uk_bin_collection` 1,111, `affalddk` 700, `recycle_app` 641,
`garbage_collection` 435, `posten` 380, `min_renovasjon` 331

A different shape from the rest: date-driven rather than condition-driven, so the glue
arms a task the evening before each collection via `add_task` / `trigger_task` rather
than reading a level. One glue covers all ten upstreams, because they all publish the
same next-collection-date sensor. `waste_collection_schedule` on its own is the largest
single domain in the custom feed once the infrastructure integrations are set aside.

### Vehicle odometers — ~43k across 24 domains

`kia_uvo` 5,664, `tesla_custom` 4,509, `tesla_fleet` 4,485\*, `myskoda` 4,372,
`renault` 4,062\*, `mbapi2020` 2,581, `volkswagencarnet` 2,000, `audiconnect` 1,875,
`fordpass` 1,778, `stellantis_vehicles` 1,748, `cardata` 1,650, `toyota` 1,313, and a
dozen smaller ones

The best conceptual fit on the list, and the case `usage` + `also_every` was built for.
The catch is distribution: no single upstream clears 5,700, so a branded glue per
marque is a poor trade. Build **one odometer-agnostic glue** that binds any distance
sensor and ships service-interval templates, and the whole 43k is addressable at once.

## Tier 2 — smaller, but excellent fit

- **3D printers — ~40k.** `bambu_lab` 20,137, `octoprint` 8,629\*, `moonraker` 5,179,
  `prusalink` 2,802\*, `ha_creality_ws` 1,320, `elegoo_printer` 1,067. Print hours
  drive lubricate-the-rails, replace-the-nozzle and clean-the-plate tasks. Bambu alone
  outweighs Battery Notes.
- **Oral-B — 16,756\*.** A session counter and a brush head that wants replacing every
  three months. A trivial mapping, and one of the few candidates that is a *household*
  chore rather than a gadget chore.
- **Air purifiers — ~25k.** `vesync` 12,277\*, `dyson_local` 4,731,
  `philips_airpurifier_coap` 2,817, `hass_dyson` 1,638, `ha_blueair` 1,070, `winix`
  987, `ac_infinity` 771. Filter life is a first-class percentage on all of them, so a
  `threshold` task is a few lines of mapping.
- **UPS batteries — 23,333\*.** `nut` publishes a battery manufacture date and a
  replace-battery self-test flag. The closest thing on the list to a second Battery
  Notes.
- **Irrigation — ~15k.** `rachio` 6,983\*, `bhyve` 3,501, `smart_irrigation` 1,782,
  `opensprinkler` 1,155, `irrigation_unlimited` 745. Seasonal work: winterize, blow out
  the lines, clean the filter, replace valve batteries.
- **Robot mowers — ~12k.** `landroid_cloud` 4,648, `mammotion` 3,698,
  `husqvarna_automower` 2,406\*, `dreame_mower` 1,054. Blade hours drive blade
  replacement; Landroid exposes blade wear directly.
- **Pets — ~11k.** `litterrobot` 4,516\*, `tractive` 2,575\*, `petkit` 1,984,
  `petlibro` 1,299. Fountain filter every 30 days, desiccant, litter change. Sits
  naturally beside the Pawsistant companion.
- **Smoke and CO alarms — ~7k.** `xsense` 4,712, `nest_protect` 2,658. A small install
  base carrying the most homeowner-ish chore there is: the monthly test, and the
  ten-year unit expiry.
- **CPAP — 1,191.** `resmed_myair` reports usage hours, which is the meter behind mask,
  filter and tubing replacement intervals. Tiny, but an exact fit.
- **Water treatment — ~4k.** `gruenbeck_cloud` 535, `aqua_temp` 535, `grohe_smarthome`
  511, `ecowater_softener` 318, plus spa and pool integrations. Salt refill, filter
  change, water testing — one-to-one mappings, small audiences.

## Recommendation

1. **Printers**, Brother specifically — the highest consumable multiplicity per device,
   the largest reach, and the only category that exercises `inventory` / `shopping`
   alongside tasks.
2. **Robot vacuums** — the biggest category that also offers a genuine reset action, so
   two-way sync is real rather than best-effort.
3. **Waste collection** — one glue, ten upstreams, and a chore every household already
   has whether or not it owns a gadget.

The vehicle glue is the most elegant fit for sensor-driven tasks but pays out slowest,
because its install base is split across 24 domains; it is worth building
odometer-agnostic or not at all.

Each of these also earns a `companions_catalog.py` entry once its glue exists, so an
install of the upstream surfaces the suggestion in **Settings → Companions**.
