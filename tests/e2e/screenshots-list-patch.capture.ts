import { test, expect } from '@playwright/test';
import { callService, deleteTask, openPanel } from './tests/helpers';
import { PHONE } from './viewports';

/**
 * Capture the Tasks list in a home with many tasks, narrowed by a search and after a
 * task is completed on another surface. The list keeps the rows that did not change,
 * so the shots must look as they did before. Run via:
 *   SHOT_DIR=../../docs/images npx playwright test --config=screenshots-list-patch.config.ts
 */
const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
const COUNT = Number(process.env.TASK_COUNT || 120);
const BASES = ['Replace furnace filter', 'Clean dryer vent', 'Test smoke alarm', 'Descale kettle'];

test('task list search and refresh in a home with many tasks', async ({ page }) => {
  test.setTimeout(300_000);
  const tasks = Array.from({ length: COUNT }, (_, i) => ({
    name: `${BASES[i % BASES.length]} #${i + 1}`,
    interval: [1, 3, 6][i % 3],
    unit: 'months',
  }));
  const report = await callService(
    'home_keeper',
    'import_data',
    { document: { home_keeper: { format: 1 }, tasks } },
    true,
  );
  const made: string[] = report.records.map((r: { id: string }) => r.id);
  try {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator(`.hk-card[data-id="${made[0]}"]`)).toBeAttached({ timeout: 60_000 });
    // The text filter narrows the list. The pills' counts follow it.
    await panel.locator('.hk-search-input').fill('furnace');
    await expect(panel.locator('#hk-list ha-card.hk-card')).toHaveCount(COUNT / BASES.length);
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/526-panel-list-search.png` });

    // A task completes on another surface. The list loads again and shows it done.
    const card = panel.locator(`.hk-card[data-id="${made[0]}"]`);
    const before = await card.innerHTML();
    await callService('home_keeper', 'complete_task', { task_id: made[0] });
    await expect.poll(() => card.innerHTML(), { timeout: 20_000 }).not.toBe(before);
    await page.waitForTimeout(600);

    await page.setViewportSize(PHONE);
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/526b-panel-mobile-list-search.png` });
  } finally {
    await Promise.all(made.map(deleteTask));
  }
});
