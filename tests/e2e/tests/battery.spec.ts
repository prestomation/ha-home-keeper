import { test, expect } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';

/**
 * E2E coverage for condition-driven (triggered) tasks — the model behind the
 * Battery Notes glue. The seed data has one *active* battery task
 * (`task_door_battery`, due-now) and two *dormant* ones (`task_smoke_battery`,
 * `task_thermostat_battery`, monitored/not-due), all managed by "Battery Notes".
 */
test.describe('Home Keeper panel — triggered / battery tasks', () => {
  test('an active battery task shows overdue + Managed by Battery Notes', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const card = panel.locator('ha-card.hk-card', { hasText: 'Front door sensor' }).first();
    await expect(card).toBeVisible();
    // Due-now -> overdue chip; managed -> "Managed by Battery Notes" chip.
    await expect(card.locator('ha-assist-chip.hk-overdue')).toBeVisible();
    await expect(card.locator('ha-assist-chip.hk-managed')).toContainText('Battery Notes');
    // It carries a quick "Done" (mark replaced) action while armed.
    await expect(card.locator('.done-btn')).toBeVisible();
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('dormant battery tasks live in a collapsed Monitored section', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const monitored = panel.locator('details.hk-group[data-group-key="status:monitored"]');
    await expect(monitored).toBeVisible();
    // Collapsed by default (out of the way), so its cards aren't visible yet.
    await expect(monitored).not.toHaveAttribute('open', /.*/);
    // The section count reflects the two dormant battery tasks.
    await expect(monitored.locator('.hk-group-count')).toHaveText('2');
    // Expanding reveals the dormant tasks; a dormant one shows "Monitored" and has
    // no quick "Done" action (nothing to mark done until its battery goes low).
    await monitored.locator('summary').click();
    const smoke = monitored.locator('ha-card.hk-card', { hasText: 'smoke alarm' }).first();
    await expect(smoke).toBeVisible();
    await expect(smoke).toContainText('Monitored');
    await expect(smoke.locator('.done-btn')).toHaveCount(0);
  });

  test('an active battery task detail shows monitored schedule + replacement history', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('.detail-open[data-detail-id="task_door_battery"]').click();
    await expect(panel.locator('#back-btn')).toBeVisible();
    // Schedule row reads "Monitored", not a recurrence rule.
    await expect(panel).toContainText('Monitored (condition-driven)');
    // The replacement history (cadence) is listed.
    await expect(panel.locator('.hk-hist-list li').first()).toBeVisible();
    // Editing a managed triggered task offers no recurrence/cadence editor.
    await panel.locator('.d-edit').click();
    await expect(panel.locator('#hk-task-form')).toBeVisible();
    // The recurrence select is absent (no schedule to choose) for a triggered task.
    await expect(panel.locator('#hk-task-form ha-select')).toHaveCount(0);
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a dormant battery task detail offers no Done action', async ({ page }) => {
    // The dormant task lives in the collapsed Monitored section, so deep-link
    // straight to its detail page rather than clicking a hidden row.
    await page.goto('/home-keeper/tasks/task_smoke_battery', { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    await panel.waitFor({ state: 'attached', timeout: 45_000 });
    await expect(panel.locator('#back-btn')).toBeVisible();
    await expect(panel).toContainText('Monitored');
    // Dormant -> no "Done" button on the detail page (only when armed).
    await expect(panel.locator('.d-done')).toHaveCount(0);
  });
});
