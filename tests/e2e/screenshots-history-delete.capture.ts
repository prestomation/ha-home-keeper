/**
 * Focused screenshot capture for the history delete confirmation (issue #597).
 *
 * The trash can on a history row used to remove the entry on the press. It now opens
 * the panel's usual delete dialog, titled with the entry's date and time, with its
 * reading and note in the body. This seeds its own task and completion, photographs
 * the dialog at desktop and phone width, then removes the task.
 *
 * The scrim is `position: fixed` on `document.body`, so both shots are viewport
 * captures.
 *
 * Run:
 *   CHROMIUM_EXEC=$(ls /opt/pw-browsers/chromium-*\/chrome-linux/chrome | head -1) \
 *     SHOT_DIR=../../docs/images \
 *     npx playwright test --config=screenshots-history-delete.config.ts
 */
import { test, expect } from '@playwright/test';
import { callService, createTask, deleteTask } from './tests/helpers';
import { PHONE, DESKTOP } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

test('capture the history delete confirmation', async ({ page }) => {
  const taskId = await createTask({ name: 'Car oil change', interval: 180, unit: 'days' });
  try {
    await callService('home_keeper', 'complete_task', {
      task_id: taskId,
      note: 'Synthetic oil, new filter',
      cost: 64.5,
    });
    const open = async () => {
      await page.goto(`/home-keeper/tasks/${taskId}/history`, { waitUntil: 'domcontentloaded' });
      const panel = page.locator('home-keeper-panel').first();
      await expect(panel.locator('.hk-hist-list li')).toHaveCount(1, { timeout: 45_000 });
      await panel.locator('.hk-hist-del').click();
      const scrim = page.locator('.hk-confirm-scrim');
      await expect(scrim).toBeVisible();
      await expect(scrim.locator('#hk-confirm-body')).toContainText('Synthetic oil');
      await page.waitForTimeout(400);
      return scrim;
    };

    // 90. Desktop: the dialog names the entry by date and time, and shows its note.
    await page.setViewportSize(DESKTOP);
    let scrim = await open();
    await page.screenshot({ path: `${OUT}/90-panel-history-delete-confirm.png` });
    await scrim.locator('ha-button', { hasText: 'Cancel' }).click();
    await expect(scrim).toBeHidden();

    // 90b. Phone: the same dialog on a 390px screen.
    await page.setViewportSize(PHONE);
    scrim = await open();
    await page.screenshot({ path: `${OUT}/90b-panel-mobile-history-delete-confirm.png` });
    await scrim.locator('ha-button', { hasText: 'Cancel' }).click();
    await expect(scrim).toBeHidden();
  } finally {
    await deleteTask(taskId);
  }
});
