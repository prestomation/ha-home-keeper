# Snooze and skip

Home Keeper supports snooze and skip for an occurrence that a user does not
complete on schedule. Snooze moves the due date and leaves the recurrence
unchanged. Skip advances the task to its next occurrence and records that the
occurrence was passed over. This is useful if a task is not done on time, or if
an occurrence is not needed at all.

Open a task and select **Snooze** or **Skip** next to **Done**.

- **Snooze** takes a duration. Select 1 of 4 durations, or set a date. The dialog
  shows the new due date before it is applied. The recurrence does not change, so
  a task snoozed from the 29th to the 6th is due again on the 29th of the next
  month.
- **Skip** advances the schedule by 1 occurrence. A floating task starts a new
  interval from the current date. A fixed task moves to its next scheduled date.
  For a task measured in miles or hours, the next interval starts from the current
  reading of the meter.

<img src="docs/images/51-panel-skip-snooze-menu.png" alt="A task's Done button with its caret open, showing Snooze and Skip with a line each explaining what they do" width="820">

<img src="docs/images/52-panel-snooze-dialog.png" alt="The snooze dialog: a duration dropdown and a line stating the date the due date moves to" width="820">

Home Keeper records a skip in the task history, in a list separate from the
completions. A skip is never counted as a completion, so the completion tally and
the average interval do not include it. Each entry stores a note and the person
who made the decision.

<img src="docs/images/53-panel-skip-in-history.png" alt="A task's history with a skipped occurrence marked as skipped, sitting between two completions" width="820">

Snooze and skip are also services, so an automation can defer a task without the
panel. `home_keeper.snooze_task` accepts `hours`, or an exact date and time in
`until`. `home_keeper.skip_task` records a skip. 3 more services edit the
recorded skips:

- `home_keeper.update_skip` changes the note or the person on an entry.
- `home_keeper.move_skip` changes the date of an entry.
- `home_keeper.delete_skip` removes an entry and undoes the skip.

The dashboard card supports both, on the row of each task, and opens the same
dialogs as the panel.

<img src="docs/images/card-skip-snooze-row.png" alt="A dashboard card whose rows show a snooze and a skip button ahead of the accent Done button" width="330">

To turn snooze or skip off, open **Settings** and then **Skip & snooze**. Both
start on. Home Keeper removes the one that is off from the panel, from the card,
and from the notification buttons. The `home_keeper.snooze_task` and
`home_keeper.skip_task` services continue to work, so an existing automation is
not affected.
