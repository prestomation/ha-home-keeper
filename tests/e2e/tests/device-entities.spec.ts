import { test, expect } from '@playwright/test';
import {
  callService,
  createTask,
  deleteTask,
  listStates,
  openPanel,
  openSettingsSection,
  trackPanelErrors,
} from './helpers';

/**
 * The switch for the task entities on device pages (#496). Off disables the
 * per-task entities in the entity registry, so Home Assistant removes their states.
 */
test.describe('Home Keeper panel — task entities on device pages', { tag: '@responsive' }, () => {
  const created: string[] = [];

  test.afterEach(async () => {
    // Put the default back, so no other spec sees disabled entities.
    await callService('home_keeper', 'set_options', { task_device_entities: true });
    while (created.length) await deleteTask(created.pop());
  });

  test('the General card switch disables the task entities', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const deviceId = await page.evaluate(() => {
      const ha = document.querySelector('home-assistant') as unknown as {
        hass: { entities: Record<string, { device_id?: string }> };
      };
      return ha.hass.entities['sensor.e2e_battery_device_battery']?.device_id ?? '';
    });
    expect(deviceId, 'the battery stub sensor must have a device').toBeTruthy();
    const name = 'E2E device entities switch';
    created.push(
      await createTask({ name, interval: 30, unit: 'days', device_id: deviceId }),
    );
    const taskStates = async () =>
      (await listStates()).filter((s) =>
        String(s.attributes?.friendly_name ?? '').includes(name),
      ).length;
    await expect.poll(taskStates, { timeout: 30_000 }).toBeGreaterThan(0);

    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await openSettingsSection(panel, 'general');
    const card = panel.locator('#hk-settings-general');
    await expect(card).toContainText('Enable task entities on device pages');
    const readOption = () =>
      page.evaluate(async () => {
        const ha = document.querySelector('home-assistant') as unknown as {
          hass: { callWS: <T>(m: Record<string, unknown>) => Promise<T> };
        };
        const res = await ha.hass.callWS<Record<string, unknown>>({
          type: 'home_keeper/get_options',
        });
        const opts = (res.options ?? res) as Record<string, unknown>;
        return opts.task_device_entities;
      });
    expect(await readOption()).toBe(true);

    // The card draws again when the options load, which can drop a click on the old
    // switch. Click again only while the stored value is still on, and give each save
    // time to land, so a retry cannot turn the switch back on.
    await expect(async () => {
      if ((await readOption()) === true) await card.locator('ha-switch').click();
      expect(await readOption()).toBe(false);
    }).toPass({ intervals: [3_000], timeout: 30_000 });
    // The entities are disabled in the registry, so their states go.
    await expect.poll(taskStates, { timeout: 30_000 }).toBe(0);
    expect(await readOption()).toBe(false);
    // The panel retries a fetch that lands while the entry is busy.
    const unexpected = errors.filter((e) => !e.includes('not_loaded'));
    expect(unexpected, `panel errors:\n${unexpected.join('\n')}`).toHaveLength(0);
  });
});
