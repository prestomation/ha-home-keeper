/**
 * One-off screenshot capture for the 1 overlay state of the panel. Not part of the e2e
 * suite (the filename is not *.spec.ts). Run:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-overlays.capture.ts \
 *     --config=screenshots-overlays.config.ts
 *
 * On the Tasks list: the deferral menu, the action sheet of a tile and the spend sheet.
 * Desktop and phone.
 */
import { expect, test, type Locator, type Page } from '@playwright/test';
import { PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

async function openTasks(page: Page): Promise<Locator> {
  await page.goto('/home-keeper/tasks', { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  await expect(panel.locator('#add-btn')).toBeVisible({ timeout: 45_000 });
  await page.waitForTimeout(500);
  return panel;
}

/** Close whatever is open, from the top, and go back to the list of rows. */
async function reset(page: Page, panel: Locator): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(150);
  }
  await panel.evaluate((p: any) => p._setTaskLayout('rows'));
  await page.waitForTimeout(300);
}

async function shots(page: Page, panel: Locator, tag: string): Promise<void> {
  // The deferral menu of the first row.
  await panel.locator('.hk-split-caret').first().click();
  await expect(panel.locator('.hk-defer-menu:not([hidden])').first()).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/overlay-${tag}defer-menu.png` });
  await reset(page, panel);

  // The action sheet of a tile.
  await panel.evaluate((p: any) => p._setTaskLayout('tiles'));
  await panel.locator('.hk-press').first().click();
  await expect(panel.locator('#hk-dialog-host .hk-sheet-row').first()).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/overlay-${tag}action-sheet.png` });
  await reset(page, panel);

  // The spend sheet.
  await panel.evaluate((p: any) => p._openSpendSheet());
  await expect(panel.locator('.hk-spend-sheet')).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/overlay-${tag}spend-sheet.png` });
  await reset(page, panel);

  await reset(page, panel);
}

test('capture the overlays of the Tasks list', async ({ page }) => {
  test.setTimeout(180_000);
  const panel = await openTasks(page);
  await shots(page, panel, '');

  await page.setViewportSize(PHONE);
  await page.waitForTimeout(500);
  await shots(page, panel, 'mobile-');
});
