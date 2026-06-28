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
    await expect(
      card.locator('.hk-row', { hasText: 'Replace battery: Hallway smoke alarm' }),
    ).toHaveCount(1);
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

  test('the label-filtered card shows only labelled tasks, with named label chips', async ({
    page,
  }) => {
    await openCardDashboard(page);
    // The third card instance is configured labels: [dog], show_labels: true.
    const dog = page.locator('home-keeper-card').nth(2);
    await dog.waitFor({ state: 'attached', timeout: 30_000 });
    await expect(dog.locator('.hk-name', { hasText: 'Buddy: Medicine' })).toBeVisible({
      timeout: 30_000,
    });
    // Both seeded dog tasks pass the filter; non-dog tasks (e.g. the water filter) don't.
    await expect(dog.locator('.hk-name', { hasText: 'Rex: Vet checkup' })).toBeVisible();
    await expect(dog.locator('.hk-name', { hasText: 'Replace water filter' })).toHaveCount(0);
    // The label chip resolves the id to its registry name ("Dog", not "dog").
    await expect(dog.locator('ha-assist-chip.hk-label').first()).toHaveAttribute('label', 'Dog');
  });

  test('a task surfaces its chosen appliance links as openable chips', async ({ page }) => {
    const card = await openCardDashboard(page);
    // The seeded water-filter task pins three of its appliance's documents: an
    // external link ("Owner's manual"), a metadata link ("Reorder filter"), and an
    // uploaded file ("Installation guide (PDF)").
    const row = card.locator('.hk-row', { hasText: 'Replace water filter' });
    await expect(row).toHaveCount(1, { timeout: 30_000 });
    // External links render as anchors that open in a new tab.
    const links = row.locator('a.hk-link');
    await expect(links).toHaveCount(2);

    const manual = links.filter({ hasText: "Owner's manual" });
    await expect(manual).toHaveAttribute('href', 'https://example.com/water-heater-manual');
    await expect(manual).toHaveAttribute('target', '_blank');
    await expect(manual).toHaveAttribute('rel', /noopener/);
    // The metadata link resolves to its label + value.
    await expect(links.filter({ hasText: 'Reorder filter' })).toHaveAttribute(
      'href',
      'https://example.com/reorder-water-filter',
    );

    // An uploaded file has no static URL — it renders as a button that mints a
    // short-lived signed URL on click, so it's a <button>, not an <a>.
    const fileChip = row.locator('button.hk-link');
    await expect(fileChip).toHaveCount(1);
    await expect(fileChip).toContainText('Installation guide (PDF)');
  });

  test('add and complete a task from the card; rows no longer open an edit form', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    const card = await openCardDashboard(page);

    const NAME = `E2E card task ${Date.now()}`;

    // ── Add (header button — still available; the add form has no Delete) ───
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

    // ── Tapping the row no longer opens an inline edit form ────────────────
    // Editing/deleting moved to the sidebar panel so a stray tap can't open a
    // form (and can't reach Delete). The row's body is inert.
    await row.locator('.grow').click();
    await expect(card.locator('.hk-form')).toHaveCount(0);

    // ── Complete (trailing Done still works) ───────────────────────────────
    await row.locator('.hk-done').click();
    // Completing a floating task advances next_due ~1 month -> no longer overdue.
    await expect(card.locator('.hk-row.overdue', { hasText: NAME })).toHaveCount(0, {
      timeout: 15_000,
    });
    await expect(card.locator('.hk-row', { hasText: NAME })).toHaveCount(1);

    expect(errors, `card errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
