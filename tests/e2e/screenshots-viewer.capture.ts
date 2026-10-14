/**
 * Screenshot capture for the view-only panel (#444). Not part of the e2e suite (the
 * file name is not *.spec.ts). The config logs in as `viewer`, a user who is not an
 * admin (global-setup.ts makes it). Run:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-viewer.capture.ts \
 *     --config=screenshots-viewer.config.ts
 *
 * Shots, desktop then phone:
 *  80.  The appliance list with the View only note and no Add appliance.
 *  80b. An appliance page with the View only chip, on the Documents tab.
 *  80c. The Settings tab with the admin-only card.
 *  80d. The Tasks tab, which works as it does for an admin.
 *  80e-80h. The phone versions of 80 to 80d.
 */
import { test, expect, Locator, Page } from '@playwright/test';
import { gotoTab, openAppliance, openPanel } from './tests/helpers';
import { ASSET } from './fixture-ids';
import { DESKTOP, PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

async function shots(page: Page, names: [string, string, string, string]): Promise<void> {
  await openPanel(page);
  const panel: Locator = page.locator('home-keeper-panel').first();

  await gotoTab(panel, 'appliances');
  await expect(panel.locator('.hk-view-only-banner')).toBeVisible();
  await expect(panel.locator('#add-btn')).toBeHidden();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/${names[0]}.png` });

  await openAppliance(page, ASSET.waterHeater, 'documents');
  await expect(panel.locator('ha-assist-chip.hk-view-only')).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/${names[1]}.png` });

  await gotoTab(panel, 'settings');
  await expect(panel.locator('.hk-admin-only')).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/${names[2]}.png` });

  await gotoTab(panel, 'tasks');
  await expect(panel.locator('#hk-list')).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/${names[3]}.png` });
}

test('capture the view-only panel', async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await shots(page, [
    '80-panel-viewer-appliances',
    '80b-panel-viewer-appliance-detail',
    '80c-panel-viewer-settings',
    '80d-panel-viewer-tasks',
  ]);

  await page.setViewportSize(PHONE);
  await shots(page, [
    '80e-panel-mobile-viewer-appliances',
    '80f-panel-mobile-viewer-appliance-detail',
    '80g-panel-mobile-viewer-settings',
    '80h-panel-mobile-viewer-tasks',
  ]);
});
