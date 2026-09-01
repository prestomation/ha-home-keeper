# CalDAV / Nextcloud to-do sync — exploratory testing findings

Investigation of [#267](https://github.com/prestomation/ha-home-keeper/issues/267), run
against a real Nextcloud 34.0.3 talking to Home Assistant's built-in `caldav`
integration, with Home Keeper's profile to-do sync pointed at the resulting `todo.*`
entity.

**Headline: the feature already works, and a separate bug was found while testing it.**
No new "CalDAV support" is needed — HA's `caldav` integration already exposes a task list
as a `todo` entity, and Home Keeper's existing profile sync drives it two-way. But CalDAV
lists have one property no other supported provider has, and Home Keeper's sync
mishandles it: **an item added to a CalDAV list is not readable back for up to a second
afterwards.** Home Keeper reads the list, does not find the item it just added, concludes
the add failed, and adds it again. The duplicate is permanent, and every later edit
reaches only one of the two copies.

**That bug is not, on the evidence here, what the reporter hit.** It reproduced only on a
*bulk* first sync — a burst of adds, always duplicating the tail — and never on a single
add. The reporter's failing case was one task created in Home Keeper, and every
single-task run in this session synced cleanly and propagated its due-date change within
seconds. **Their symptom was not reproduced.** See "The one thing that did not reproduce"
below for what is still open.

---

## The environment

| Piece | What was used |
| --- | --- |
| Home Assistant | **2026.8.3** (`ghcr.io/home-assistant/home-assistant:stable` as of 2026-09-01), the repo's `tests/integration` compose stack |
| CalDAV server | `nextcloud:apache` 34.0.3, SQLite, on a shared Docker network |
| HA integration | built-in `caldav`, pointed at `http://nextcloud/remote.php/dav` |
| Python CalDAV lib | `caldav` 2.1.0 (vendored in the HA image) |
| Home Keeper | this branch, one profile with `sync.entity_id = todo.chores` |

Reproduction scripts are not committed — they drove HA over its REST/WebSocket API and
Nextcloud over raw CalDAV `REPORT`/`PUT`/`DELETE`, so every assertion below is against
the bytes on the server, not against Home Assistant's view of them.

**Every claim below about Home Assistant's internals was read out of the running
2026.8.3 container**, not from memory or documentation. They are nonetheless
**version-dependent**: the `caldav` refresh behaviour that Finding 1 turns on is an
implementation detail nobody upstream owes us, and it could be fixed (or changed) in any
release. Re-check them against the installed version before relying on them, and prefer a
fix that does not depend on them holding.

---

## Setup gotcha, before any of the sync behaviour

**Nextcloud's default "Personal" calendar cannot hold tasks.** It advertises
`supported-calendar-component-set` = `VEVENT` only. HA's `caldav` todo platform creates a
`todo.*` entity only for calendars that advertise `VTODO`
(`SUPPORTED_COMPONENT = "VTODO"` in `caldav/todo.py`), so out of a stock Nextcloud you
get `calendar.personal` and **no** `todo.personal`.

Verified against the live server:

```
/remote.php/dav/calendars/admin/personal/   -> <comp name="VEVENT"/>
/remote.php/dav/calendars/admin/chores/     -> <comp name="VEVENT"/> <comp name="VTODO"/> <comp name="VJOURNAL"/>
```

The `chores` collection was made with `occ dav:create-calendar`; in the UI the same thing
happens when you add a **task list** in the Nextcloud Tasks app. Users who see no `todo`
entity after adding the CalDAV integration are almost always looking at a VEVENT-only
calendar. Worth a line in the README's to-do sync section.

Once the list exists, the entity reports `supported_features: 119` — create, delete,
update, due date, due datetime, description; everything Home Keeper's planner asks for
except `MOVE_TODO_ITEM`, which it never uses.

---

## What works

Every one of these was confirmed by reading the VTODOs back off Nextcloud.

| Direction | Result |
| --- | --- |
| Create a task in Home Keeper | Item appears, with `DUE;VALUE=DATE`, `SUMMARY` and `DESCRIPTION` |
| Change the due date in Home Keeper | `DUE` moves, within seconds |
| Rename in Home Keeper | `SUMMARY` follows |
| Change notes in Home Keeper | `DESCRIPTION` follows |
| Complete in Home Keeper | Item flips to `STATUS:COMPLETED` |
| Tick the item off on the server | Task completes in Home Keeper, recurrence reschedules, a **fresh** VTODO is written for the next occurrence |
| Delete the task in Home Keeper | Its item is removed from the server |
| A VTODO written in Nextcloud that Home Keeper never wrote | Left strictly alone — not imported, not deleted |

So the reporter's second and third observations — completing on the server, and deleting
in Home Keeper — are working as designed, and the sync is genuinely two-way. Notably,
**the due-date change they reported as broken worked every time it was tried here**, on a
single task, within seconds.

---

## Finding 1 — Home Keeper mints permanent duplicate items on CalDAV lists

**Severity: high. Reproduced 4 times out of 4** on a bulk first sync. Found while
testing; **not** something the reporter described, and see the caveat at the end of this
section before treating it as their bug.

### The precondition CalDAV alone has

`todo.add_item` on a CalDAV list returns **before** the new item is visible to
`todo.get_items`. HA's CalDAV entity saves to the server, then refreshes its own cache in
a fire-and-forget background task — the comment in `caldav/todo.py` says so outright:

```python
await self.hass.async_add_executor_job(partial(self._calendar.save_todo, **item_data))
# refreshing async otherwise it would take too much time
self.hass.async_create_task(self.async_update_ha_state(force_refresh=True))
```

Measured directly, five times in a row, on a local container with a sub-100 ms round
trip:

```
add 'race probe 1' returned in 84ms; get_items sees 1: >>> MISSING <<<
    after 2s: PRESENT (server has 2)
add 'race probe 2' returned in 61ms; get_items sees 2: >>> MISSING <<<
    after 2s: PRESENT (server has 3)
...
```

and for a burst, the tail of the burst is the part that stays invisible:

```
five adds took 251ms
t+ 0s  HA sees  4  server has  5  missing from HA: ['burst 5']
t+ 1s  HA sees  5  server has  5  missing from HA: []
```

CalDAV is the outlier among the providers Home Keeper's sync targets, and the difference
is one `await`:

| Integration | End of `async_create_todo_item` |
| --- | --- |
| `local_todo` | `await self.async_update_ha_state(force_refresh=True)` |
| `todoist` | `await self.coordinator.async_refresh()` |
| `caldav` | `self.hass.async_create_task(self.async_update_ha_state(force_refresh=True))` |

So on every other target the item is readable the instant the call returns, and Home
Keeper's assumptions hold. Against a real Nextcloud over a LAN or the internet the CalDAV
window is far wider than the ~1 s seen here. This is arguably an upstream bug worth
reporting against `homeassistant/components/caldav` as well — `async_create_todo_item` is
documented as leaving the entity's state current — but Home Keeper should not depend on
that being fixed.

### What Home Keeper does with it

`todo.add_item` answers with nothing, so the planner records the new item with **no
uid** and binds one on the next pass by summary
(`todo_list.py`, the add loop — `plan.tracked[key] = _entry(target, None, want)`).

The next pass fires immediately, because writing to the list changes its state and
`_handle_state_change` forces a pass. That pass reads a list that does not contain the
item yet, so `resolve_tracked` returns `None`, and control reaches this branch
(`todo_list.py`, in `plan_sync`):

```python
if item is None:
    if want is None:
        continue
    sync = profile["sync"]
    if entry.get("uid") and sync["two_way"] and sync["vanish_as_completed"]:
        plan.complete.append(CompleteOp(key, task_id))
        settled.add(key)
    continue          # <- key never written to plan.tracked
```

With no uid the entry is simply dropped — deliberately, per the module docstring: *"an
entry that never captured a uid has no proof its add ever landed, so it is re-added,
never completed."* The second loop then finds `key not in plan.tracked` and plans a
**second** `AddOp`. Two VTODOs, two uids, one task.

The reasoning is sound for a list that answers reads honestly. It assumes "I cannot see
it" implies "the add failed". On CalDAV it usually means "the add succeeded and the
cache has not caught up".

Two adjacent races are worth ruling out explicitly, because both are natural things to
suspect and neither is what is happening:

- **A refresh landing between `plan_sync`'s two loops.** It cannot. `plan_sync` is pure
  and synchronous over an `items_by_entity` snapshot captured before it is called, with
  no `await` anywhere inside, so both loops see byte-identical input. The window is
  strictly *between* passes.
- **A half-built list snapshot.** Also no. `WebDavTodoListEntity.async_update` assigns
  `self._attr_todo_items` once, wholesale, after the executor job returns the complete
  search result — there is no moment where a caller sees half a list. What *can* happen is
  an older complete snapshot overwriting a newer one when two fire-and-forget refreshes
  are in flight, which is the same missing-recent-item shape and not a separate bug.

### Reproduction

Sync a profile with 10–11 matching tasks onto a fresh CalDAV list, four times, clearing
the server in between:

```
round 1: HK wants 11, server has 12  dupes={'Renew passport': (2, 1)}
round 2: HK wants 11, server has 11  dupes={'Replace T&P relief valve …': (2, 1)}  missing={'Renew passport': (0, 1)}
round 3: HK wants 10, server has 12  dupes={'Replace furnace filter': (3, 2), 'Replace T&P relief valve …': (2, 1)}
round 4: HK wants 10, server has 12  dupes={'Replace furnace filter': (3, 2), 'Replace T&P relief valve …': (2, 1)}
```

The duplicated entries are always at the tail of the add burst, which is exactly the part
still invisible when the follow-up pass reads.

### What a duplicate does to later edits

Once a duplicate exists, Home Keeper's bookkeeping points at exactly one of the two
copies and never learns about the other. Planting the duplicate by hand and then changing
the due date in Home Keeper:

```
before:  Dupe probe | DUE:20261005 | UID:c78f0766-…      <- tracked
         Dupe probe | DUE:20261005 | UID:planted-duplicate <- orphan

after:   Dupe probe | DUE:20261224 | UID:c78f0766-…      <- moved
         Dupe probe | DUE:20261005 | UID:planted-duplicate <- frozen forever
```

Deleting the task in Home Keeper afterwards removes the tracked copy and leaves the
orphan on the server permanently:

```
after delete:  Dupe probe | DUE:20261005 | UID:planted-duplicate
```

In the Nextcloud Tasks app the two copies are indistinguishable, so a user looking at the
orphan would see a task that syncs on create and then never updates again — which *reads*
like the reported symptom.

**Do not treat that as the explanation.** Two things argue against it:

- The duplicate never appeared on a single add, only at the tail of a burst. The
  reporter's failing case was one task created in Home Keeper.
- Nobody in #267 reported seeing duplicate items, and two identical entries in the
  Nextcloud Tasks app are hard to miss — especially for someone methodical enough to
  write up five numbered test cases.

The resemblance is suggestive, not evidence.

### Fix options

1. **Force the target list to refresh before the pass that would re-add.** After any
   successful `add_item`, `await homeassistant.helpers.entity_component.async_update_entity(...)`
   on that entity, so the next read sees a real snapshot. Turns "cannot see it" back into
   honest evidence. Costs one extra CalDAV round trip per pass that adds anything, and
   only on passes that add.
2. **Give a uid-less entry a grace period in the planner.** Keep the entry in
   `plan.tracked` the first time it resolves to nothing, with an attempt counter, and only
   drop it (and therefore re-add) once it has been unseen across two passes. This is a
   pure-planner change and unit-testable, which suits the mutation gate. Note a
   genuinely-failed add is *already* retried immediately by a different path —
   `_apply` does `settled.pop(add.key, None)` when the call raises — so the counter only
   ever delays the case where the call succeeded, which is the case that must not re-add.
3. **Both.** (2) is the correctness fix; (1) also shortens every other latency below.

Option 2 touches only `todo_list.py`, already on the mutation allowlist, which is why it
looks like the contained one. **It is a sketch, not a design** — these have to be settled
before it is written, and one of them may sink it:

- Where does the counter live? `plan.tracked` is rebuilt from scratch each pass, so the
  count has to be carried on the persisted entry, which widens the bookkeeping shape.
- What happens on the pass where the uid finally binds while the item is still invisible?
  That combination should not arise (the uid is read *off* the resolved item), but the
  transition needs stating rather than assuming.
- The `claimed` and `settled` sets span the whole plan, so an entry held back rather than
  dropped must not claim an identity it has not resolved — otherwise two profiles syncing
  onto one list could deadlock each other out of a line.

Neither option is validated here. Both are directions.

---

## Finding 2 — inbound changes wait on a poll, up to 15 minutes

**Severity: medium (expectation-setting), not a defect.**

`caldav/todo.py` sets `SCAN_INTERVAL = timedelta(minutes=15)`, and nothing pushes: CalDAV
has no change notification HA subscribes to. `todo.get_items` reads the entity's cached
`todo_items` and does not force a refresh, so Home Keeper never sees the server sooner
than that cache does.

There are two delays stacked here, and it is worth keeping them apart:

1. **Server → HA cache.** The 15-minute poll — *unless* something forces a refresh
   first. Every Home Keeper write to that list does: `add_item` / `update_item` /
   `remove_item` each end with a `force_refresh` on the CalDAV entity. So a list Home
   Keeper is actively writing to gets refreshed as a side effect, and a quiet one waits
   the full 15 minutes.
2. **HA cache → Home Keeper.** Either instant (the list's state changes, which forces a
   pass) or the 5-minute periodic sweep.

Both were measured. A VTODO ticked off on Nextcloud in a quiet window produced no
reaction for 90 s, then reacted within 2 s of a forced `homeassistant.update_entity` —
delay 1:

```
t+  5s  todo.chores=1  HK last_completed=None
...
t+ 90s  todo.chores=1  HK last_completed=None
=== force HA to poll ===
+  2s   HK last_completed=2026-09-01T02:37:21-04:00  next_due=2026-12-01T02:37:21-05:00
```

A second run showed delay 2 in isolation, and it is the more interesting of the two. The
tick landed 1 s before a refresh Home Keeper's own write had already triggered, so the
cache was fresh at 02:45:54 (confirmed in the HA log — that is the last CalDAV server
call before the reaction). Home Keeper still did not act until **02:50:53, exactly one
5-minute sweep later**, because the item count did not move: probe A went completed and
probe B was added in the same window, so `todo.chores` stayed at 1 and no state-change
event fired.

That is the case `async_schedule_sweep`'s own docstring calls out — *"a list whose
outstanding count happens to land back where it started — one item ticked off while
another was added — produces no state change at all, so the listener alone can miss a
tick-off"* — working exactly as designed. The sweep is the safety net, and it caught it.

So the worst case is 15 min + 5 min, the common case on an active list is under 5 min,
and neither is a defect. What follows from it:

- **Document it.** "Ticking an item off on a CalDAV server can take up to 15 minutes to
  reach Home Keeper" belongs in the README's to-do sync section, next to the Todoist
  recipe.
- **Optionally shorten it.** Home Keeper's periodic sweep could call
  `homeassistant.update_entity` on each synced list before reading it, which would
  collapse delay 1 into delay 2 and bound the whole thing by Home Keeper's own 5-minute
  tick. That is a network round trip per synced list per 5 minutes against somebody
  else's server, so it should be a deliberate choice, not a silent one.

---

## Finding 3 — a write that fails while the server is down is only retried on the sweep

**Severity: low.** Nextcloud was stopped, a new matching task was created in Home Keeper,
and Nextcloud was restarted.

While the server was down the entity did **not** go unavailable — it only polls every 15
minutes, so HA had no idea. Home Keeper therefore read a stale-but-plausible list, planned
the add, and the `todo.add_item` call failed. That is handled correctly: `_apply` drops
the entry so the next pass retries, and Home Keeper itself stayed healthy throughout
(`_call` swallows the failure, `async_sync` never raises).

What is worth knowing is what wakes the retry. Nothing about the server coming back
produces a task event or a list state change, so the retry waits for the **5-minute
periodic sweep** — measured at 248 s after recovery, which is that sweep and not
anything faster:

```
t+  0s  server has: ['Offline probe A']
t+104s  still ['Offline probe A']
t+228s  still ['Offline probe A']
t+248s  >>> 'Offline probe B' landed <<<
```

Forcing an entity refresh does not help unless the item count changes, because it is the
*state change* that forces a Home Keeper pass. Self-healing, but slower than it looks,
and silent — the failure is logged at `debug` only:

```python
except Exception as err:  # never break the mutation that triggered us
    self._logger.debug("todo.%s on %s failed: %s", service, entity_id, err)
```

For a self-hosted CalDAV server that goes down regularly, a repeated failure against a
configured target is arguably worth the `_warn_once` treatment the missing-list and
unsupported-feature paths already get.

---

## The one thing that did not reproduce — the reporter's due-date symptom

Their first observation was: a task created in Home Keeper reached Nextcloud, then
changing its due date in Home Keeper never reached Nextcloud, over 13 hours and several
reloads of both integrations.

**That did not happen once here.** Every single-task run created the item and then moved
its `DUE` within seconds of the change:

```
after add_task:     CalDAV probe | DUE;VALUE=DATE:20261005 | DESCRIPTION:first notes
after due change:   CalDAV probe | DUE;VALUE=DATE:20261224 | DESCRIPTION:first notes
after rename:       CalDAV probe renamed | DUE;VALUE=DATE:20261224
after notes change: CalDAV probe renamed | DUE;VALUE=DATE:20261224 | DESCRIPTION:second notes
```

The update path itself is sound. Home Assistant's `todo.update_item` merges over the
existing item (`dataclasses.asdict(found)` then the changed fields) rather than replacing
it, so a due-only update keeps the summary and description; and `_api_items_factory`
serializes `due` with `isoformat()`, so the planner's `str(item["due"])[:10]` comparison
reads the right date whether the server stored a `DATE` or a `DATE-TIME`.

Hypotheses still open, roughly in order of how much they'd explain:

1. **They changed the time of day, not the date.** `desired_by_sync` truncates `next_due`
   to a date, so a change that leaves the date alone produces no CalDAV write at all and
   would look exactly like this — indefinitely, through any number of reloads. This is
   the only hypothesis that survives 13 hours without needing anything to be broken.
2. **The task stopped matching the profile in a way that produced no visible change.**
   Worth asking which Include tier their profile uses.
3. **Their `todo.update_item` was failing** — a uid Nextcloud no longer had, a permission
   problem — which `_call` swallows at `debug` level, so nothing would appear in a normal
   log. Finding 3's silence applies here too.

**What to ask them:** which field they edited and whether the *date* changed; their
profile's Include tier; and a `custom_components.home_keeper` debug log across one edit.
Without that this stays unexplained — and the honest reply on #267 says so rather than
offering the duplicate as an answer.

---

## What is expected, and what Home Keeper can and cannot do

Worth stating plainly, because the issue thread has two different asks tangled together.

**Home Keeper syncs *its* tasks onto a list. It does not adopt a list's tasks.** The
`todo` entity is a delivery surface. A VTODO written in Nextcloud that Home Keeper never
created is left alone — not imported, not renamed, not deleted (confirmed: a hand-written
`foreign-probe-1.ics` survived every subsequent pass untouched). That is the documented
design, and it is the right one: a Home Keeper task carries recurrence, a device, an
area, labels, consumables and completion history, none of which a VTODO can express, so
there is nothing sensible to infer from a bare summary line.

So for the original request — *"syncing tasks to/from a caldav server"* — the honest
answer is:

- **To CalDAV: yes, fully, today.** Create, rename, reschedule, re-describe, complete,
  delete, and recurrence rescheduling all land on the server.
- **From CalDAV: completions only.** Ticking an item off completes the Home Keeper task
  (that is the whole two-way contract, same as Todoist). Creating a task *in* Nextcloud
  and having it become a Home Keeper task is not a thing Home Keeper does for any
  provider, and is a much larger feature than "CalDAV support".

**CalDAV's own limits, as opposed to Home Keeper's:**

- No push. HA reads the server on a 15-minute poll, shortened only by Home Keeper's own
  writes forcing a refresh (Finding 2).
- No uid returned on create, so the sync must bind by summary on a later pass — which is
  the window Finding 1 falls into. Once a uid *is* bound the sync resolves by it first
  (`resolve_tracked` tries uid, then falls back to summary), so same-named tasks are only
  ambiguous during that first window, not permanently.
- Due dates are date-only in practice. Home Keeper deliberately writes `DUE;VALUE=DATE`
  (`desired_by_sync` truncates `next_due` to a date, because "a to-do list works in that
  granularity"), so a task's **time of day never reaches the server** and changing only
  the time of day produces no CalDAV write at all. That is by design but is a plausible
  second reading of "I changed the due date and nothing happened".
- Nextcloud's calendars advertise their component set, and only a task list advertises
  `VTODO`.
- Deletes on the Nextcloud side go to a trashbin and read as a vanish, which with
  `vanish_as_completed` on (the default) completes the Home Keeper task.

---

## Suggested follow-ups

1. **Fix Finding 1** — the duplicate is data the user has to clean up by hand, and it
   silently breaks every later edit. Option 2 above is the contained fix. This stands on
   its own merits; it is not contingent on it being the reporter's bug.
2. **Get the missing detail on the due-date symptom** before claiming it is understood —
   which field they edited and whether the date itself moved, their profile's Include
   tier, and a `custom_components.home_keeper` debug log across one edit.
3. **README**: a short CalDAV/Nextcloud paragraph in "Send tasks to your to-do lists",
   covering the task-list-not-Personal-calendar gotcha and the 15-minute inbound delay.
4. Consider warning (not just `debug`-logging) on repeated write failures against a
   configured sync target — Findings 1 and 3 are both quiet for the same reason, and the
   third hypothesis above would have been visible if they were not.
