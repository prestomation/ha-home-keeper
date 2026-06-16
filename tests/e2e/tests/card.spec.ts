import { test, expect, Locator } from '@playwright/test';
import { openCardDashboard, trackPanelErrors } from './helpers';

/** Fill the nth `ha-selector-text` inside a scope (the card's inline form). */
async function fillText(scope: Locator, nth: number, value: string): Promise<void> {
  const field = scope.locator('ha-selector-text').nth(nth).locator('input, textarea');
  await field.click();
  await field.fill(value);
}

test.describe('Home Keeper card — dashboard', () => {
  test('renders seeded tasks with one-tap Done, no card errors', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const card = await openCardDashboard(page);

    // The card header and seeded task rows render (built from HA components).
    await expect(card.locator('.hk-title').first()).toContainText('Home maintenance');
    await expect(card.locator('.hk-name')).toContainText(['Replace fridge filter']);
    await expect(card.locator('.hk-row').first()).toBeVisible();
    // Active tasks carry a trailing Done action.
    await expect(card.locator('.hk-done').first()).toBeVisible();

    expect(errors, `card errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('overdue task shows an overdue chip; dormant triggered task has no Done', async ({
    page,
  }) => {
    const card = await openCardDashboard(page);
    // The seeded water filter is overdue -> red ha-assist-chip + left accent.
    await expect(card.locator('ha-assist-chip.hk-overdue').first()).toBeVisible();
    await expect(card.locator('.hk-row.overdue').first()).toBeVisible();
    // A dormant (monitored) battery task has nothing to complete — its owner
    // arms it — so it renders without a Done button.
    await expect(card.locator('[data-edit-id="task_smoke_battery"]')).toHaveCount(1);
    await expect(card.locator('.hk-done[data-id="task_smoke_battery"]')).toHaveCount(0);
  });

  test('the grouped card buckets tasks into collapsible status sections', async ({ page }) => {
    await openCardDashboard(page);
    // The second card instance is configured group_by: status.
    const grouped = page.locator('home-keeper-card').nth(1);
    await grouped.waitFor({ state: 'attached', timeout: 30_000 });
    await expect(grouped.locator('details.hk-group').first()).toBeVisible({ timeout: 30_000 });
    // An "Overdue" section header is present (the water filter is overdue).
    await expect(
      grouped.locator('details.hk-group .hk-group-title', { hasText: 'Overdue' }).first(),
    ).toBeVisible();
  });

  test('full lifecycle: add, complete, edit, then delete a task from the card', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    const card = await openCardDashboard(page);

    const NAME = `E2E card task ${Date.now()}`;
    const RENAMED = `${NAME} (edited)`;

    // ── Add ───────────────────────────────────────────────────────────────
    await card.locator('#hk-add').click();
    const form = card.locator('.hk-form');
    await expect(form).toBeVisible();
    // ha-form renders nested ha-form elements for grid sub-schemas; the top-level
    // one (with the name field) is first.
    await expect(form.locator('ha-form').first()).toBeVisible();
    await fillText(form, 0, NAME); // first text selector is the name
    await form.locator('ha-button', { hasText: 'Create' }).click();

    // The new floating task (never completed) lands due-now -> overdue row.
    const row = card.locator('.hk-row', { hasText: NAME });
    await expect(row).toHaveCount(1, { timeout: 15_000 });
    await expect(card.locator('.hk-row.overdue', { hasText: NAME })).toHaveCount(1);

    // ── Complete (trailing Done) ───────────────────────────────────────────
    await row.locator('.hk-done').click();
    // Completing a floating task advances next_due ~1 month -> no longer overdue.
    await expect(card.locator('.hk-row.overdue', { hasText: NAME })).toHaveCount(0, {
      timeout: 15_000,
    });
    await expect(card.locator('.hk-row', { hasText: NAME })).toHaveCount(1);

    // ── Edit (row click opens the inline form) ─────────────────────────────
    await card.locator('.hk-row', { hasText: NAME }).locator('.grow').click();
    const editForm = card.locator('.hk-form');
    await expect(editForm).toBeVisible();
    await fillText(editForm, 0, RENAMED);
    await editForm.locator('ha-button', { hasText: 'Save' }).click();
    await expect(card.locator('.hk-row', { hasText: RENAMED })).toHaveCount(1, { timeout: 15_000 });

    // ── Delete (inline form Delete button, confirm dialog) ─────────────────
    page.once('dialog', (dialog) => dialog.accept());
    await card.locator('.hk-row', { hasText: RENAMED }).locator('.grow').click();
    await expect(card.locator('.hk-form')).toBeVisible();
    await card.locator('.hk-form ha-button', { hasText: 'Delete' }).click();
    await expect(card.locator('.hk-row', { hasText: NAME })).toHaveCount(0, { timeout: 15_000 });

    expect(errors, `card errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
