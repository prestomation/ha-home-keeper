# Fixed schedules

Use a fixed schedule for a task on calendar dates, such as "every Tuesday and Friday
at 07:00" or "the first Tuesday of each month". Completing the task moves it to the
next date of the schedule, while the later dates stay on their own days and keep
their time of day when the clocks change.

Select **Repeats on a fixed schedule** on the task form to make one.

## Days of the week

Set **Frequency** to weekly, then press the days the task is due. The start date
gives the time of day and the first week. To set up trash that goes out on Tuesday
and Friday mornings:

1. Set **Every** to 1 and **Frequency** to weekly.
2. Press **Tue** and **Fri**.
3. Set **First occurrence** to the next Tuesday at 07:00.

The box under the form shows the rule in words and the next 4 dates, so you can check
the schedule before you save it.

<img src="docs/images/71-panel-fixed-weekdays.png" alt="The task form with Frequency set to weekly, the Tuesday and Friday buttons pressed, and the next 4 dates under the form" width="820">

Daily, monthly and yearly schedules need no days. A monthly task on the 29th, 30th or
31st uses the last day of a shorter month, then goes back to its own day.

## Custom rules

Open **Custom rule (RRULE)** to see the schedule as iCalendar text. The controls
above it and the text are the same schedule: press a day and the text changes, type
a rule and the controls change.

Type a rule for a schedule the controls cannot show. Some examples:

| Schedule | Rule |
| --- | --- |
| The first Tuesday of each month | `FREQ=MONTHLY;BYDAY=1TU` |
| The last Friday of each month | `FREQ=MONTHLY;BYDAY=-1FR` |
| Every 2 weeks on Monday and Thursday | `FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH` |
| The 1st and the 15th of each month | `FREQ=MONTHLY;BYMONTHDAY=1,15` |
| Each year on the first Sunday of April | `FREQ=YEARLY;BYMONTH=4;BYDAY=1SU` |

When the rule has parts other than days of the week, the form grays out the controls and
shows **Reset to simple**, which goes back to a plain rule with the same frequency.

<img src="docs/images/72-panel-fixed-custom-rule.png" alt="The task form with a custom rule for the first Tuesday of each month, the day buttons grayed out and a Reset to simple button" width="820">

A rule cannot end, so `COUNT` and `UNTIL` are not allowed. A rule that is due more
than once a day is not allowed either.

A task on the first Tuesday stays on the first Tuesday. When you snooze it or do it
early, the date after it is still the first Tuesday of the next month.

## Move one date

Sometimes one date of the schedule changes, such as when the city moves a trash day
for a holiday. You can move that one date and keep the other dates as they are.

- **On the dashboard card or in the panel**, select **Snooze**, then **A later date**.
  Pick the date, set the new date and time, and select **Move**. **Next date** is the
  usual snooze.
- **On the task page**, the **Upcoming** block lists the next dates. Select **Move**
  on a date. A moved date shows **Moved** and the date it came from. Select **Undo**
  to put it back.
- **In the Home Assistant calendar**, open the event, change the start time and
  select **Only this event**. A change to the whole series is not accepted there, so
  use the panel for it.

<img src="docs/images/73-panel-upcoming-moved.png" alt="The Upcoming block of a trash task with a Friday date moved to Saturday, marked Moved, with Undo and Move buttons" width="820">

<img src="docs/images/74-panel-snooze-later-date.png" alt="The Snooze dialog on A later date, with one date picked and a new date and time for it" width="820">

A move goes away by itself after its date has passed. Home Keeper turns
**A later date** and **Move** off with **Snooze** in **Settings**.

An automation moves a date with the `home_keeper.move_occurrence` service. Give the
date on the schedule as `occurrence` and the new date as `to`. To undo a move, set
`to` to the same time as `occurrence`.

```yaml
action: home_keeper.move_occurrence
data:
  task_id: Take trash out
  occurrence: "2026-10-09T07:00:00"
  to: "2026-10-10T07:00:00"
```

Each move fires a `home_keeper_task_occurrence_moved` event.
