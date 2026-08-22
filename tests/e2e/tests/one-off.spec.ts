import { test, expect, Locator } from '@playwright/test';
import {
  deleteTask,
  expectAbsentFromActiveSurfaces,
  expectOnTodoList,
  listTasks,
  openPanel,
  todoSummaries,
  trackPanelErrors,
} from './helpers';

/** Fill the input of the nth ha-form text selector within a scope. */
async function fillText(scope: Locator, nth: number, value: string): Promise<void> {
  await scope.locator('ha-selector-text').nth(nth).locator('input, textarea').fill(value);
}

/**
 * E2E coverage for one-off (do-once) tasks. The seed data has one *upcoming*
 * one-off (`task_passport`, a future due date) and one *completed* one-off
 * (`task_car_registration`, already done -> dormant, in the Completed section).
 *
 * Completing a one-off is a *disappearance*: it goes dormant and has to leave the
 * to-do list, the calendar and the panel's active list at once. This file asserts
 * both halves of that transition — present before, absent after — on every
 * surface, not just the panel. Asserting only the panel is what let #221 ship: the
 * panel filed the task under Completed correctly while the to-do entity went on
 * offering it as needs_action forever.
 */
test.describe('Home Keeper panel — one-off tasks', () => {
  // Tasks these specs create, torn down after each test. The e2e container's task
  // store IS the committed seed fixture, so anything left behind is a permanent
  // addition to it (see tests/unit/test_integration_fixture_clean.py).
  let created: string[] = [];

  test.afterEach(async () => {
    await Promise.all(created.map(deleteTask));
    created = [];
  });

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

  test('the seeded completed one-off is off the to-do list and calendar', async ({ page }) => {
    // Regression (#221), asserted against the *seed* so it holds without depending
    // on the create/complete flow working. "Renew car registration" is dormant
    // (next_due null, last_completed set) and must appear on no active surface,
    // while the still-upcoming "Renew passport" must.
    await expectOnTodoList(page, 'Renew passport');
    await expectAbsentFromActiveSurfaces(page, 'Renew car registration');
  });

  test('the create form switches to one-off and reveals a due date picker', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#add-btn').click();
    await expect(panel.locator('#hk-task-form')).toBeVisible();
    // Switch the recurrence dropdown to One-off; a single datetime (Due) field appears.
    await panel.locator('#hk-task-form ha-select').first().click();
    await page.getByRole('menuitem', { name: /Just once/ }).first().click();
    await expect(panel.locator('#hk-task-form ha-selector-datetime').first()).toBeVisible();
  });

  test('create a one-off, complete it, and it leaves every active surface', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const NAME = 'E2E one-off probe';

    // ── Add a one-off (defaulted due date = today) ───────────────────────────
    await panel.locator('#add-btn').click();
    await expect(panel.locator('#hk-task-form')).toBeVisible();
    await fillText(panel.locator('#hk-task-form'), 0, NAME);
    await panel.locator('#hk-task-form ha-select').first().click();
    await page.getByRole('menuitem', { name: /Just once/ }).first().click();
    await panel.locator('#f-save').click();

    // It shows up as a one-off, still actionable.
    const row = panel.locator('ha-card.hk-card', { hasText: NAME });
    await expect(row).toHaveCount(1, { timeout: 15_000 });
    await expect(row).toContainText('One-off');
    // Register for teardown as soon as it exists, so a later failure still cleans up.
    const task = (await listTasks()).find((t) => t.name === NAME);
    expect(task, 'the created one-off should be in the store').toBeTruthy();
    created.push(task!.id);

    // ── Present on the to-do list *before* the completion ────────────────────
    // The half of the transition the suite used to skip: without it, "absent
    // after" would also pass for a task that was never listed at all.
    await expectOnTodoList(page, NAME);
    const before = (await todoSummaries()).length;

    // ── Complete it (one-tap Done) -> dormant ────────────────────────────────
    await openPanel(page);
    await panel.locator('ha-card.hk-card', { hasText: NAME }).locator('.done-btn').click();

    // The panel files it under Completed...
    const completed = panel.locator('details.hk-group[data-group-key="status:completed"]');
    await completed.locator('summary').click();
    await expect(completed.locator('ha-card.hk-card', { hasText: NAME })).toHaveCount(1, {
      timeout: 15_000,
    });
    // No Done action once completed.
    await expect(
      completed.locator('ha-card.hk-card', { hasText: NAME }).locator('.done-btn'),
    ).toHaveCount(0);

    // ...and it leaves the to-do list, the calendar and the panel's active list.
    await expectAbsentFromActiveSurfaces(page, NAME);
    // Exactly one item left the list — not zero (the bug), and not several.
    // Counted from the item list, not the entity's state: the state string is only
    // rewritten when the coordinator refreshes (a 5-minute interval plus debounced
    // explicit refreshes), so it trails the list by an unbounded amount under load.
    // `expectAbsentFromActiveSurfaces` has already polled the list to a settled
    // state, so this reads it once.
    expect((await todoSummaries()).length).toBe(before - 1);

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
