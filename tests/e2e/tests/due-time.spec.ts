import { test, expect } from '@playwright/test';
import {
  callService,
  createTask,
  deleteTask,
  listTasks,
  openPanel,
  openSettingsSection,
  trackPanelErrors,
} from './helpers';

/**
 * The set due time of floating tasks (#438): the Settings card turns it on, the
 * stored due date moves to the set time, and the task page shows only the date.
 */
test.describe('Home Keeper panel — Due time', { tag: '@responsive' }, () => {
  const created: string[] = [];

  test.afterEach(async () => {
    // Put the default back, so no other spec sees a set due time.
    await callService('home_keeper', 'set_options', { due_time_mode: 'completion' });
    while (created.length) await deleteTask(created.pop());
  });

  test('the card sets a due time, and the task page shows only the date', async ({ page }) => {
    const errors = trackPanelErrors(page);
    // Done 10 days ago at 22:42, every 30 days: due in 20 days at 22:42.
    const done = new Date(Date.now() - 10 * 86_400_000);
    done.setHours(22, 42, 0, 0);
    const taskId = await createTask({
      name: 'E2E furnace filter',
      interval: 30,
      unit: 'days',
      last_completed: done.toISOString(),
    });
    created.push(taskId);

    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await openSettingsSection(panel, 'duetime');
    const card = panel.locator('#hk-settings-duetime');
    await expect(card).toBeVisible();
    await expect(card.locator('.hk-settings-value')).toHaveText('At the time of completion');
    // The time field is shown only for a set time.
    await expect(card.locator('ha-selector-time')).toHaveCount(0);

    await card.getByText('At a set time', { exact: true }).click();
    await expect(card.locator('ha-selector-time')).toBeVisible();
    await expect(card.locator('.hk-settings-value')).toHaveText('Due at 08:00');
    await expect(card.locator('.hk-save-status.saved')).toBeVisible({ timeout: 30_000 });

    // The save reloads the entry, which moves the stored date to 08:00 in Home
    // Assistant's zone. The stored ISO text carries that zone's offset.
    await expect
      .poll(async () => {
        const task = (await listTasks()).find((t) => t.id === taskId);
        return String(task?.next_due ?? '');
      })
      .toMatch(/T08:00:00/);

    await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
    const detail = page.locator('home-keeper-panel').first();
    const due = detail.locator('.hk-detail-row', { hasText: 'Next due' }).locator('.v');
    await expect(due).toBeVisible({ timeout: 45_000 });
    // A date with no time of day: no "08:00" and no "8:00 AM".
    await expect(due).not.toHaveText(/\d:\d\d/);

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
