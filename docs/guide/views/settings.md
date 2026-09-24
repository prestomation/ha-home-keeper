# Settings

The **Settings** tab in the panel edits the integration options. The form matches the
Home Assistant options flow and saves each change immediately. The same options are
available in the options flow under **Settings → Devices & services → Configure** and
through the `home_keeper.set_options` service.

The tab has 7 sections:

- **General** sets how long completed one-off tasks are kept.
- **Shopping list** selects the to-do list that
  [buy reminders are synced to](../appliances/appliances.md#send-buy-reminders-to-your-shopping-list).
- **Profiles** holds the saved filters. See
  [Profiles](./profiles.md).
- **Notifications** holds the notification configurations. See
  [Notifications](./notifications.md).
- **Problem sensor sync** has the sync switch and the exclusions for entities and
  devices and areas and labels. The exclusions apply only when the sync is on.
- **Companions** lists the integrations that work with Home Keeper.
- **Import and export** saves your data to a file and reads a file back. It also
  holds the [appliance report](../automation/import-export.md#appliance-report).
  See [Import and export](../automation/import-export.md).

![The Home Keeper Settings tab, showing the General, Shopping list and problem-sensor sync cards](../../images/17-panel-settings.png)

#### Companions

A companion is an integration that works with Home Keeper. Examples are a pet-care
tracker that creates recurring tasks and a glue integration that turns a low battery
into a replacement task. The **Companions** section at the end of the Settings tab
lists them in 2 groups:

- **Connected** lists the companions that registered themselves with Home Keeper.
  Examples are [Pawsistant](https://github.com/prestomation/pawsistant) and the
  [Battery Notes glue integration](https://github.com/prestomation/ha-home-keeper-battery-notes).
  Each row has a **Configure** button that opens the companion's own page.
- **Suggested** lists popular integrations that Home Keeper detects from a catalog
  and that have no glue integration installed. An example is **Battery Notes**. Each
  row has an **Install** link and a **Dismiss** button.

To add a companion or a [glue integration](../../GLUE_INTEGRATIONS.md) to the catalog,
[open a GitHub issue](https://github.com/prestomation/ha-home-keeper/issues/new?title=Companion%20suggestion:%20).

![The Companions section on the Settings tab: connected integrations with Configure buttons](../../images/21-panel-companions.png)

##### Declarative companions (config-driven, no separate integration)

A **declarative companion** is a recipe. The recipe targets an integration, or it
matches entities through an entity id filter. The recipe sets a trigger mode: usage,
threshold, state, or availability. The recipe also sets a Jinja template for the task
name and the task notes.

Home Keeper opens one managed task for each entity that matches the recipe. The task
clears when the condition recovers. A task that a recipe made has an **Edit recipe**
button on its detail page. The button opens the recipe that made the task.

Each task that a recipe makes is a sensor-based task, so it has no due date until
its condition is true. A task with no due date shows as **Monitored** and stays off
the to-do list and the calendar. When the condition becomes true, Home Keeper sets
the due date to that moment, so the task is due now and then overdue. The age of an
overdue task shows how long the condition has been true. In the **Firmware update
available** preset, a device with an update pending shows an overdue task, and a
device with no update pending shows **Monitored**. All bundled presets complete the
task automatically when the condition recovers, so those tasks offer no Done button.

The *Add from preset* picker offers 2 presets.

- **Device Pulse** targets the per-device ping sensors from
  [studiobts/home-assistant-device-pulse](https://github.com/studiobts/home-assistant-device-pulse).
  The Device Pulse integration must be installed.
- **Firmware update available** matches every `update.*` entity that reports `on`.
  This covers UniFi, ESPHome, HACS, Reolink, and Bambu Lab.

A preset writes the task name and notes in the Home Assistant language. A later change
of the language changes the tasks to the new language. When a recipe has your own name
or notes, Home Keeper uses your text.

Low batteries have no preset. The [Battery Notes glue
integration](../../GLUE_INTEGRATIONS.md) already opens a task for each battery and
also supplies the battery type and the count. Write a recipe for a low-battery
`binary_sensor` if you do not use that glue integration.

The *Add companion* dialog shows a live preview of the matches before you save. A
warning shows above 50 matches. A recipe cannot match more than 500 entities. See
[INTEGRATING.md](../../INTEGRATING.md) for the service reference.

The *Which entities?* section of the dialog has the integration and the entity domain.
Click **More filters** to see the other filters. Set a device class there, or write an
entity id regex. You can also limit the recipe to some areas or to some labels. An
entity that has no area of its own uses the area of its device. When **More filters**
is closed, its row shows how many filters and exclusions are set.

The **Exclusions** block under the filters removes entities from the recipe. Select
the entities, devices, areas or labels to exclude. Home Keeper then makes no task for
an entity that matches one of them. This is the same as the exclusions of Problem
sensor sync.

Each row in the preview has an **Exclude** button. Click it to exclude that entity.
The entity then shows under the matches with an **Include** button, which adds it
back. The preview shows 10 matches at most. To exclude an entity that is not in the
preview, select it in the excluded entities list.

![The recipe dialog with More filters open and one excluded entity in the Exclusions block](../../images/21j-panel-declarative-filters.png)

![The same dialog on a phone, with an Exclude button on each preview row](../../images/21k-panel-mobile-declarative-filters.png)

![The two-card preset picker modal (Device Pulse disabled because the upstream integration isn't installed)](../../images/21c-panel-declarative-preset-picker.png)

![The Add dialog seeded from the Firmware update available preset, with the live-preview panel on the right](../../images/21d-panel-declarative-add-dialog.png)

![The page of a task a recipe made, with an Edit recipe button and no Done button while the task is monitored](../../images/21e-panel-declarative-task-detail.png)

A recipe you switch off keeps the tasks it made. The tasks stop until you switch the
recipe on again. Their history stays with them. Delete the recipe to remove its
tasks.

Each recipe gets a row under **Settings → Companions** with an Edit button and a
Delete button. On a phone the row stacks, and the buttons take a line of their own.

![A recipe row in Settings, Companions: the name with its Enabled and Preset chips, then Edit and Delete](../../images/21h-panel-declarative-row-actions.png)

![The same recipe row on a phone, with Edit and Delete on a line under the name](../../images/21i-panel-mobile-recipe-row.png)
