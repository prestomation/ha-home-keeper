/**
 * One-off screenshot capture for the Parts view of the Appliances tab (#547). Not part
 * of the e2e suite (the file name is not *.spec.ts). Run:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-parts.capture.ts \
 *     --config=screenshots-parts.config.ts
 *
 * Shots, desktop then phone (the phone name has a -mobile- segment):
 *  547  / 547e. The Parts view, grouped by appliance. The Anode rod and the AAA
 *               batteries sit at or below their reorder point, so their rows carry the
 *               low marker and the Low stock chip. The Batteries appliance belongs to
 *               an integration, and its stepper works.
 *  547b / 547f. The Low stock chip on: the 2 low parts only.
 *  547c / 547g. The same list for a user who is not an admin: no stepper.
 *  547d / 547h. The Archived scope on: the parts of an archived appliance.
 *  547i / 547j. The Appliances list with the new Appliances | Parts switch.
 *
 * Its own file, like the other captures of a single feature, so that a shot can be
 * taken again without the 60 steps of `screenshots.capture.ts`.
 */
import { expect, test, Locator, Page } from '@playwright/test';
import { resolve } from 'node:path';
import { callService } from './tests/helpers';
import { DESKTOP, PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
const VIEWER_STATE = resolve(__dirname, '.auth/viewer-state.json');

const panelOf = (page: Page): Locator => page.locator('home-keeper-panel').first();

async function openParts(page: Page): Promise<Locator> {
  await page.goto('/home-keeper/appliances/parts', { waitUntil: 'domcontentloaded' });
  const panel = panelOf(page);
  await expect(panel.locator('.hk-parts-view')).toBeVisible({ timeout: 45_000 });
  await expect(panel.locator('.hk-pt-row').first()).toBeVisible();
  return panel;
}

async function shot(page: Page, name: string): Promise<void> {
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/${name}.png` });
}

/** The Parts view in the default scope and with the Low stock chip on. */
async function mainShots(page: Page, names: [string, string]): Promise<void> {
  const panel = await openParts(page);
  await shot(page, names[0]);
  await panel.locator('.hk-pt-filters [data-seg-val="low"]').click();
  await expect(panel.locator('.hk-pt-row')).toHaveCount(2);
  await shot(page, names[1]);
  await panel.locator('.hk-pt-filters [data-seg-val="all"]').click();
}

async function archivedShot(page: Page, name: string): Promise<void> {
  await callService('home_keeper', 'add_asset', {
    name: 'Old dishwasher',
    parts: [
      { name: 'Rinse aid', type: 'consumable', stock: 1, reorder_at: 2, vendor: 'Costco' },
      { name: 'Spray arm', type: 'wear', stock: 1, reorder_at: 0 },
    ],
  });
  const { assets } = await callService('home_keeper', 'list_assets', {}, true);
  const asset = assets.find((a: any) => a.name === 'Old dishwasher');
  try {
    await callService('home_keeper', 'archive_asset', { asset_id: asset.id });
    const panel = await openParts(page);
    await panel.locator('.hk-seg[data-seg="assetFilter"] [data-seg-val="archived"]').click();
    await expect(panel.locator('.hk-pt-row')).toHaveCount(2);
    await shot(page, name);
    await panel.locator('.hk-seg[data-seg="assetFilter"] [data-seg-val="active"]').click();
  } finally {
    await callService('home_keeper', 'delete_asset', { asset_id: asset.id });
  }
}

async function switchShot(page: Page, name: string): Promise<void> {
  // The URL, not the tab: the tab opens in the mode that the browser used last.
  await page.goto('/home-keeper/appliances', { waitUntil: 'domcontentloaded' });
  const panel = panelOf(page);
  await expect(panel.locator('.hk-mode')).toBeVisible({ timeout: 45_000 });
  await expect(panel.locator('.hk-card[data-id]').first()).toBeVisible();
  await shot(page, name);
}

test('capture the Parts view', async ({ page, browser, baseURL }) => {
  test.setTimeout(240_000);
  const viewer = async (size: { width: number; height: number }, name: string) => {
    const ctx = await browser.newContext({
      baseURL,
      storageState: VIEWER_STATE,
      viewport: size,
    });
    const vp = await ctx.newPage();
    try {
      const panel = await openParts(vp);
      await expect(panel.locator('.hk-view-only-banner')).toBeVisible();
      await expect(panel.locator('.hk-stock')).toHaveCount(0);
      await shot(vp, name);
    } finally {
      await ctx.close();
    }
  };

  await page.setViewportSize(DESKTOP);
  await mainShots(page, ['547-panel-parts', '547b-panel-parts-low']);
  await viewer(DESKTOP, '547c-panel-parts-viewer');
  await archivedShot(page, '547d-panel-parts-archived');
  await switchShot(page, '547i-panel-appliances-switch');

  await page.setViewportSize(PHONE);
  await mainShots(page, ['547e-panel-mobile-parts', '547f-panel-mobile-parts-low']);
  await viewer(PHONE, '547g-panel-mobile-parts-viewer');
  await archivedShot(page, '547h-panel-mobile-parts-archived');
  await switchShot(page, '547j-panel-mobile-appliances-switch');
});
