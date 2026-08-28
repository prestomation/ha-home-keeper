/**
 * Phone-width capture of the panel surfaces, for reviewing the responsive layout.
 * Not part of the e2e suite (filename is not *.spec.ts). Run with:
 *   SHOT_DIR=/tmp/mobile npx playwright test mobile.capture.ts --config=screenshots.config.ts
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

  await panel.locator('#mtab-settings').click();
  await expect(panel.locator('#hk-settings')).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/m-settings.png` });

  await panel.locator('#mtab-appliances').click();
  await expect(panel.locator('#hk-list')).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/m-appliances.png` });
});
