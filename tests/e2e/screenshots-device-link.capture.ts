/**
 * One-off screenshot capture + behavioural check for the "link the panel to the
 * virtual device" change — not part of the e2e suite (filename isn't *.spec.ts). Run:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-device-link.capture.ts \
 *     --config=screenshots-device-link.config.ts
 *
 * Covers two things the user asked for:
 *  1. The "Virtual device" chip on the Appliances list + appliance detail is now a
 *     clickable link to the appliance's HA device page (it was a dead chip before).
 *  2. The device chip on a *task* row (showing the appliance name) already links to
 *     the device page — asserted here so we know it works, not just believe it.
 */
import { test, expect, Locator } from '@playwright/test';
import { openPanel } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

/** Click a chip and assert HA navigated to a device page. Returns to the panel. */
async function expectChipOpensDevicePage(page: import('@playwright/test').Page, chip: Locator): Promise<void> {
  await expect(chip).toBeVisible();
  await chip.click();
  await page.waitForURL(/\/config\/devices\/device\//, { timeout: 10_000 });
  expect(page.url()).toContain('/config/devices/device/');
}

test('capture + verify panel→device links', async ({ page }) => {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.waitForTimeout(1000);

  // 1. Appliances list — the virtual "Garage water heater" row now carries a clickable
  // "Virtual device" chip (open-in-new icon) that links to its HA device page.
  await panel.locator('#tab-appliances').click();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/device-link-appliance-list.png`, fullPage: true });

  // 2. Appliance detail header — same clickable chip next to the title.
  await panel.locator('.detail-open[data-detail-id="asset_water_heater"]').click();
  await expect(panel.locator('.hk-detail-title')).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/device-link-appliance-detail.png`, fullPage: true });

  // Verify the detail chip actually opens the device page.
  await expectChipOpensDevicePage(page, panel.locator('.hk-detail-title ~ .hk-chips .hk-device-chip').first());

  // 3. Task list — a task on the virtual appliance shows the appliance/device-name
  // chip; assert it ALSO opens the device page (the user's second ask — verifying it
  // already works rather than assuming).
  await openPanel(page);
  await expect(panel.locator('#add-btn')).toBeVisible();
  await page.waitForTimeout(500);
  // task_anode is a wear-part task whose device_id is reconciled to the live water
  // heater device (unlike the demo task_water_filter, which pins a stale seed id).
  const taskChip = panel
    .locator('.hk-card[data-id="task_anode"] .hk-device-chip')
    .first();
  await taskChip.scrollIntoViewIfNeeded();
  await expectChipOpensDevicePage(page, taskChip);
});
