# Services

Home Keeper exposes every data action as a Home Assistant service. This is useful
for automations, scripts, and voice control. The
[API reference](https://prestomation.github.io/ha-home-keeper/developer/api#actions)
lists all of them with their fields.

- **Tasks**: `home_keeper.add_task`, `update_task`, `delete_task`, and
  `complete_task` cover the basic actions. `complete_task` takes an optional
  `completed_at` to back-date it, plus `note`, `cost`, `photo`, and `who`.
  `update_completion` changes a recorded completion's metadata. `move_completion`
  changes a recorded completion's timestamp, identified by its current `old_ts`.
  `trigger_task` arms a condition-driven task. `snooze_task` defers the due date
  by `hours` without completing the task. `skip_task` advances the task to its
  next occurrence without completing it. `set_task_consumable` links a task to an
  appliance consumable, so a completion draws down its stock. Omit the ids to
  unlink. `list_tasks` returns a response.
<!-- vale ai-tells.OverusedVocabulary = NO -->
- **Notifications**: `home_keeper.notify` sends an actionable notification for the
  tasks that are due, from a saved notification or profile. It returns
  `{matched, sent}`. See
  [Notifications](../views/notifications.md).
<!-- vale ai-tells.OverusedVocabulary = YES -->
- **Appliances**: `home_keeper.add_asset`, `update_asset`, and `delete_asset`
  manage an appliance. `adjust_part_stock` adjusts a part's stock.
  `add_asset_document`, `update_asset_document`, and `remove_asset_document`
  attach, rename, or detach a manual, a warranty, or a receipt. A file uploads
  from the panel. `list_assets` and `export_inventory` return a response.
- **Import and export**: `home_keeper.export_data` returns every task and appliance
  as one document. `home_keeper.import_data` reads one back. Both return a response.
  See [Import and export](./import-export.md).

#### Use a name instead of an id

Every `task_id`, `asset_id`, `part_id`, and `document_id` field takes the object's
**name** or its id.

```yaml
action: home_keeper.complete_task
data:
  task_id: Replace furnace filter
```

The panel shows the id on every task and appliance page and beside each part and
document, with a copy button. Use the id when 2 objects share a name. An ambiguous
name returns an error that lists the matching ids.

A task can also be completed through the `todo.home_keeper_tasks` list with
`todo.update_item`, which addresses the item by name:

```yaml
action: todo.update_item
target:
  entity_id: todo.home_keeper_tasks
data:
  item: Replace furnace filter
  status: completed
```
