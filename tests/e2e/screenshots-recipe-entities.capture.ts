/**
 * One-off screenshot capture for the recipe entity-name fix (#377). Not part of the
 * e2e suite (the filename does not match *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-recipe-entities.config.ts
 *
 * It adds 2 recipes that match the one device-backed battery sensor in the
 * container, then photographs that device's page at desktop and phone width:
 *  - "Low battery" clears itself when the battery recovers, so its task has no
 *    Mark done button.
 *  - "Replace battery" does not clear itself, so its task keeps the button.
 * Each entity name starts with the recipe name, not the rendered task name.
 *
 * Run it against a fresh container (`docker compose down -v`, then
 * `git checkout -- tests/integration/ha_config/`). It does not delete the 2
 * recipes, so a second run on the same container adds 2 more tasks to the device.
 */
import { test, expect } from '@playwright/test';
import { openPanel } from './tests/helpers';
import { DESKTOP, PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
const SENSOR = 'sensor.e2e_battery_device_battery';

test('capture recipe entity names on a device page', async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-name').first()).toBeVisible();

  // The panel can load before the integration has registered its services.
  await page.waitForFunction(() => {
    const ha = document.querySelector('home-assistant') as unknown as {
      hass?: { services?: Record<string, Record<string, unknown>> };
    };
    return Boolean(ha?.hass?.services?.home_keeper?.add_declarative_companion);
  }, undefined, { timeout: 60000 });

  const selection = { domain: 'sensor', target_integration: 'home_keeper_battery_notes' };
  const addRecipe = (recipe: Record<string, unknown>) =>
    page.evaluate(async (data) => {
      const ha = document.querySelector('home-assistant') as unknown as {
        hass: { callWS: <T>(m: Record<string, unknown>) => Promise<T> };
      };
      // The recipe services only answer with a response, so call them the way the
      // frontend does with return_response. A recipe that makes a device task
      // reloads the entry, which removes the services for a moment, so a
      // "not found" is retried.
      for (let attempt = 0; ; attempt++) {
        try {
          return await ha.hass.callWS({
            type: 'call_service',
            domain: 'home_keeper',
            service: 'add_declarative_companion',
            service_data: data,
            return_response: true,
          });
        } catch (err) {
          const code = (err as { code?: string }).code;
          if (code !== 'not_found' || attempt >= 30) {
            throw new Error(`add_declarative_companion failed: ${JSON.stringify(err)}`);
          }
          await new Promise((r) => setTimeout(r, 1000));
        }
      }
    }, recipe);
  // Wait until the overdue sensor of *label* reads Problem, so the next recipe's
  // entry reload does not catch its task before it arms.
  const waitArmed = (label: string) =>
    page.waitForFunction(
      (name) => {
        const ha = document.querySelector('home-assistant') as unknown as {
          hass: { states: Record<string, { state: string; attributes: Record<string, unknown> }> };
        };
        return Object.values(ha.hass.states).some(
          (s) =>
            String(s.attributes.friendly_name ?? '').endsWith(`${name}: Overdue`) &&
            s.state === 'on',
        );
      },
      label,
      { timeout: 60000 },
    );

  await addRecipe({
    name: 'Low battery',
    selection,
    trigger: { mode: 'threshold', comparison: '<=', value: 50, clear_on_recover: true },
    task_template: { name_template: 'Battery: {{ device_name }}' },
  });
  await waitArmed('Low battery');
  await addRecipe({
    name: 'Replace battery',
    selection,
    trigger: { mode: 'threshold', comparison: '<=', value: 50 },
    task_template: { name_template: 'Replace the {{ device_name }} battery' },
  });
  await waitArmed('Replace battery');

  const deviceId = await page.evaluate((sensor) => {
    const ha = document.querySelector('home-assistant') as unknown as {
      hass: { entities: Record<string, { device_id?: string }> };
    };
    return ha.hass.entities[sensor]?.device_id ?? null;
  }, SENSOR);
  expect(deviceId, 'the battery sensor must have a device').toBeTruthy();


  await page.goto(`/config/devices/device/${deviceId}`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByText('Low battery: Next due').first()).toBeVisible({ timeout: 30000 });
  await expect(page.getByText('Replace battery: Mark done').first()).toBeVisible();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${OUT}/21r-device-recipe-entity-names.png`, fullPage: true });

  await page.setViewportSize(PHONE);
  await page.waitForTimeout(2500);
  await page.screenshot({
    path: `${OUT}/21r-device-mobile-recipe-entity-names.png`,
    fullPage: true,
  });
});
