import { test, expect } from '@playwright/test';
import { callService, openAppliance, openPanel } from './tests/helpers';
import { ASSET } from './fixture-ids';
import { PHONE } from './viewports';

/**
 * Capture the Appliances list at the window size of #551 (1015 x 904) and on a phone.
 * The list is long, and its pane must fit the window at the end of the page. The cards
 * must show their left border (#554). Run via:
 *   SHOT_DIR=../../docs/images npx playwright test --config=screenshots-scroll-corners.config.ts
 */
const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
const WINDOW = { width: 1015, height: 904 };
const EXTRA = Array.from({ length: 14 }, (_, i) => `Spare appliance ${i + 1}`);

test('appliance list fits the window and cards keep their border', async ({ page }) => {
  for (const name of EXTRA) await callService('home_keeper', 'add_asset', { name });
  try {
    await page.setViewportSize(WINDOW);
    await openPanel(page);
    const panel = await openAppliance(page, ASSET.waterHeater);
    await expect(panel.locator('.hk-master')).toBeVisible();
    // Scroll the pane to its end, then the page to its end.
    await panel.locator('.hk-master').evaluate((el) => (el.scrollTop = el.scrollHeight));
    await page.mouse.move(700, 500);
    await page.mouse.wheel(0, 3000);
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/551-panel-appliance-list.png` });
    // The left edge of the list, enlarged, for the card borders.
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(300);
    const box = (await panel.locator('.hk-master').boundingBox())!;
    await page.screenshot({
      path: `${OUT}/554-panel-card-border.png`,
      clip: { x: box.x - 12, y: box.y, width: 120, height: 300 },
    });

    await page.setViewportSize(PHONE);
    await openPanel(page);
    await page.goto('/home-keeper/appliances', { waitUntil: 'domcontentloaded' });
    await expect(panel.locator('ha-card.hk-card').first()).toBeVisible();
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/551b-panel-mobile-appliance-list.png` });
    await page.screenshot({
      path: `${OUT}/554b-panel-mobile-card-border.png`,
      clip: { x: 0, y: 260, width: 140, height: 300 },
    });
  } finally {
    const res = (await callService('home_keeper', 'list_assets', {}, true)) as any;
    for (const a of res?.assets ?? []) {
      if (EXTRA.includes(a.name)) await callService('home_keeper', 'delete_asset', { asset_id: a.id });
    }
  }
});
