import { test, expect, type Locator, type Page } from '@playwright/test';
import { callService, createTask, deleteTask, listTasks, trackPanelErrors } from './helpers';

/** Deep-link straight to a task page and wait for its actions to render. */
async function gotoTask(page: Page, taskId: string): Promise<Locator> {
  await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-detail-actions .hk-split-caret')).toBeVisible({
    timeout: 45_000,
  });
  return panel;
}

/** Open the snooze dialog from the caret beside Done, and return its preset select. */
async function openSnooze(panel: Locator): Promise<Locator> {
  await panel.locator('.hk-detail-actions .hk-split-caret').click();
  await panel.locator('.hk-detail-actions .hk-defer-snooze').click();
  await expect(panel.locator('ha-dialog[open] .hk-snooze-hint')).toBeVisible({ timeout: 15_000 });
  return panel.locator('ha-dialog[open] ha-selector-select').first().locator('ha-select');
}

const selectValue = (select: Locator): Promise<string> =>
  select.evaluate((el) => String((el as HTMLInputElement).value ?? ''));

/**
 * A task's own snooze length (#367).
 *
 * `defer.test.js` pins which preset `snoozeStateFor` picks. This proves the length
 * gets there: stored through the service, read back by the panel, and used by the
 * real dialog, where a field the websocket does not return would not show in jsdom.
 */
test.describe('Home Keeper panel — snooze length per task', () => {
  let taskId: string | undefined;

  test.afterEach(async () => {
    await deleteTask(taskId);
    taskId = undefined;
  });

  test('the snooze dialog opens on the task length', async ({ page }) => {
    const errors = trackPanelErrors(page);
    taskId = await createTask({ name: 'E2E snooze 4h', interval: 1, unit: 'days', snooze_hours: 4 });
    const stored = (await listTasks()).find((t) => t.id === taskId);
    expect(stored?.snooze_hours).toBe(4);

    const panel = await gotoTask(page, taskId);
    const select = await openSnooze(panel);
    await expect.poll(() => selectValue(select)).toBe('4h');

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a cleared length opens on the usual preset again', async ({ page }) => {
    taskId = await createTask({ name: 'E2E snooze cleared', interval: 1, unit: 'days', snooze_hours: 1 });
    await callService('home_keeper', 'update_task', { task_id: taskId, snooze_hours: null });
    const stored = (await listTasks()).find((t) => t.id === taskId);
    expect(stored?.snooze_hours).toBeNull();

    const panel = await gotoTask(page, taskId);
    const select = await openSnooze(panel);
    await expect.poll(() => selectValue(select)).toBe('1w');
  });

  test('a length no preset has opens on a custom date', async ({ page }) => {
    taskId = await createTask({ name: 'E2E snooze 3h', interval: 1, unit: 'days', snooze_hours: 3 });

    const panel = await gotoTask(page, taskId);
    const select = await openSnooze(panel);
    await expect.poll(() => selectValue(select)).toBe('custom');
    await expect(panel.locator('ha-dialog[open] ha-selector-datetime')).toBeVisible();
  });
});
