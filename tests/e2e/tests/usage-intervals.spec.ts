import { test, expect } from '@playwright/test';
import { openPanel, openTaskTab, trackPanelErrors } from './helpers';
import { TASK } from '../fixture-ids';

/**
 * The usage between completions on a metered task (issue #305).
 *
 * The seeded nozzle task meters printer hours and carries three services, at 120, 375
 * and 660 h — so the two intervals are +255 h and +285 h, and the four summary figures
 * are four different numbers. Asserted here rather than only in the capture walk,
 * because a screenshot documents a surface without covering it (#221).
 */
test.describe('Home Keeper panel — usage between completions', { tag: '@responsive' }, () => {
  test('each row carries its own interval, and the strip summarises them', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    // The nozzle task is dormant (the meter has not reached its target), so it lives
    // in the collapsed Monitored group.
    const monitored = panel.locator('details.hk-group[data-group-key="status:monitored"]');
    if (!(await monitored.evaluate((el: HTMLDetailsElement) => el.open))) {
      await monitored.locator('summary').click();
    }
    await panel.locator(`.detail-open[data-detail-id="${TASK.nozzleUsage}"]`).click();
    await openTaskTab(panel, 'history');

    const rows = panel.locator('.hk-hist-list li');
    await expect(rows).toHaveCount(3);
    // Newest first: 660 h is +285 h past the 375 h before it.
    await expect(rows.nth(0).locator('.hk-hist-chips')).toContainText('at 660 h');
    await expect(rows.nth(0).locator('.hk-hist-delta')).toHaveText('+285 h');
    await expect(rows.nth(1).locator('.hk-hist-delta')).toHaveText('+255 h');
    // The oldest completion has nothing before it to subtract.
    await expect(rows.nth(2).locator('.hk-hist-delta')).toHaveCount(0);

    const figures = panel.locator('.hk-hist-usage > div');
    await expect(figures).toHaveCount(4);
    await expect(figures.nth(0)).toContainText('Last interval');
    await expect(figures.nth(0)).toContainText('285 h');
    await expect(figures.nth(1)).toContainText('270 h');
    await expect(figures.nth(2)).toContainText('255 h');
    await expect(figures.nth(3)).toContainText('285 h');

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a time-based task keeps a history with no interval anywhere', async ({ page }) => {
    // The strip and the delta belong to a meter. A task counted in months has readings
    // nowhere to derive them from, and must not grow an empty block.
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator(`.detail-open[data-detail-id="${TASK.fridgeFilter}"]`).click();
    await openTaskTab(panel, 'history');

    await expect(panel.locator('.hk-hist-list li').first()).toBeVisible();
    await expect(panel.locator('.hk-hist-usage')).toHaveCount(0);
    await expect(panel.locator('.hk-hist-delta')).toHaveCount(0);
  });
});
