/**
 * One-off screenshot capture for PR documentation — not part of the e2e suite
 * (filename does not match *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots.capture.ts \
 *     --config=screenshots.config.ts
 *
 * The panel is built from Home Assistant components, so forms are `ha-form`s:
 * text fields live inside `ha-selector-text` (fill the inner input) and dropdowns
 * are `ha-select` built on `ha-dropdown` (open, then click the role="menuitem").
 */
import { test, expect, Locator } from '@playwright/test';
import { openPanel, openDashboard } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

/** Fill the input of the nth ha-form text selector within a scope. */
async function fillText(scope: Locator, nth: number, value: string): Promise<void> {
  await scope.locator('ha-selector-text').nth(nth).locator('input, textarea').fill(value);
}

/** Pick an option label from an HA ha-select (ha-dropdown) dropdown. */
async function chooseHaSelect(select: Locator, optionLabel: string | RegExp): Promise<void> {
  await select.click();
  await select.page().getByRole('menuitem', { name: optionLabel }).first().click();
}

test('capture Home Keeper panel + usage screenshots', async ({ page }) => {
  // 1. The admin sidebar panel — task list with floating + fixed + overdue tasks.
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.waitForTimeout(1200); // let the HA sidebar/layout settle (avoid ghosting)
  await page.screenshot({ path: `${OUT}/1-panel-task-list.png`, fullPage: true });

  // 2. Create form — floating recurrence + device picker.
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-form')).toBeVisible();
  await fillText(panel.locator('#hk-task-form'), 0, 'Replace dishwasher filter');
  await page.screenshot({ path: `${OUT}/2-panel-create-floating.png`, fullPage: true });

  // 3. Create form switched to a fixed (anchored) schedule.
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').first(), /Fixed/);
  await expect(panel.locator('#hk-task-form ha-selector-datetime')).toBeVisible();
  await page.screenshot({ path: `${OUT}/3-panel-create-fixed.png`, fullPage: true });

  // 5. Appliances tab — the asset list with the seeded virtual device.
  await panel.locator('#tab-appliances').click();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/5-panel-appliances-list.png`, fullPage: true });

  // 6. Appliance create form — virtual device, metadata, parts and relationships.
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-asset-form')).toBeVisible();
  const assetForm = panel.locator('#hk-asset-form');
  await fillText(assetForm, 0, 'Garage water heater'); // name
  await fillText(assetForm, 1, 'Rheem'); // manufacturer
  // Icon picker is a nested combo-box; best-effort (not essential to the shot).
  try {
    await assetForm
      .locator('ha-selector-icon input')
      .first()
      .fill('mdi:water-boiler', { timeout: 4000 });
  } catch {
    /* leave icon empty */
  }
  // Add a wear part to show the parts editor + replacement interval.
  await panel.locator('#a-add-part').click();
  const part = panel.locator('.hk-part').first();
  await fillText(part, 0, 'Anode rod'); // part name
  await fillText(part, 1, 'AR-1'); // part number
  await chooseHaSelect(part.locator('ha-select').first(), 'wear item');
  // After switching to wear, the replace-interval number appears (cost is #0).
  await panel.locator('.hk-part').first().locator('ha-selector-number').nth(1).locator('input').fill('12');
  await page.screenshot({ path: `${OUT}/6-panel-appliance-create.png`, fullPage: true });

  // 4. The usage surfaces — native to-do list + calendar on a dashboard.
  await openDashboard(page);
  await page.waitForTimeout(1500); // let cards settle
  await page.screenshot({ path: `${OUT}/4-usage-todo-and-calendar.png`, fullPage: true });
});
