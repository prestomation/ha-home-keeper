/**
 * One-off screenshot capture for the Home Keeper triggers (#415).
 * Not part of the e2e suite (the filename does not match *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-triggers.config.ts
 *
 * It shoots Home Assistant's Add trigger dialog at desktop and phone width:
 *  - By target, on the garage water heater (an appliance device);
 *  - By type, with Home Keeper selected;
 *  - the search for "overdue";
 *  - the automation with the Task became overdue trigger on that device;
 *  - the Home Keeper service device with the global Events entity.
 */
import { test, expect, type Page } from '@playwright/test';
import {
  openAddTrigger,
  searchTriggers,
  showDeviceTriggers,
  showHomeKeeperByType,
  triggerRow,
} from './automation-triggers';
import { DESKTOP, PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

/** The registry device id of an entity, read through the frontend connection. */
async function deviceIdOf(page: Page, entityId: string): Promise<string> {
  return page.evaluate(async (id) => {
    const ha = document.querySelector('home-assistant') as unknown as {
      hass?: { connection?: unknown; callWS: <T>(m: Record<string, unknown>) => Promise<T> };
    };
    for (let i = 0; i < 60 && !ha?.hass?.connection; i++) {
      await new Promise((r) => setTimeout(r, 500));
    }
    const entries = await ha.hass!.callWS<Array<{ entity_id: string; device_id: string }>>({
      type: 'config/entity_registry/list',
    });
    const entry = entries.find((e) => e.entity_id === id);
    if (!entry) throw new Error(`no registry entry for ${id}`);
    return entry.device_id;
  }, entityId);
}

/** Open the service device page and bring the Events entity row into view. */
async function serviceDevice(page: Page, deviceId: string): Promise<void> {
  await page.goto(`/config/devices/device/${deviceId}`, { waitUntil: 'domcontentloaded' });
  const devicePanel = page.locator('ha-config-device-page');
  const row = devicePanel.getByText('Events', { exact: true }).first();
  await expect(row).toBeVisible({ timeout: 30000 });
  await expect
    .poll(() => page.evaluate(() => document.getElementById('ha-launch-screen') === null), {
      timeout: 30000,
    })
    .toBe(true);
  await page.waitForTimeout(1500);
  await row.scrollIntoViewIfNeeded();
  await page.waitForTimeout(800);
}

/** Bring the Home Keeper group of a By target list into view. */
async function scrollToHomeKeeper(page: Page): Promise<void> {
  const dialog = page.locator('add-automation-element-dialog');
  await dialog.getByText('Home Keeper', { exact: true }).first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(800);
}

test('capture the Home Keeper triggers in the automation editor', async ({ page }) => {
  test.setTimeout(300000);
  await page.setViewportSize(DESKTOP);
  await page.goto('/home-keeper', { waitUntil: 'domcontentloaded' });
  await page
    .getByText('Home Assistant has started!')
    .waitFor({ state: 'hidden', timeout: 20000 })
    .catch(() => undefined);
  const service = await deviceIdOf(page, 'event.home_keeper_events');

  let dialog = await openAddTrigger(page);
  await showDeviceTriggers(dialog, 'Garage water heater');
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/79-automation-trigger-by-target.png` });

  dialog = await openAddTrigger(page);
  await showHomeKeeperByType(dialog);
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/79b-automation-trigger-by-type.png` });

  dialog = await openAddTrigger(page);
  await searchTriggers(dialog, 'overdue');
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/79c-automation-trigger-search.png` });

  dialog = await openAddTrigger(page);
  await showDeviceTriggers(dialog, 'Garage water heater');
  await triggerRow(dialog, 'Task became overdue').click();
  await expect(page.getByText('Triggers when a task becomes overdue.').first()).toBeVisible();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/79d-automation-trigger-added.png` });

  await serviceDevice(page, service);
  await page.screenshot({ path: `${OUT}/79e-device-service-events.png`, fullPage: true });

  // Phone. The dialog fills the screen, and By target opens 1 step at a time.
  await page.setViewportSize(PHONE);
  try {
    dialog = await openAddTrigger(page);
    await showDeviceTriggers(dialog, 'Garage water heater');
    await scrollToHomeKeeper(page);
    await page.screenshot({ path: `${OUT}/79-automation-mobile-trigger-by-target.png` });

    dialog = await openAddTrigger(page);
    await showHomeKeeperByType(dialog);
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/79b-automation-mobile-trigger-by-type.png` });

    dialog = await openAddTrigger(page);
    await searchTriggers(dialog, 'overdue');
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/79c-automation-mobile-trigger-search.png` });

    dialog = await openAddTrigger(page);
    await showDeviceTriggers(dialog, 'Garage water heater');
    await triggerRow(dialog, 'Task became overdue').click();
    await expect(page.getByText('Triggers when a task becomes overdue.').first()).toBeVisible();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: `${OUT}/79d-automation-mobile-trigger-added.png` });

    await serviceDevice(page, service);
    await page.screenshot({ path: `${OUT}/79e-device-mobile-service-events.png` });
  } finally {
    await page.setViewportSize(DESKTOP);
  }
});
