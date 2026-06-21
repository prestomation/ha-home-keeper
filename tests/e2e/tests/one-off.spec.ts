import { test, expect, Locator } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';

/** Fill the input of the nth ha-form text selector within a scope. */
async function fillText(scope: Locator, nth: number, value: string): Promise<void> {
  await scope.locator('ha-selector-text').nth(nth).locator('input, textarea').fill(value);
}

/**
 * E2E coverage for one-off (do-once) tasks. The seed data has one *upcoming*
 * one-off (`task_passport`, a future due date) and one *completed* one-off
 * (`task_car_registration`, already done -> dormant, in the Completed section).
 */
test.describe('Home Keeper panel — one-off tasks', () => {
  test('an upcoming one-off shows its due date and a Done action', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const card = panel.locator('ha-card.hk-card', { hasText: 'Renew passport' }).first();
    await expect(card).toBeVisible();
    // It reads as a one-off and is still actionable until it's done.
    await expect(card).toContainText('One-off');
    await expect(card.locator('.done-btn')).toBeVisible();
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a completed one-off lives in a collapsed Completed section with no Done', async ({
    page,
  }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const completed = panel.locator('details.hk-group[data-group-key="status:completed"]');
    await expect(completed).toBeVisible();
    // Collapsed by default (out of the active list), so its cards aren't visible yet.
    await expect(completed).not.toHaveAttribute('open', /.*/);
    // Expanding reveals the completed one-off; it shows "Completed" and offers no
    // quick "Done" action (it's already done).
    await completed.locator('summary').click();
    const car = completed.locator('ha-card.hk-card', { hasText: 'car registration' }).first();
    await expect(car).toBeVisible();
    await expect(car).toContainText('Completed');
    await expect(car.locator('.done-btn')).toHaveCount(0);
  });

  test('the create form switches to one-off and reveals a due date picker', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#add-btn').click();
    await expect(panel.locator('#hk-task-form')).toBeVisible();
    // Switch the recurrence dropdown to One-off; a single datetime (Due) field appears.
    await panel.locator('#hk-task-form ha-select').first().click();
    await page.getByRole('menuitem', { name: /One-off/ }).first().click();
    await expect(panel.locator('#hk-task-form ha-selector-datetime').first()).toBeVisible();
  });

  test('create a one-off, complete it, and it moves to the Completed section', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const NAME = `E2E one-off ${Date.now()}`;

    // ── Add a one-off (defaulted due date = today) ───────────────────────────
    await panel.locator('#add-btn').click();
    await expect(panel.locator('#hk-task-form')).toBeVisible();
    await fillText(panel.locator('#hk-task-form'), 0, NAME);
    await panel.locator('#hk-task-form ha-select').first().click();
    await page.getByRole('menuitem', { name: /One-off/ }).first().click();
    await panel.locator('#f-save').click();

    // It shows up as a one-off, still actionable.
    const row = panel.locator('ha-card.hk-card', { hasText: NAME });
    await expect(row).toHaveCount(1, { timeout: 15_000 });
    await expect(row).toContainText('One-off');

    // ── Complete it (one-tap Done) -> dormant -> Completed section ────────────
    await row.locator('.done-btn').click();
    const completed = panel.locator('details.hk-group[data-group-key="status:completed"]');
    await completed.locator('summary').click();
    await expect(completed.locator('ha-card.hk-card', { hasText: NAME })).toHaveCount(1, {
      timeout: 15_000,
    });
    // No Done action once completed.
    await expect(
      completed.locator('ha-card.hk-card', { hasText: NAME }).locator('.done-btn'),
    ).toHaveCount(0);

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
