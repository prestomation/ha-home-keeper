/**
 * One-off screenshot capture for the options artifact of issue #496 (opt out of the
 * per-task device entities). Not part of the e2e suite. Run with:
 *   SHOT_DIR=/tmp/shots npx playwright test --config=screenshots-issue496.config.ts
 *
 * It photographs, at desktop and phone width, the screens that each option changes:
 *  - the appliance device page with its per-task entities (the problem),
 *  - the General card of the Settings tab (where a global switch would go),
 *  - the task form with its device field (where a per-task switch would go),
 *  - the Home Assistant entity settings dialog (today's workaround).
 */
import { test, expect, type Page } from '@playwright/test';
import { openPanel, openSettingsSection } from './tests/helpers';
import { DESKTOP, PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

async function ws<T>(page: Page, msg: Record<string, unknown>): Promise<T> {
  return page.evaluate(async (m) => {
    const ha = document.querySelector('home-assistant') as unknown as {
      hass: { callWS: <R>(x: Record<string, unknown>) => Promise<R> };
    };
    return ha.hass.callWS(m);
  }, msg) as Promise<T>;
}

test('capture issue 496 screens', async ({ page }) => {
  test.setTimeout(240_000);
  await page.setViewportSize(DESKTOP);
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-name').first()).toBeVisible();

  const { assets } = await ws<{ assets: { name: string; device_id?: string | null }[] }>(page, {
    type: 'home_keeper/get_assets',
  });
  const deviceId = assets.find((a) => a.name === 'Garage water heater')?.device_id ?? '';
  expect(deviceId).toBeTruthy();
  for (const name of ['Flush sediment tank', 'Inspect burner assembly', 'Check relief valve']) {
    await ws(page, {
      type: 'home_keeper/add_task',
      task: { name, recurrence_type: 'floating', interval: 6, unit: 'months', device_id: deviceId },
    });
  }
  await page.waitForTimeout(6000);
  const { tasks } = await ws<{ tasks: { id: string; name: string; device_id?: string | null }[] }>(
    page,
    { type: 'home_keeper/get_tasks' },
  );
  const taskId = tasks.find((t) => t.name === 'Flush sediment tank')?.id ?? '';

  // 1. The device page with the per-task entities.
  await page.goto(`/config/devices/device/${deviceId}`, { waitUntil: 'domcontentloaded' });
  await expect(page.getByText('Flush sediment tank: Mark done').first()).toBeVisible({
    timeout: 30000,
  });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${OUT}/496a-device-page-tasks.png`, fullPage: true });
  await page.setViewportSize(PHONE);
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${OUT}/496a-device-mobile-page-tasks.png`, fullPage: true });

  // 3. The General card of the Settings tab.
  await page.setViewportSize(DESKTOP);
  await openPanel(page);
  await openSettingsSection(panel, 'general');
  await page.mouse.move(0, 0);
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/496b-panel-settings-general.png` });
  await page.setViewportSize(PHONE);
  await openPanel(page);
  await openSettingsSection(panel, 'general');
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/496b-panel-mobile-settings-general.png`, fullPage: true });

  // 4. The task form, scrolled to its device field.
  for (const [size, name] of [
    [DESKTOP, '496c-panel-task-form-device.png'],
    [PHONE, '496c-panel-mobile-task-form-device.png'],
  ] as const) {
    await page.setViewportSize(size);
    await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
    const actions = panel.locator('.hk-detail-actions').first();
    await expect(actions.locator('.d-edit')).toBeVisible({ timeout: 45_000 });
    await actions.locator('.d-edit').click();
    const form = panel.locator('#hk-form');
    await expect(form).toBeVisible({ timeout: 20_000 });
    const device = form.getByText('Placement', { exact: true }).first();
    await device.scrollIntoViewIfNeeded();
    await page.mouse.wheel(0, 150);
    await page.mouse.move(0, 0);
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${OUT}/${name}` });
  }

  // 2. Options C and D, and today's workaround: the per-task entities disabled in the
  // entity registry. The device page folds them away.
  await page.setViewportSize(DESKTOP);
  const disabled = await page.evaluate(async (dev) => {
    const ha = document.querySelector('home-assistant') as unknown as {
      hass: {
        callWS: <R>(x: Record<string, unknown>) => Promise<R>;
        entities: Record<string, { device_id?: string; platform?: string }>;
      };
    };
    const reg = await ha.hass.callWS<
      { entity_id: string; unique_id: string; device_id: string | null; platform: string }[]
    >({ type: 'config/entity_registry/list' });
    const ids = reg
      .filter(
        (e) =>
          e.platform === 'home_keeper' &&
          e.device_id === dev &&
          /_(done|next_due|overdue)$/.test(e.unique_id),
      )
      .map((e) => e.entity_id);
    for (const entity_id of ids) {
      await ha.hass.callWS({
        type: 'config/entity_registry/update',
        entity_id,
        disabled_by: 'user',
      });
    }
    return ids.length;
  }, deviceId);
  console.log('disabled per-task entities:', disabled);
  await page.goto(`/config/devices/device/${deviceId}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(4000);
  await page.screenshot({ path: `${OUT}/496d-device-page-disabled.png`, fullPage: true });
  await page.setViewportSize(PHONE);
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${OUT}/496d-device-mobile-page-disabled.png`, fullPage: true });
});
