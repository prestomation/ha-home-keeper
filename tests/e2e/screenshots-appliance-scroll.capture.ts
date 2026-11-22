import { test, expect } from '@playwright/test';
import { callService, openAppliance, openPanel } from './tests/helpers';
import { ASSET } from './fixture-ids';
import { DESKTOP, PHONE } from './viewports';

/**
 * Capture the Appliances tab after a press on a row near the bottom of the list beside
 * the open appliance. The list must keep its scroll, and the open row must be in view.
 * Set SHOT_SUFFIX to name a run, for example `before` or `after`. Run via:
 *   SHOT_DIR=../../docs/images SHOT_SUFFIX=after \
 *     npx playwright test --config=screenshots-appliance-scroll.config.ts
 */
const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
const SUFFIX = process.env.SHOT_SUFFIX || 'after';
const EXTRA = Array.from({ length: 14 }, (_, i) => `Scroll appliance ${String(i + 1).padStart(2, '0')}`);

test('appliance list keeps its scroll after a press on a row', async ({ page }) => {
  for (const name of EXTRA) await callService('home_keeper', 'add_asset', { name });
  try {
    await page.setViewportSize(DESKTOP);
    await openPanel(page);
    const panel = await openAppliance(page, ASSET.waterHeater);
    const pane = panel.locator('.hk-master');
    await expect(pane).toBeVisible();
    await pane.evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });
    const last = panel.locator('.hk-master ha-card.hk-card').last();
    const name = (await last.locator('.hk-name').innerText()).trim();
    await last.locator('.detail-open').click();
    await expect(panel.locator('.hk-master ha-card.hk-selected .hk-name')).toHaveText(name);
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/586-panel-appliance-scroll-${SUFFIX}.png` });

    // A phone has no list beside the appliance, so this shot shows the page as it is.
    await page.setViewportSize(PHONE);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/586b-panel-mobile-appliance-scroll-${SUFFIX}.png` });
  } finally {
    const assets = (await callService('home_keeper', 'list_assets', {}, true)) as any;
    for (const a of assets?.assets ?? []) {
      if (EXTRA.includes(a.name)) await callService('home_keeper', 'delete_asset', { asset_id: a.id });
    }
  }
});
