/**
 * Phone-width capture of the panel surfaces, for reviewing the responsive layout.
 * Not part of the e2e suite (filename is not *.spec.ts). Run with:
 *   SHOT_DIR=/tmp/mobile npx playwright test --config=mobile.config.ts
 */
import { test, expect } from '@playwright/test';
import { openPanel } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-mobile';

test('capture the panel at phone width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openPanel(page);
  const panel = page.locator('home-keeper-panel');
  await expect(panel.locator('#hk-list')).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/m-tasks.png` });

  // Settings opens on its section index — six rows, each naming a section and what
  // it is set to. Nothing is off the edge of the screen.
  await panel.locator('#mtab-settings').click();
  await expect(panel.locator('.hk-index-row').first()).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/m-settings-index.png` });

  // Tapping a row opens that section alone, with a back arrow.
  await panel.locator('.hk-index-row[data-section="problem"]').click();
  await expect(panel.locator('#hk-settings')).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/m-settings-section.png` });

  await panel.locator('#settings-back').click();
  await expect(panel.locator('.hk-index-row').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/m-settings-back.png` });

  await panel.locator('#mtab-appliances').click();
  await expect(panel.locator('#hk-list')).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/m-appliances.png` });

  // The same URL on a desktop is the whole page with the rail beside it — the split
  // is CSS, so widening the window is all it takes.
  await page.setViewportSize({ width: 1280, height: 800 });
  await panel.locator('#tab-settings').click();
  await expect(panel.locator('.hk-settings-rail')).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/d-settings.png` });
});
