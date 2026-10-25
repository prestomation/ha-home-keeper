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
 * The cost totals (#460): a completion with a cost shows in the spend sensors and in
 * the strip above the task list. A total opens its records, and a record opens the
 * history of its task. The Cost tracking card changes the periods.
 */
test.describe('Home Keeper panel — Cost totals', { tag: '@responsive' }, () => {
  const created: string[] = [];

  test.afterEach(async () => {
    await callService('home_keeper', 'set_options', {
      cost_windows: [30, 60],
      cost_summary_panel: true,
    });
    while (created.length) await deleteTask(created.pop());
  });

  async function spendState(uniqueEnd: string): Promise<Record<string, any> | undefined> {
    const states = await listStates();
    return states.find(
      (s) =>
        s.entity_id.startsWith('sensor.home_keeper_') &&
        s.attributes?.device_class === 'monetary' &&
        s.entity_id.endsWith(uniqueEnd),
    );
  }

  test('a completion cost shows in the sensor and the strip', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const taskId = await createTask({ name: 'E2E shower valve', interval: 90, unit: 'days' });
    created.push(taskId);
    await callService('home_keeper', 'complete_task', { task_id: taskId, cost: 3.19 });

    // The 30-day sensor counts it.
    await expect
      .poll(async () => Number((await spendState('_30_days'))?.state ?? -1), { timeout: 20_000 })
      .toBeGreaterThanOrEqual(3.19);

    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const strip = panel.locator('.hk-spend');
    await expect(strip).toBeVisible();
    const total = strip.locator('[data-spend="w30"]');
    await expect(total).toHaveAttribute('aria-pressed', 'false');
    await total.click();
    await expect(strip.locator('[data-spend="w30"]')).toHaveAttribute('aria-pressed', 'true');
    const row = strip.locator('.hk-spend-row', { hasText: 'E2E shower valve' });
    await expect(row).toBeVisible();
    await expect(row.locator('.hk-spend-cost')).toContainText('3.19');

    // The record opens the history of its task.
    await row.locator('.hk-spend-task').click();
    await expect(page).toHaveURL(new RegExp(`/home-keeper/tasks/${taskId}/history`));
    expect(errors).toEqual([]);
  });

  test('the Cost tracking card changes the periods and hides the strip', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await openSettingsSection(panel, 'cost');
    const card = panel.locator('#hk-settings-cost');
    await expect(card).toBeVisible();
    await expect(card.locator('.hk-settings-value')).toContainText('30, 60');

    // The same write the card makes. The sensor of a new period appears.
    await callService('home_keeper', 'set_options', {
      cost_windows: [7, 30],
      cost_summary_panel: false,
    });
    await expect.poll(async () => Boolean(await spendState('_7_days')), { timeout: 30_000 }).toBe(true);
    await openPanel(page);
    await expect(page.locator('home-keeper-panel').first().locator('.hk-spend')).toHaveCount(0);
  });
});
