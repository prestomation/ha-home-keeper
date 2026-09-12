# Complete tasks with NFC/RFID tags

Home Keeper supports linking a task to a [Home Assistant
tag](https://www.home-assistant.io/integrations/tag/). When a user scans the
tag, Home Keeper completes the task. This is useful for completing a task by
scanning a tag placed on the item, without opening the dashboard.

No `tag_scanned` automation is needed. The **Done** button continues to work.

The **Require tag scan to complete** toggle blocks **Done** on every surface:

- panel
- card
- to-do list
- device button
- notifications

With the toggle on, a user completes the task only by scanning its tag.

Write the tag once in Home Assistant **Settings → Tags**, or let the companion app
register it on the first scan. Then select the tag in the **NFC/RFID tag** field
of the task form, or type the tag ID.

![The task form's NFC/RFID tag picker and the require-scan toggle](../../images/44-panel-task-tag-form.png)

![A task row wearing the NFC chip, and a scan-required task with its Done button blocked](../../images/44b-panel-task-nfc-chip.png)

A scan completion fires the `home_keeper_task_completed` event with
`origin: home_keeper_tag_scan`. Automations can pass the same origin to
`home_keeper.complete_task` to complete a scan-locked task. See
[docs/EVENTS.md](../../EVENTS.md).
