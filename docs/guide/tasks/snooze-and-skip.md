# Snooze, skip and due today

Home Keeper supports snooze, skip and due today for a task that is not completed
on schedule, or that a user wants to do sooner than its schedule says. Snooze
moves the due date later and leaves the recurrence unchanged. Skip advances the
task to its next occurrence and records that the occurrence was passed over. Due
today moves the due date to today, also without changing the recurrence.

Open a task and select **Snooze**, **Skip** or **Due today** next to **Done**.

- **Snooze** takes a duration. Select 1 of 4 durations, or set a date. The dialog
  shows the new due date before it is applied. The recurrence does not change, so
  a task snoozed from the 29th to the 6th is due again on the 29th of the next
  month.
- **Skip** advances the schedule by 1 occurrence. A floating task starts a new
  interval from the current date. A fixed task moves to its next scheduled date.
  For a task measured in miles or hours, the next interval starts from the current
  reading of the meter.
- **Due today** moves the due date to today, for a task a user wants to do now
  rather than on its usual date. It takes effect immediately, with no dialog, and
  it never records a completion. A task that is already due or overdue does not
  show it, because there is no due date to bring nearer.

<img src="docs/images/51-panel-skip-snooze-menu.png" alt="A task's Done button with its caret open, showing Snooze, Skip and Due today with a line each explaining what they do" width="820">

<img src="docs/images/52-panel-snooze-dialog.png" alt="The snooze dialog: a duration dropdown and a line stating the date the due date moves to" width="820">

Home Keeper records a skip in the task history, in a list separate from the
completions. A skip is never counted as a completion, so the completion tally and
the average interval do not include it. Each entry stores a note and the person
who made the decision.

<img src="docs/images/53-panel-skip-in-history.png" alt="A task's history with a skipped occurrence marked as skipped, sitting between two completions" width="820">

Snooze, skip and due today are also services, so an automation moves a task
without the panel:

- `home_keeper.snooze_task` accepts `hours`. An exact date and time in `until`
  works too.
- `home_keeper.skip_task` records a skip.
- `home_keeper.set_due_today` moves the due date to today, whatever the periodic
  schedule says. Like a snooze, it is not a completion.

3 more services edit the recorded skips:

- `home_keeper.update_skip` changes the note or the person on an entry.
- `home_keeper.move_skip` changes the date of an entry.
- `home_keeper.delete_skip` removes an entry and undoes the skip.

The dashboard card supports all three, on the row of each task, and opens the same
dialogs as the panel. Due today acts immediately, so it has no dialog to open.

<img src="docs/images/card-skip-snooze-row.png" alt="A dashboard card whose rows show snooze, skip and due today buttons ahead of the accent Done button" width="330">

To turn snooze, skip or due today off, open **Settings** and then
**Snooze, skip and due today**. All three start on. Home Keeper removes Snooze or
Skip that is off from the panel, the card, and the notification buttons. Due today
has no notification button to begin with, because a notified task is already due
or overdue. Turning it off removes it only from the panel and the card. The
`home_keeper.snooze_task`, `home_keeper.skip_task` and
`home_keeper.set_due_today` services continue to work, so an existing
automation is not affected.

<img src="docs/images/45c-panel-settings-skipsnooze.png" alt="The Snooze, skip and due today settings card, with a switch for each" width="500">
