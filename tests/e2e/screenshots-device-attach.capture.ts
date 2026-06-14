/**
 * One-off screenshot capture for the device-attachment UI PR — not part of the
 * e2e suite (filename does not match *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-device-attach.capture.ts \
 *     --config=screenshots-device-attach.config.ts
 *
 * It demonstrates two changes:
 *  1. The sidebar panel's device chip — now an actionable link with the device's
 *     brand logo (falling back to a generic device icon when no image loads).
 *  2. Per-task device-page entities named by their task, so several tasks on one
 *     device no longer collapse into identically-named "Mark done" controls.
 *
 * To get a device that already exists in the registry, we attach the new tasks to
 * the seeded "Garage water heater" virtual appliance (it owns a real HA device).
 * Tasks are created through the panel's own authenticated websocket connection
 * (no fragile picker automation), then we open that device's HA page.
 */
import { test, expect } from '@playwright/test';
import { openPanel } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

test('capture device-attachment UI', async ({ page }) => {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.waitForTimeout(1200); // let the sidebar/layout settle

  // Seed two extra maintenance tasks on the seeded water-heater device using the
  // panel's authenticated hass connection, then read back its device id.
  const deviceId = await page.evaluate(async () => {
    const ha = document.querySelector('home-assistant') as unknown as {
      hass: {
        callWS: <T>(m: Record<string, unknown>) => Promise<T>;
        devices: Record<string, unknown>;
      };
    };
    const hass = ha.hass;
    const { tasks } = await hass.callWS<{ tasks: { device_id?: string | null }[] }>({
      type: 'home_keeper/get_tasks',
    });
    // Pick a task on a device that actually exists in the registry (the seeded
    // virtual "Garage water heater"), not the demo task pointing at a stale id.
    const attached = tasks.find((t) => t.device_id && hass.devices[t.device_id]);
    const device_id = attached?.device_id as string;
    for (const name of ['Flush sediment tank', 'Inspect burner assembly']) {
      await hass.callWS({
        type: 'home_keeper/add_task',
        task: { name, recurrence_type: 'floating', interval: 6, unit: 'months', device_id },
      });
    }
    return device_id;
  });
  expect(deviceId, 'expected a seeded device-attached task to read a device id').toBeTruthy();

  // Adding device-attached tasks reloads the entry to create their per-task
  // entities; give it a moment, then refresh the panel.
  await page.waitForTimeout(5000);
  await openPanel(page);
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.waitForTimeout(2800); // let the HA sidebar finish animating (avoid ghosting)

  // 1. Task list — multiple rows now carry the device chip (icon + device name).
  await page.screenshot({ path: `${OUT}/1-panel-device-chips.png`, fullPage: true });

  // Close-up of a single task row showing the device chip.
  const chipRow = panel.locator('.hk-card-row:has(.hk-device-chip)').first();
  await chipRow.scrollIntoViewIfNeeded();
  await chipRow.screenshot({ path: `${OUT}/2-device-chip-closeup.png` });

  // 2. The device page — each task's mark-done button / next-due sensor / overdue
  // binary sensor is now prefixed with its task name instead of colliding.
  await page.goto(`/config/devices/device/${deviceId}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${OUT}/3-device-page-entities.png`, fullPage: true });
});
