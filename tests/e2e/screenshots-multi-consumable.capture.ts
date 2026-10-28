/**
 * Screenshot capture for several consumables on 1 task (issue #493) — not part of the
 * e2e suite (the filename is not *.spec.ts). Run from tests/e2e/:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-multi-consumable.config.ts
 *
 * Covers the 3 changed surfaces, desktop and phone:
 *  34b / 34c. The task form: Linked consumables with 2 filters, and 1 amount field
 *             for each filter.
 *  34d / 34f. The task page: 1 stock chip and 1 Linked consumables line for each part.
 *  34e / 34g. The task list row: 1 short "2 parts · Low stock" chip.
 *
 * Its own file, as the counted-wear capture is, so the shots do not inherit the state
 * of the long walk in `screenshots.capture.ts`, and the appliance it makes is gone
 * before any other capture runs.
 */
import { expect, Locator, Page, test } from '@playwright/test';
import { centre, shotWithDrawer } from './shots';
import { PHONE } from './viewports';
import { openListFilters, openPanel } from './tests/helpers';
import { WaterIds, removeWaterSystem, seedWaterSystem } from './water-system';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

async function openTask(page: Page, ids: WaterIds): Promise<Locator> {
  await page.goto(`/home-keeper/tasks/${ids.taskId}`, { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  await expect(panel.locator('.hk-asset-head .hk-part-chip')).toHaveCount(2);
  return panel;
}

async function shootForm(page: Page, panel: Locator, path: string): Promise<void> {
  await panel.locator('.d-edit').click();
  const form = panel.locator('#hk-task-form');
  await expect(form).toBeVisible();
  const amount = panel.locator('#hk-task-form-placement ha-selector-number').nth(1);
  await expect(amount).toBeVisible();
  await centre(amount);
  await page.mouse.move(0, 0);
  await page.waitForTimeout(500);
  await shotWithDrawer(page, path);
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });
}

async function shootRow(page: Page, path: string, ids: WaterIds): Promise<void> {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  // Dismiss the first-run banner if it is up, so the row is in frame.
  const intro = panel.locator('ha-button.hk-intro-dismiss');
  if ((await intro.count()) > 0) {
    await intro.click();
    await expect(panel.locator('.hk-intro')).toHaveCount(0);
  }
  await openListFilters(panel);
  await panel.locator('.hk-search-input').fill('filter');
  const row = panel.locator(`ha-card.hk-card[data-id="${ids.taskId}"]`);
  await expect(row.locator('ha-assist-chip.hk-part-chip')).toHaveAttribute(
    'label',
    '2 parts · Low stock',
  );
  await row.scrollIntoViewIfNeeded();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(500);
  await page.screenshot({ path });
  await panel.locator('.hk-search-input').fill('');
}

test('capture several consumables on 1 task', async ({ page }) => {
  test.setTimeout(240_000);
  let ids: WaterIds | null = null;
  try {
    ids = await seedWaterSystem();

    // ── desktop ──
    let panel = await openTask(page, ids);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/34d-panel-multi-consumable-detail.png`, fullPage: true });
    await shootForm(page, panel, `${OUT}/34b-panel-multi-consumable-form.png`);
    await shootRow(page, `${OUT}/34e-panel-multi-consumable-list.png`, ids);

    // ── phone ──
    await page.setViewportSize(PHONE);
    panel = await openTask(page, ids);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/34f-panel-mobile-multi-consumable-detail.png` });
    await shootForm(page, panel, `${OUT}/34c-panel-mobile-multi-consumable-form.png`);
    await shootRow(page, `${OUT}/34g-panel-mobile-multi-consumable-list.png`, ids);
  } finally {
    await removeWaterSystem(ids);
  }
});
