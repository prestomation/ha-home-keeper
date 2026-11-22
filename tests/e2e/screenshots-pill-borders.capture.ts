import { test, expect } from '@playwright/test';
import { DESKTOP, PHONE } from './viewports';

/**
 * Capture the pill groups of the Appliances page: the controls row on a desktop, and
 * the Appliances | Parts switch on a phone. The ends of each pill must keep their whole
 * outline. Set SHOT_SUFFIX to name a run, for example `before` or `after`. Run via:
 *   SHOT_DIR=../../docs/images SHOT_SUFFIX=after \
 *     npx playwright test --config=screenshots-pill-borders.config.ts
 */
const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
const SUFFIX = process.env.SHOT_SUFFIX || 'after';

test.use({ deviceScaleFactor: 2 });

test('pill groups keep their outline', async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await page.goto('/home-keeper/appliances', { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-seg').first()).toBeVisible();
  await page.waitForTimeout(800);
  // The whole row of controls: from the first pill group to the last one.
  const segs = panel.locator('.hk-seg');
  const first = (await segs.first().boundingBox())!;
  const last = (await segs.last().boundingBox())!;
  const top = Math.min(first.y, last.y) - 12;
  const bottom = Math.max(first.y + first.height, last.y + last.height) + 12;
  await page.screenshot({
    path: `${OUT}/554-panel-pill-borders-${SUFFIX}.png`,
    clip: { x: first.x - 12, y: top, width: last.x + last.width - first.x + 24, height: bottom - top },
  });

  await page.setViewportSize(PHONE);
  await page.waitForTimeout(500);
  await expect(panel.locator('.hk-mode .hk-seg')).toBeVisible();
  await panel.locator('.hk-mode').screenshot({ path: `${OUT}/554b-panel-mobile-pill-borders-${SUFFIX}.png` });
});
