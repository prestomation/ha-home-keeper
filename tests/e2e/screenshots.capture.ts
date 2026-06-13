/**
 * One-off screenshot capture for PR documentation — not part of the e2e suite
 * (filename does not match *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots.capture.ts \
 *     --config=screenshots.config.ts
 */
import { test, expect } from '@playwright/test';
import { openPanel, openDashboard } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

test('capture Home Keeper panel + usage screenshots', async ({ page }) => {
  // 1. The admin sidebar panel — task list with floating + fixed + overdue tasks.
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/1-panel-task-list.png`, fullPage: true });

  // 2. Create form — floating recurrence + device picker.
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-form')).toBeVisible();
  await panel.locator('#f-name').fill('Replace dishwasher filter');
  await page.screenshot({ path: `${OUT}/2-panel-create-floating.png`, fullPage: true });

  // 3. Create form switched to a fixed (anchored) schedule.
  await panel.locator('#f-type').selectOption('fixed');
  await expect(panel.locator('#anchor-wrap')).toBeVisible();
  await page.screenshot({ path: `${OUT}/3-panel-create-fixed.png`, fullPage: true });

  // 5. Appliances tab — the asset list with the seeded virtual device.
  await panel.locator('#tab-appliances').click();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/5-panel-appliances-list.png`, fullPage: true });

  // 6. Appliance create form — virtual device + asset metadata fields.
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-asset-form')).toBeVisible();
  await panel.locator('#a-name').fill('Garage water heater');
  await panel.locator('#a-manufacturer').fill('Rheem');
  await panel.locator('#a-warranty').fill('2032-05-01');
  await page.screenshot({ path: `${OUT}/6-panel-appliance-create.png`, fullPage: true });

  // 4. The usage surfaces — native to-do list + calendar on a dashboard.
  await openDashboard(page);
  await page.waitForTimeout(1500); // let cards settle
  await page.screenshot({ path: `${OUT}/4-usage-todo-and-calendar.png`, fullPage: true });
});
