# Integration presets: the gaps

**Status: future work.** Nothing here is committed scope.

## Why this file exists

Many integrations report the wear of the device they control. A robot vacuum reports
the hours left on its filter. A printer reports its toner level. A dishwasher reports
that its salt is low. A car reports its odometer. Home Keeper can turn each of these
readings into a task with a declarative companion, and a preset for each integration
can ship that companion ready to use.

A survey of about 225 popular integrations found about 480 such readings. About 330
of them fit a declarative companion as it is today:

| Reading | Mode that fits |
|---|---|
| Percent left (filter, toner, brush) | `threshold`, below N, auto-clear |
| Time left (hours to the next part change) | `template` that converts the unit, auto-clear |
| Measurement too low or too high (boiler pressure, humidity) | `threshold`, auto-clear |
| Wear counter that the device resets | `threshold`, above N, auto-clear |
| Alert state (salt low, descale now) | `state`, or `template` for "not OK" |
| Lifetime hour counter (print hours, burner hours) | `usage`, target N |

The other readings need a change to Home Keeper first. Each gap below says what the
change is, which readings it opens, and one way to build it.

## 1. Run-time counter mode

**Opens:** about 40 readings. Robot mowers, air conditioners, heat pumps, washers and
dryers often report only a state, such as `mowing`, `cool` or `running`. They report
no hour counter.

**Idea:** a new sensor mode, `runtime`. It adds up the time that the entity spends in
a list of states (or that an attribute holds one of a list of values), and arms the
task after N hours. A completion sets the total back to 0. The total must survive a
restart, so store it on the task like the `usage` baseline, and write it at most every
few minutes. Time while the entity is `unavailable` does not count.

## 2. State-change counter mode

**Opens:** about 20 readings, nearly all of them smart locks. A lock has no wear
sensor, but each change to `locked` is one cycle of the mechanism.

**Idea:** a new sensor mode, `count`. It counts the changes into a given state and
arms the task after N changes. A completion sets the count back to 0. Store the count
on the task, as for `runtime`.

## 3. Press a button when the task is done

**Opens:** about 100 readings get better. Robot vacuums and air purifiers count down
the life of each part and have a reset button for it. When a person marks the task
done in Home Keeper but does not reset the counter in the device, the threshold never
crosses again, so the task never comes back.

**Idea:** an optional `on_complete` action on a companion: press the `button` entity
on the same device whose key matches a given key. A preset names the pair, for
example `filter_time_left` with `reset_air_filter_consumable`. This also lets these
tasks allow Done, which auto-clear blocks today.

## 4. Unit-aware usage targets

**Opens:** about 60 readings, mostly car odometers and charger energy counters. An
odometer reports kilometres or miles, depending on the Home Assistant unit system,
and a `usage` target is in the unit of the entity. A preset cannot ship one number
that is right for both.

**Idea:** let a `usage` target carry its own unit (`km`, `mi`, `h`, `kWh`), and convert
the reading to that unit before the comparison, with Home Assistant's own unit
converters. A reading in a unit that does not convert decides nothing.

## 5. Device filter

**Opens:** about 20 readings. Some duties apply only to some models of a device. For
example, a carbon rod service applies to one printer model and not to the others from
the same integration. Some integrations use one entity key for every kind of
appliance, so the key alone cannot tell a washer from a dryer.

**Idea:** selection filters on the device: `models` and `manufacturers` (a match on
part of the text, ignoring case), and `device_has_keys`, which matches only when the
device also has an entity with one of the given keys.

## 6. One task for several entities

**Opens:** about 12 readings. Some appliances report one duty on more than one
entity, such as "salt low", "salt empty" and "program blocked, no salt". Today each of
those entities gets its own task.

**Idea:** a companion option to group the matches by device. The device gets one
task, which arms when any of its entities meets the condition and clears when all of
them recover.

## 7. Matching without a translation key

**Opens:** integrations that set no `translation_key` on their entities, which is
common in custom integrations. Today they need an `entity_regex`, which breaks when a
person renames the entity or uses Home Assistant in another language.

**Idea:** a `key_suffixes` filter that matches the end of the entity id, and the end
of the entity's `unique_id`, which a rename does not change. Keep it limited to one
integration, so that a short suffix cannot match entities of other integrations.

## 8. Preset bundles

**Opens:** faster setup. An integration with 8 parts that wear needs up to 3 presets,
one for each type of trigger, and each preset is added on its own.

**Idea:** a bundle groups the presets of one integration. **Add all** saves each
companion in the bundle with its defaults, and the person can edit each one after.

## 9. Weekly check of the preset keys

**Done, as a skill.** Each catalog entry pins the upstream commit we last read, and the
weekly `preset-upkeep` skill (`.claude/skills/preset-upkeep`) runs the check, fixes or
adds presets and opens one draft PR. The original idea follows.

**Opens:** confidence that the presets still work. An integration can rename or remove
an entity key in a new release, and a preset that names that key then matches nothing
without an error.

**Idea:** a scheduled workflow that runs `ci/check_preset_keys.py` each week, which
looks for each key in the source of its integration. When a key is gone, the workflow
opens an issue that names the preset. It never blocks a pull request, because a change
in another project must not stop our merges.

## 10. Device-first suggestions

**Opens:** discovery. A person with a Roborock may not know that a Roborock preset
exists.

**Idea:** in the preset picker, and as a notice in Settings, list the devices that
match a preset the person has not added: "Your Roborock S7 has 7 parts Home Keeper can
track." One click opens the preset.

## 11. Adopt as normal tasks

**Opens:** a choice of ownership. A companion owns its tasks and locks some fields.
Some people want the tasks to be their own, to edit freely.

**Idea:** an **Adopt** action on a preset that makes ordinary sensor tasks with the
same bindings, once, and saves no companion. New devices then do not get tasks
without the person's action, which is the trade-off.
