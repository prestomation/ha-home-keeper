# Device registry, HA 2026.8 — findings and the model decision (#183)

Scratch working doc, not user-facing. Records what the new upgrade suite *measured*,
so the device-model decision is made against evidence rather than a reading of the
code. No behaviour change ships with it.

## What changed upstream

Home Assistant 2026.8 made device identifiers and connections unique **per config
entry** instead of globally
([dev blog](https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/)).

Home Keeper's device attachment is built on the old global-merge behaviour. The whole
mechanism is `coordinator.py:344-363`:

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

The fork is nameless because `device_info_for_task` sends no `name` when it believes
it is merging. Both HA's device picker and the panel's `deviceName()` fall back to the
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

## The options

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
issue with a re-pick flow, plus snapshot auto-heal generalizing
`devices.py:280-326` `_resolve_by_snapshot` from assets to tasks. The auto-heal must
rewrite `source.<ns>.device_id` as well, or it reproduces the duplication above.

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
