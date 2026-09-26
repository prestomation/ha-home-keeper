import { test, expect } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';
import { TASK } from '../fixture-ids';

/**
 * A switched-off task in the panel (issue #344).
 *
 * `enabled` is a field on `home_keeper.update_task`, so an automation on a helper can
 * take a pool's tasks out of every list while the pool is closed. The panel offers no
 * way to switch a task off and deliberately never will — a control that hides a task
 * from every surface on one mis-tap is worse than one that takes an action to reach.
 *
 * That makes the *way back* the load-bearing part, and it is what these assert. The
 * screenshots at `58-panel-task-disabled-list.png` and `59-panel-task-enable-banner.png`
 * photograph the same two surfaces; a capture proves a surface renders and asserts
 * nothing about it, which is how `4-usage-todo-and-calendar.png` documented #221 in
 * plain sight for months.
 */

/** Switch a task off the way an automation does — the only path there is. */
async function setEnabled(page, taskId: string, enabled: boolean): Promise<void> {
  await page.evaluate(
    async ({ id, on }) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const hass = (document.querySelector('home-assistant') as any)?.hass;
      if (!hass) throw new Error('no hass');
      await hass.callService('home_keeper', 'update_task', { task_id: id, enabled: on });
    },
    { id: taskId, on: enabled },
  );
}

test.describe('Home Keeper panel — a switched-off task', () => {
  test.afterEach(async ({ page }) => {
    await setEnabled(page, TASK.waterFilter, true).catch(() => undefined);
  });

  test('leaves the scope pills and their counts, and stays under All', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const seg = panel.locator('.hk-seg[data-seg="filter"]');
    const all = seg.locator('.hk-seg-btn[data-seg-val="all"]');
    const overdue = seg.locator('.hk-seg-btn[data-seg-val="overdue"]');

    const countOf = async (pill) =>
      Number((await pill.locator('.hk-seg-count').textContent()) ?? '-1');
    const allBefore = await countOf(all);
    const overdueBefore = await countOf(overdue);

    await setEnabled(page, TASK.waterFilter, false);
    // The panel rebuilds on the task_updated event; poll rather than race it.
    await expect.poll(async () => countOf(all), { timeout: 15_000 }).toBe(allBefore);
    expect(
      await countOf(overdue),
      'a switched-off task is not late work, whatever its frozen date says',
    ).toBeLessThan(overdueBefore + 1);

    // It is still reachable. All keeps it, under a section of its own.
    await all.click();
    const group = panel.locator('details.hk-group[data-group-key="status:disabled"]');
    await expect(group, 'a switched-off task gets a section, not the Overdue pile').toBeVisible({
      timeout: 15_000,
    });
    await expect(group.locator(`.detail-open[data-detail-id="${TASK.waterFilter}"]`)).toHaveCount(1);

    expect(errors, 'no panel errors').toEqual([]);
  });

  test('says Disabled on the row instead of a due date', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await setEnabled(page, TASK.waterFilter, false);

    const row = panel.locator(`ha-card.hk-card[data-id="${TASK.waterFilter}"]`);
    await expect(row.locator('ha-assist-chip.hk-disabled')).toBeVisible({ timeout: 15_000 });
    // The stored date is frozen where it was, so printing it would state a deadline
    // Home Keeper will not keep.
    await expect(row.locator('.hk-meta')).not.toContainText('Due');
    await expect(row, 'and the row is never painted as late work').not.toHaveClass(/overdue/);
  });

  test('offers Enable on its page, and no way to switch one off', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    // A live task's page carries no half of the switch at all.
    await panel.locator(`.detail-open[data-detail-id="${TASK.waterFilter}"]`).click();
    await expect(panel.locator('.hk-detail-title')).toBeVisible();
    await expect(panel.locator('.hk-disabled-banner')).toHaveCount(0);
    await expect(panel.locator('.d-enable'), 'nothing to enable on a live task').toHaveCount(0);

    await setEnabled(page, TASK.waterFilter, false);
    const banner = panel.locator('.hk-disabled-banner');
    await expect(banner, 'the page must say why nothing is happening').toBeVisible({
      timeout: 15_000,
    });
    await expect(banner).toContainText('disabled');

    await panel.locator('.d-enable').click();
    await expect(banner, 'Enable is the panel’s way back').toHaveCount(0, { timeout: 15_000 });
    // And the due date did not move: Enable switches on, it does not reschedule.
    await expect(panel.locator('.hk-disabled-banner')).toHaveCount(0);
  });
});
