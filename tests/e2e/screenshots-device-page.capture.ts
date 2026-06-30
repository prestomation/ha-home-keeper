/**
 * One-off screenshot capture for the "device page enrichment" PR — not part of the
 * e2e suite (filename does not match *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-device-page.capture.ts \
 *     --config=screenshots-device-page.config.ts
 *
 * It documents what a Home Keeper *virtual appliance*'s HA device page now shows:
 *  - the device-info block with make / model / **serial number** (a first-class field),
 *  - per-part **spare-stock** ``number`` controls and **low-stock** problem sensors,
 *  - alongside the existing per-task next-due / overdue / mark-done entities and the
 *    tracked-date sensors.
 *
 * The seeded "Garage water heater" virtual appliance owns a real HA device and has
 * stock-tracked parts (an anode rod that is low: 1 on hand, reorder at 2), so the page
 * populates on its own — we just read its device id from the panel's authenticated
 * websocket connection and open the device page.
 */
import { test, expect } from '@playwright/test';
import { openPanel } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

test('capture appliance device page enrichment', async ({ page }) => {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.waitForTimeout(1200); // let the sidebar/layout settle

  // Read the seeded virtual water-heater appliance's device id via the panel's hass.
  const deviceId = await page.evaluate(async () => {
    const ha = document.querySelector('home-assistant') as unknown as {
      hass: { callWS: <T>(m: Record<string, unknown>) => Promise<T> };
    };
    const { assets } = await ha.hass.callWS<{
      assets: { name: string; device_id?: string | null }[];
    }>({ type: 'home_keeper/get_assets' });
    const wh = assets.find((a) => a.name === 'Garage water heater');
    return (wh?.device_id as string) || '';
  });
  expect(deviceId, 'expected the seeded water heater to have a device id').toBeTruthy();

  // Open the appliance's HA device page and let its entity cards render.
  await page.goto(`/config/devices/device/${deviceId}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3500);

  // 1. The whole device page — device-info block (make/model/serial + "Visit" deep
  // link into the panel) plus every Home Keeper entity grouped under the appliance:
  // per-task next-due / overdue / mark-done, tracked-date sensors, and the new per-part
  // spare-stock numbers + low-stock problem sensors.
  await page.screenshot({ path: `${OUT}/device-page-appliance.png`, fullPage: true });

  // 2. Close-up of the device-info card (best-effort): make / model / serial number.
  const infoCard = page.locator('ha-device-info-card').first();
  if (await infoCard.count()) {
    await infoCard.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await infoCard.screenshot({ path: `${OUT}/device-page-info-block.png` });
  }
});
