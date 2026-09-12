# Upgrading to Home Assistant 2026.8

Home Assistant 2026.8 changed how a device works. A device now belongs to 1
integration instead of being shared. Home Keeper used the shared behavior to
place a task's button and sensors on the page of the device the task is about,
such as a dishwasher or a printer.

Home Keeper 0.13.0 includes the fix and repairs an install that already
upgraded. No action is needed.

#### If you already upgraded Home Assistant

Home Assistant already split the devices by the time the fix arrived. Symptoms
include:

- a second device for an existing item, sometimes labelled with a long
  identifier instead of a name
- tasks that shared a device page split across 2 entries when grouped by device
- for a companion integration such as Battery Notes or Bambu Lab, a duplicate
  task next to the original

Updating to 0.13.0 repairs all of it on the next restart. Tasks return to the
real device, and the leftover devices are removed. Duplicated companion tasks
become 1 task again. An item that has a recorded completion is never removed. History, notes, and schedules stay unchanged.

#### If you have not upgraded Home Assistant yet

Update Home Keeper first. 0.13.0 detaches from a device it does not own before
Home Assistant splits devices. Nothing then needs repair. Either order results
in a correct state.

#### Device triggers on devices of other integrations

For a task attached to a device that another integration owns, the device page
no longer lists Home Keeper triggers under Add automation. Home Assistant
offers a device's triggers only for the single integration the device belongs
to.

An automation built that way must be rebuilt on the task's own entities,
`binary_sensor.<task>_overdue` and `sensor.<task>_next_due`, or on the matching
`home_keeper_*` event. These react to the same transitions. Home Keeper
appliances are not affected and keep their device triggers.
