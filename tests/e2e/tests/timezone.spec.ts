import { expect, test } from '@playwright/test';
import { callService, createTask, deleteTask, listTasks, openPanel, openTaskTab } from './helpers';

/**
 * X04-7: the panel reads and writes times in Home Assistant's zone, not in the
 * browser zone.
 *
 * The container runs on America/New_York (tests/integration/ha_config). The browser
 * here runs on Asia/Tokyo, 13 hours ahead, so a time read in the wrong zone shows a
 * different hour and, for these values, a different date.
 */
test.use({ timezoneId: 'Asia/Tokyo' });

// 09:30 in New York is 23:30 the same day in Tokyo.
const ANCHOR = '2026-11-02T09:30:00-05:00';
// 21:15 on Sep 15 in New York is 10:15 on Sep 16 in Tokyo.
const DONE_AT = '2026-09-15T21:15:00-04:00';

let taskId: string | undefined;

test.afterEach(async () => {
  await deleteTask(taskId);
  taskId = undefined;
});

test('the edit form and the history show and keep times in the HA zone', async ({ page }) => {
  taskId = await createTask({
    name: 'E2E timezone probe',
    recurrence_type: 'fixed',
    freq: 'MONTHLY',
    interval: 1,
    anchor: ANCHOR,
  });
  await callService('home_keeper', 'complete_task', { task_id: taskId, completed_at: DONE_AT });
  const before = (await listTasks()).find((t) => t.id === taskId)!;

  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
  await expect(panel.locator('.hk-detail-actions').first()).toBeVisible({ timeout: 30_000 });

  // The history row shows the completion on its New York date, not the Tokyo one.
  await openTaskTab(panel, 'history');
  const row = panel.locator('.hk-hist-list li').first();
  await expect(row).toContainText('Sep 15, 2026');
  await expect(row).not.toContainText('Sep 16');

  // The edit form shows the anchor on the New York wall clock...
  await panel.locator('.d-edit').click();
  const anchor = panel.locator('#hk-task-form ha-selector-datetime').first();
  await expect(anchor).toBeVisible();
  await expect
    .poll(() => anchor.evaluate((el: Element & { value?: string }) => el.value))
    .toBe('2026-11-02 09:30:00');

  // ...and a save with no change stores the same instant, not one moved by 13 hours.
  await panel.locator('#f-save').click();
  await expect(panel.locator('#hk-task-form')).toHaveCount(0, { timeout: 15_000 });
  const after = (await listTasks()).find((t) => t.id === taskId)!;
  expect(Date.parse(after.anchor)).toBe(Date.parse(ANCHOR));
  expect(after.next_due).toBe(before.next_due);
});
