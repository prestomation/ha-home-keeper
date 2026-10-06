import { test, expect, type Page } from '@playwright/test';
import { callService, createTask, deleteTask, listTasks, trackPanelErrors } from './helpers';

/**
 * Fixed schedules as RRULEs (#391) and moving one date (#390), through the real panel.
 *
 * The rule text is the stored value; Repeats, Every and the day buttons are views of
 * it. These drive the views and read the rule back, then move a date through the
 * snooze dialog the Upcoming block opens, and through Home Assistant's own calendar
 * update command, which is the contract "Only this event" rests on.
 */

const CALENDAR = 'calendar.home_keeper_upcoming_tasks';

/** The next Tuesday at 07:00 UTC, at least 2 days out, so no date is in the past. */
function nextTuesday(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + 2);
  while (d.getUTCDay() !== 2) d.setUTCDate(d.getUTCDate() + 1);
  d.setUTCHours(7, 0, 0, 0);
  return d.toISOString();
}

async function gotoPanel(page: Page, path: string) {
  await page.goto(`/home-keeper${path}`, { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  return panel;
}

async function storedTask(id: string): Promise<Record<string, any>> {
  const task = (await listTasks()).find((t) => t.id === id);
  if (!task) throw new Error(`task ${id} is gone`);
  return task;
}

test.describe('Home Keeper panel — fixed schedules', { tag: '@responsive' }, () => {
  let taskId: string | undefined;

  test.beforeEach(async () => {
    taskId = await createTask({
      name: `Take trash out ${Date.now()}`,
      rrule: 'FREQ=WEEKLY;BYDAY=TU,FR',
      anchor: nextTuesday(),
    });
  });

  test.afterEach(async () => {
    await deleteTask(taskId);
    taskId = undefined;
  });

  test('the day buttons read and write the rule', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await gotoPanel(page, `/tasks/${taskId}`);
    await panel.locator('.d-edit').click();
    const days = panel.locator('#hk-rule-days');
    await expect(days).toBeVisible();
    await expect(days.locator('.hk-day-btn[aria-pressed="true"]')).toHaveCount(2);
    await expect(days.locator('.hk-day-btn[data-day="TU"]')).toHaveAttribute('aria-pressed', 'true');
    await expect(days.locator('.hk-day-btn[data-day="FR"]')).toHaveAttribute('aria-pressed', 'true');

    // The preview names the next 4 dates, from the backend's own engine.
    await expect(panel.locator('#hk-form-next')).toContainText(/Tue|Fri/, { timeout: 10_000 });

    await days.locator('.hk-day-btn[data-day="WE"]').click();
    await expect(days.locator('.hk-day-btn[data-day="WE"]')).toHaveAttribute('aria-pressed', 'true');
    await expect(panel.locator('#hk-form-summary-value')).toHaveText(
      'Every week on Tuesday, Wednesday, and Friday',
    );

    await panel.locator('#f-save').click();
    await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });
    expect((await storedTask(taskId!)).rrule).toBe('FREQ=WEEKLY;INTERVAL=1;BYDAY=TU,WE,FR');
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a custom rule greys the buttons out until it is reset', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await gotoPanel(page, `/tasks/${taskId}`);
    await panel.locator('.d-edit').click();
    const ruleForm = panel.locator('#hk-task-form-rule');
    await ruleForm.locator('ha-expansion-panel').click();
    const box = ruleForm.locator('ha-selector-text input');
    await expect(box).toHaveValue('FREQ=WEEKLY;BYDAY=TU,FR');

    await box.fill('FREQ=MONTHLY;BYDAY=1TU');
    // Typing keeps focus: the views repaint in place rather than re-rendering.
    await expect(box).toBeFocused();
    const days = panel.locator('#hk-rule-days');
    await expect(days.locator('.hk-day-btn').first()).toBeDisabled();
    await expect(panel.locator('#hk-rule-reset')).toBeVisible();
    await expect(panel.locator('#hk-form-summary-value')).toHaveText(
      'Custom rule: FREQ=MONTHLY;BYDAY=1TU',
    );
    await expect(panel.locator('#hk-form-next')).toContainText('Tue', { timeout: 10_000 });

    // A rule the backend refuses says why, in the preview line.
    await box.fill('FREQ=MONTHLY;COUNT=2');
    await expect(panel.locator('#hk-form-next')).toContainText('COUNT', { timeout: 10_000 });

    await box.fill('FREQ=MONTHLY;BYDAY=1TU');
    await panel.locator('#hk-rule-reset').click();
    await expect(box).toHaveValue('FREQ=MONTHLY;INTERVAL=1');
    // A monthly rule needs no days, so the row goes away.
    await expect(days).toBeHidden();
    await panel.locator('#f-cancel').click();
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('Move on the Upcoming block moves one date, and Undo puts it back', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await gotoPanel(page, `/tasks/${taskId}`);
    const upcoming = panel.locator('#hk-upcoming');
    await expect(upcoming.locator('.hk-up-row')).toHaveCount(6, { timeout: 10_000 });
    const third = upcoming.locator('.hk-up-row').nth(2);
    const start = await third.locator('.hk-up-move').getAttribute('data-start');

    await third.locator('.hk-up-move').click();
    const dialog = panel.locator('ha-dialog[open]');
    await expect(dialog.locator('#hk-snooze-mode-later')).toHaveAttribute('aria-pressed', 'true');
    await expect(dialog.locator('.hk-later-row.picked')).toHaveCount(1);
    await expect(dialog.locator('.hk-move-hint')).toContainText('moves to');
    await dialog.locator('ha-button[slot="primaryAction"]').click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });

    await expect(upcoming.locator('.hk-moved-badge')).toHaveCount(1, { timeout: 10_000 });
    const moves = (await storedTask(taskId!)).moved_occurrences;
    expect(moves).toHaveLength(1);
    expect(new Date(moves[0].from).getTime()).toBe(new Date(start!).getTime());
    expect(new Date(moves[0].to).getTime() - new Date(start!).getTime()).toBe(86_400_000);

    await upcoming.locator('.hk-up-undo').click();
    await expect(upcoming.locator('.hk-moved-badge')).toHaveCount(0, { timeout: 10_000 });
    expect((await storedTask(taskId!)).moved_occurrences).toEqual([]);
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('the calendar shows a moved date, and "only this event" moves one', async ({ page }) => {
    const panel = await gotoPanel(page, `/tasks/${taskId}`);
    await expect(panel.locator('#hk-upcoming .hk-up-row')).toHaveCount(6, { timeout: 10_000 });
    const anchor = new Date(nextTuesday());
    const friday = new Date(anchor.getTime() + 3 * 86_400_000);
    const saturday = new Date(friday.getTime() + 86_400_000);

    // Through Home Assistant's own calendar command, as its event dialog sends it.
    const result = await page.evaluate(
      async ({ entity, uid, from, to }) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const hass = (document.querySelector('home-assistant') as any)?.hass;
        const start = new Date(from);
        const end = new Date(start.getTime() + 3_600_000);
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const events: any[] = await hass.callApi(
          'GET',
          `calendars/${entity}?start=${start.toISOString()}&end=${end.toISOString()}`,
        );
        const event = events.find((e) => e.uid === uid);
        if (!event) return { error: 'no event', events };
        await hass.callWS({
          type: 'calendar/event/update',
          entity_id: entity,
          uid,
          recurrence_id: event.recurrence_id,
          event: {
            summary: event.summary,
            dtstart: to,
            dtend: new Date(new Date(to).getTime() + 3_600_000).toISOString(),
          },
        });
        const later: any[] = await hass.callApi(
          'GET',
          `calendars/${entity}?start=${start.toISOString()}&end=${new Date(
            start.getTime() + 3 * 86_400_000,
          ).toISOString()}`,
        );
        return {
          rrule: event.rrule,
          after: later.filter((e) => e.uid === uid).map((e) => e.start.dateTime ?? e.start),
        };
      },
      {
        entity: CALENDAR,
        uid: taskId!,
        from: friday.toISOString(),
        to: saturday.toISOString(),
      },
    );
    expect(result).not.toHaveProperty('error');
    expect(result.rrule).toContain('BYDAY=TU,FR');
    expect(result.after.map((d: string) => new Date(d).getTime())).toContain(saturday.getTime());
    expect(result.after.map((d: string) => new Date(d).getTime())).not.toContain(friday.getTime());
    const moves = (await storedTask(taskId!)).moved_occurrences;
    expect(moves).toHaveLength(1);
  });

  test('the calendar refuses a change to the whole series', async ({ page }) => {
    await gotoPanel(page, `/tasks/${taskId}`);
    const error = await page.evaluate(
      async ({ entity, uid, to }) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const hass = (document.querySelector('home-assistant') as any)?.hass;
        try {
          await hass.callWS({
            type: 'calendar/event/update',
            entity_id: entity,
            uid,
            event: {
              summary: 'Renamed',
              dtstart: to,
              dtend: new Date(new Date(to).getTime() + 3_600_000).toISOString(),
            },
          });
          return null;
        } catch (err) {
          return String((err as { message?: string })?.message ?? err);
        }
      },
      { entity: CALENDAR, uid: taskId!, to: nextTuesday() },
    );
    // The translated message when Home Assistant has the exception strings loaded,
    // else its key: either way it names the panel as the place for this edit.
    expect(error).toMatch(/Home Keeper panel|calendar_edit_in_panel/);
    expect((await storedTask(taskId!)).moved_occurrences).toEqual([]);
  });

  test('the move service moves a date and fires an event', async () => {
    const before = (await storedTask(taskId!)).next_due;
    const anchor = new Date(nextTuesday());
    const friday = new Date(anchor.getTime() + 3 * 86_400_000);
    await callService('home_keeper', 'move_occurrence', {
      task_id: taskId,
      occurrence: friday.toISOString(),
      to: new Date(friday.getTime() + 86_400_000).toISOString(),
    });
    const task = await storedTask(taskId!);
    expect(task.moved_occurrences).toHaveLength(1);
    // Friday is not the date on the board, so next_due did not move.
    expect(task.next_due).toBe(before);
  });
});
