# Device registry, HA 2026.8 — findings and the model decision (#183)

Scratch working doc, not user-facing. Records what the upgrade suite *measured*, so
the device-model decision was made against evidence rather than a reading of the code.
Option A shipped off the back of it — see "Decision" below for what that does and does
not fix.

## What changed upstream

Home Assistant 2026.8 made device identifiers and connections unique **per config
entry** instead of globally
([dev blog](https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/)).

Home Keeper's device attachment was built on the old global-merge behaviour. The whole
mechanism was one expression in `coordinator.device_info_for_task` (now
`device_link_for_task`):

```python
return DeviceInfo(identifiers=device.identifiers, connections=device.connections)
```

Copying a foreign device's identifiers used to merge our per-task entities onto that
device's page. It now silently forks a duplicate device owned by our config entry.

## Two distinct failure modes, not one

They look identical in the UI (a device shown as a raw GUID) and have different
causes. A fix must handle both; neither implies the other.

**Fresh attach on 2026.8** — `tests/integration/test_device_attach.py`. Attaching a
task to a foreign device produces a second device carrying the same identifiers, with
`name = None`, and Home Keeper's entities land on *that*:

```
id=d4fe99a6… name='E2E Battery Device'  entries=['demo_battery_notes']
id=d71d53cb… name=None                  entries=['home_keeper_test_entry']   ← ours
  button.probe_fork_mark_done      device_id=d71d53cb…
  sensor.probe_fork_next_due       device_id=d71d53cb…
  binary_sensor.probe_fork_overdue device_id=d71d53cb…
```

The fork was nameless because the old `device_info_for_task` sent no `name` when it
believed it was merging. Both HA's device picker and the panel's `deviceName()` fall back to the
device id when `name` and `name_by_user` are unset — that is #183 item 1. The stored
`device_id` is *not* stale here; the device it points at simply has no name.

**Upgrading across the split** — `tests/upgrade/`. Home Assistant splits each merged
device into one device per config entry, copies the name onto every half, and gives
**all** of them new registry ids:

```
(bambu_lab, AC12309BH109)
  before: [('58a23187', 'X1 Carbon', ('upgrade_home_keeper_entry', 'upgrade_bambu_lab_entry'))]
  after : [('65019cdd', 'X1 Carbon', ('upgrade_bambu_lab_entry',)),
           ('18aa2ba8', 'X1 Carbon', ('upgrade_home_keeper_entry',))]
```

Every `device_id` persisted before the upgrade therefore dangles. That is the root of
#183 items 1 and 3 on the upgrade path, and it explains "no easy way to fix it": the
id points at nothing *and* `device_id` is locked.

## The glue integrations

Audited from source; `tests/upgrade` exercises all three against a real upgrade.

| Glue | Attaches to | Task matching key | Duplicates on upgrade? |
|---|---|---|---|
| `ha-home-keeper-bambu-lab` | foreign (`bambu_lab` printer) | `source.<ns>.device_id` | **yes**, 1 → 2 |
| `ha-home-keeper-battery-notes` | foreign (Battery Notes' device) | `source.<ns>.device_id` | **yes**, 1 → 2 |
| `Pawsistant` | its own dog device | `schedule_id` / `dog_id` | **no** |

**None of them has the 2026.8 mechanism bug** — no glue copies foreign identifiers
into `DeviceInfo`. The fork is entirely Home Keeper's.

What they do have is a re-keying problem, and it is worse than predicted: the
duplication happens on the **upgrade itself**, with no Home Keeper auto-heal involved.
bambu-lab and battery-notes store the device id twice — on the task and inside their
`source` namespace — and match existing tasks on the `source` copy. The split
renumbers the device, that copy matches nothing, their reconcile creates a fresh task,
and the stale one persists because neither `plan_reconcile` deletes tasks whose device
vanished. Measured:

```
home_keeper_battery_notes: 'Replace battery: Kitchen Sensor' × 2
home_keeper_bambu_lab:     'Update firmware: X1 Carbon'      × 2
pawsistant:                unchanged
```

**Pawsistant is the reference implementation.** Its `source` namespace holds
`dog_id` / `event_type` / `schedule_id` and no device id at all, so it re-keys
durably regardless of what the registry does. Note it still ends up with a dangling
`device_id` — a durable key prevents *duplication*, it does not *heal* the pointer.
Home Keeper has to do that part.

**bambu-lab already solved half of this and didn't apply it to tasks.** It keys
maintenance *options* on the printer serial explicitly "because it survives the device
registry entry being recreated" (`wiring.py:103-105`), while `task_for_device` still
matches on `device_id`. Options survive registry churn; tasks don't.

Generalized: contributed tasks need a durable re-key that is not the device id, so
Home Keeper can rewrite both copies without the contributor duplicating. That belongs
in `docs/INTEGRATING.md` as a contract, not as three local patches.

## Two findings that constrain the model choice

**Entity-level linking is the sanctioned replacement, but not a full restore.**
Setting `entity.device_entry` with `device_info = None` links an entity to a foreign
device (`entity_platform.py:951-975`); `async_device_info_to_link_from_device_id` is
deprecated and now returns `None`. It does **not** add our config entry to that device.

**So device triggers and per-device diagnostics are lost on foreign devices under
*any* fix.** `device_automation/__init__.py:247-257` resolves candidate integrations
from `device.config_entries` and from entity **domains** (`sensor`, `button`) — never
from the owning platform. `device_trigger.py` and `diagnostics.py` therefore stop
being offered on a foreign device page from 2026.8 on. This is the strongest argument
for the reporter's "always own a Home Keeper device" suggestion.

## Decision: option A, shipped

**Entity-level linking, keeping dual mode.** `coordinator.device_link_for_task` returns
a `DeviceEntry` for a task attached to a resolvable device, and the entity assigns
`self.device_entry` with no `device_info`. The self-owned `DeviceInfo` fallback stays
for a task whose `device_id` doesn't resolve.

Accepted cost: device triggers and per-device diagnostics are gone on devices Home
Keeper doesn't own. Judged acceptable because most people drive Home Keeper from the
panel or a Lovelace card rather than the device page, and the same automations remain
buildable from the task's entities or the event.

**Scope of the fix — measured, and narrower than it first looked.** The upgrade suite
originally ran *this* Home Keeper in both phases, which is not a journey any user takes
and made the fix look bigger than it is. It now runs the **previous release** in phase 1
(`ci/fetch-glues.sh` stages it; `conftest._use_home_keeper` swaps it in), so the run is a
real upgrade: old Home Keeper on old HA, then new on new. That changed the result.

*Fixed:* any attachment made by this version. Fresh attaches put entities on the real
device and create no duplicate (`tests/integration/test_device_attach.py`, both passing).
Anyone still on a pre-2026.8 Home Assistant is protected before they upgrade, because
this version never merges — including the knock-on where Home Keeper's own merge was
what dragged a companion's device into the split and made its glue duplicate tasks.

*Also fixed, by repair rather than prevention:* an install that **already** upgraded.
The merge happened under the old version, so Home Assistant had already split those
devices, handed Home Keeper its own half and moved our entities onto it. Nothing at
setup can prevent that, so `devices.async_heal_split_device_ids` undoes it instead.

The mechanism is the part worth knowing, because the obvious approach fails silently:
a stale id does **not** look stale. `dr.async_get()` synthesizes a read-only composite
device for a pre-migration id, so "does this still resolve?" answers yes and a naive
heal skips every task. What Home Assistant refuses is *linking an entity* to it, which
is the visible symptom. The supported query is
`async_get_devices_for_composite_device_id`, which returns the live devices the id was
split into; the successor to adopt is the split that isn't ours, with the composite's
former `primary_config_entry` breaking ties.

That query has a horizon: once every half has been re-homed, Home Assistant collects
the composite and the query answers the empty list it gives any ordinary id. Past that
point the only thing that can still identify the original device is a stored
identifiers/connections snapshot, which existing-kind **assets** keep (refreshed by
`_reconcile_existing`) and tasks do not. So the heal resolves tasks and assets into one
shared mapping: an id only an asset can resolve still heals the task on the same
device. Healing them from separate mappings splits one appliance across two device
pages — asset on the live device, task left on the dead id.

Duplicated contributor tasks are merged in the same pass
(`store.async_merge_split_duplicates`). Canonicalizing device ids back through
`composite_device_id` is what makes the two copies recognisable as one thing — they
point at different halves of the same original, so they look unrelated otherwise. The
survivor keeps the history but adopts the *newer* task's `device_id`, because the newer
one was created by the contributor after the split and so carries that contributor's own
answer for where the task belongs; adopting anything else just gets it duplicated again
on the next reconcile. Deletion uses `force=True` (contributed tasks are
deletion-protected, and here the integration created the duplicate and cannot clean it
up itself) and never removes a task carrying completions.

## Upgrade order matters, and only one order is clean

Measured in `tests/upgrade/test_upgrade_order.py`, which runs three separate container
paths against the same fixture:

| order | devices we own but didn't create | tasks pointing at a dead device | glues duplicated |
|---|---|---|---|
| Home Keeper first, then HA | **none** | 2 | 1 |
| HA first, Home Keeper after | 3 | 4 | 2 |
| both together | 3 | 4 | 2 |

The first row is the point. `devices.async_detach_legacy_merged_devices` drops our
config entry, at setup, from any device an earlier release merged onto but that we
don't own. Run while still on a pre-2026.8 Home Assistant, that leaves nothing of ours
joined to those devices, so Home Assistant's split has nothing to divide and every
registry id survives.

It is deliberately limited to devices that have **another** config entry besides ours.
Removing the last entry deletes the device, which would strand the entities on it —
that is the already-split leftover, and it needs entities re-pointed first.

The residual dangling tasks in the clean row belong to the `battery_notes` stub's own
merge, not to Home Keeper: it reproduces pre-2026.8 Battery Notes, so Home Assistant
splits the kitchen sensor whatever we do. Real users are less exposed, since Battery
Notes 3.0.0-dev has already moved to entity linking.

**Two false starts worth recording**, because both produced a confident wrong answer
from a harness that looked fine:

1. Running *this* Home Keeper in both phases made the fix look like it also cured the
   glue duplication. It doesn't, for anyone already upgraded.
2. A gitignored cache of the working-tree build (`home_keeper_working_tree/`) survived
   between runs, so an edit to the integration never reached the container and the
   suite reported on stale code — which is why "order doesn't matter" was the answer
   for one round. `ci/fetch-glues.sh` now stages both builds authoritatively.

## The options considered

**A — Entity-link, keep dual mode.** Swap the identifier copy for
`entity.device_entry`. Smallest change; entities still appear on the foreign device
page; no duplicate device. Accepts the permanent loss of device triggers and
per-device diagnostics on foreign devices.

**B — Always own a Home Keeper device** (the reporter's suggestion). Every task/asset
gets a Home Keeper device; foreign devices become `related_device_ids`. Keeps
triggers, diagnostics and the `configuration_url` deep link, and is immune to future
registry churn. Abandons the Battery-Notes-style "our entities on your dishwasher's
page" property, which is a stated design goal in `docs/DESIGN.md`, and needs a real
store migration.

**C — Hybrid.** Always create the Home Keeper device *and* entity-link the per-task
entities onto the foreign device. Best coverage; two device pages per appliance, which
is close to the confusion the reporter opened the issue about.

Whichever is chosen, the recovery work is the same and is already decided: a repair
issue with a re-pick flow. The snapshot auto-heal half of it has since shipped —
`devices._resolve_by_snapshot` serves both reconciliation and `_split_successor`, and
the shared mapping in `async_heal_split_device_ids` carries a snapshot-resolved device
over to the tasks on it (see the mechanism section above). It rewrites
`source.<ns>.device_id` too, or it would reproduce the duplication above.

## Follow-ups

- `docs/INTEGRATING.md`: durable re-key contract for contributed tasks.
- Unlock a `locked_fields` entry whose value no longer resolves (#183 item 3). All
  three glues lock `device_id`; fixing it here beats patching three repos.
- Document that Home Keeper entities no longer appear on another integration's device
  page — the reporter asked for this explicitly.
- bambu-lab and battery-notes: match tasks on a durable key. Separate repos.
- `companions_catalog.py` lists only `battery_notes`, so the bambu-lab glue is never
  detected or suggested in Settings → Companions. Unrelated to #183; surfaced by the
  audit.
