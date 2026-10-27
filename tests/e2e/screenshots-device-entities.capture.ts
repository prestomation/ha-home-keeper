/**
 * One-off screenshot capture for the switch of the task entities on device pages
 * (#496). Not part of the e2e suite (the filename does not match *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-device-entities.config.ts
 *
 * It adds 3 tasks to the seeded "Garage water heater" appliance, then photographs at
 * desktop and phone width:
 *  - the device page with the task entities enabled (the default),
 *  - the General card of Settings with the switch off,
 *  - the device page with the switch off: the task entities fold into "+N disabled
 *    entities".
 * It puts the switch back on and deletes the 3 tasks at the end.
 */
import { test, expect, type Page } from '@playwright/test';
import { callService, deleteTask, openPanel, openSettingsSection } from './tests/helpers';
import { DESKTOP, PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
const NAMES = ['Flush sediment tank', 'Inspect burner assembly', 'Check relief valve'];

async function ws<T>(page: Page, msg: Record<string, unknown>): Promise<T> {
  return page.evaluate(async (m) => {
    const ha = document.querySelector('home-assistant') as unknown as {
      hass: { callWS: <R>(x: Record<string, unknown>) => Promise<R> };
    };
    return ha.hass.callWS(m);
  }, msg) as Promise<T>;
}

test('capture the task entities switch', async ({ page }) => {
  test.setTimeout(240_000);
  const created: string[] = [];
  try {
    await page.setViewportSize(DESKTOP);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('.hk-name').first()).toBeVisible();

    const { assets } = await ws<{ assets: { name: string; device_id?: string | null }[] }>(
      page,
      { type: 'home_keeper/get_assets' },
    );
    const deviceId = assets.find((a) => a.name === 'Garage water heater')?.device_id ?? '';
    expect(deviceId, 'the seeded water heater must have a device').toBeTruthy();
    for (const name of NAMES) {
      const resp = await callService(
        'home_keeper',
        'add_task',
        { name, recurrence_type: 'floating', interval: 6, unit: 'months', device_id: deviceId },
        true,
      );
      created.push(resp.task_id as string);
    }

    // 1. The device page with the task entities enabled.
    const devicePage = `/config/devices/device/${deviceId}`;
    await page.goto(devicePage, { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('Flush sediment tank: Mark done').first()).toBeVisible({
      timeout: 30_000,
    });
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/96a-device-entities-on.png`, fullPage: true });

    // 2. The switch off in the General card. The save disables the entities.
    await openPanel(page);
    await openSettingsSection(panel, 'general');
    const card = panel.locator('#hk-settings-general');
    await card.locator('ha-switch').click();
    await expect(card.locator('.hk-save-status.saved')).toBeVisible({ timeout: 30_000 });
    await page.mouse.move(0, 0);
    await page.waitForTimeout(800);
    await card.screenshot({ path: `${OUT}/96b-panel-settings-entities-off.png` });

    // 3. The device page with the switch off.
    await page.goto(devicePage, { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(/disabled entit/).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('Flush sediment tank: Mark done')).toHaveCount(0);
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/96c-device-entities-off.png`, fullPage: true });

    // The phone shots.
    await page.setViewportSize(PHONE);
    await page.waitForTimeout(2000);
    await page.screenshot({ path: `${OUT}/96d-device-mobile-entities-off.png` });
    await openPanel(page);
    await openSettingsSection(panel, 'general');
    await expect(panel.locator('#hk-settings-general')).toBeVisible();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${OUT}/96e-panel-mobile-settings-entities-off.png` });
  } finally {
    await callService('home_keeper', 'set_options', { task_device_entities: true });
    for (const id of created) await deleteTask(id);
  }
});
