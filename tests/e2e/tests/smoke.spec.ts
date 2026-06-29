import { test, expect, Locator } from '@playwright/test';
import { openPanel, openDashboard, trackPanelErrors } from './helpers';

/**
 * Pick an option from an HA `ha-select` dropdown by visible label. HA's current
 * `ha-select` is built on `ha-dropdown` (Web Awesome): clicking the field opens
 * a menu whose items are `ha-dropdown-item` with role="menuitem". The option
 * label is expected to be unique on the page so the match is unambiguous.
 */
async function chooseHaSelect(
  selectLocator: Locator,
  optionLabel: string | RegExp,
): Promise<void> {
  await selectLocator.click();
  await selectLocator.page().getByRole('menuitem', { name: optionLabel }).first().click();
}

test.describe('Home Keeper panel — smoke', () => {
  test('panel renders with seeded tasks and no panel errors', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);

    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('.hk-toolbar-title').first()).toContainText('Home Keeper');
    // Built from HA components: tabs, an add button, and ha-card rows.
    await expect(panel.locator('#tab-tasks')).toBeVisible();
    await expect(panel.locator('#add-btn')).toBeVisible();
    await expect(panel.locator('.hk-name')).toContainText(['Replace fridge filter']);
    await expect(panel.locator('ha-card.hk-card').first()).toBeVisible();

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('overdue task shows an overdue chip', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    // The seeded water filter is overdue -> red ha-assist-chip.
    await expect(panel.locator('ha-assist-chip.hk-overdue').first()).toBeVisible();
  });

  test('Add task opens an ha-form with recurrence + device picker', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#add-btn').click();
    await expect(panel.locator('#hk-form')).toBeVisible();
    const form = panel.locator('#hk-task-form');
    await expect(form).toBeVisible();
    // ha-form lazily renders its selector widgets: a text field (name), a select
    // (recurrence) and the searchable device picker.
    await expect(form.locator('ha-selector-text').first()).toBeVisible();
    await expect(form.locator('ha-select').first()).toBeVisible();
    await expect(form.locator('ha-selector-device')).toBeVisible();
  });

  test('switching to a fixed schedule reveals the datetime anchor field', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#add-btn').click();
    const form = panel.locator('#hk-task-form');
    await expect(form).toBeVisible();
    // The recurrence select is the first ha-select in the task form.
    await chooseHaSelect(form.locator('ha-select').first(), /fixed schedule/i);
    // Fixed schedule reveals the anchor datetime field; last_completed also adds
    // a second datetime selector, so use .first() to avoid strict-mode violation.
    await expect(panel.locator('#hk-task-form ha-selector-datetime').first()).toBeVisible();
  });

  test('Appliances tab lists the seeded virtual device and opens its form', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#tab-appliances').click();
    // The seeded "Garage water heater" virtual appliance appears with its chip.
    await expect(panel.locator('.hk-name')).toContainText(['Garage water heater']);
    await expect(panel.getByText('Virtual device').first()).toBeVisible();
    // Add-appliance form: name (text) field is present; dates are opt-in via the
    // metadata editor, so quick-adding the "Warranty expiry" seed reveals a date field.
    await panel.locator('#add-btn').click();
    const form = panel.locator('#hk-asset-form');
    await expect(form).toBeVisible();
    await expect(form.locator('ha-selector-text').first()).toBeVisible();
    // The "Custom fields" section collapses by default on a new appliance — expand it.
    await form.locator('details.hk-collapsible > summary').filter({ hasText: 'Custom fields' }).click();
    await form.locator('ha-button', { hasText: 'Warranty expiry' }).click();
    await expect(form.locator('ha-selector-date').first()).toBeVisible();
    // Switching to "existing device" adds the identity device picker alongside
    // the always-present "Related devices" picker (2 device selectors total).
    await chooseHaSelect(form.locator('ha-select').first(), /Existing device/);
    await expect(panel.locator('#hk-asset-form ha-selector-device')).toHaveCount(2);
  });

  test('appliance form parts editor adds a part and reveals wear fields', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#tab-appliances').click();
    await panel.locator('#add-btn').click();
    await expect(panel.locator('#hk-asset-form')).toBeVisible();
    // Related-device multi-picker and icon picker exist for a virtual asset.
    await expect(panel.locator('#hk-asset-form ha-selector-icon').first()).toBeVisible();
    await expect(panel.locator('#hk-asset-form ha-selector-device').first()).toBeVisible();
    // The "Parts & wear items" section collapses by default on a new appliance — expand it.
    await panel
      .locator('#hk-asset-form details.hk-collapsible > summary')
      .filter({ hasText: 'Parts & wear items' })
      .click();
    // Add a part; switching its type to "wear item" reveals the replacement
    // interval (a second ha-select — the replace unit — appears in the part).
    await panel.locator('#a-add-part').click();
    await expect(panel.locator('.hk-part')).toHaveCount(1);
    const part = panel.locator('.hk-part').first();
    await chooseHaSelect(part.locator('ha-select').first(), 'wear item');
    await expect(panel.locator('.hk-part').first().locator('ha-select')).toHaveCount(2);
  });

  test('task detail page lists completions and a trash button removes one', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    // Clicking a task's row opens its detail page, which shows the history inline.
    await panel.locator('.detail-open[data-detail-id="task_fridge_filter"]').click();
    const rows = panel.locator('.hk-hist-list li');
    await expect(rows.first()).toBeVisible();
    const before = await rows.count();
    expect(before).toBeGreaterThan(1);
    // Each row carries a trash (ha-icon-button) — delete the first completion.
    await panel.locator('.hk-hist-del').first().click();
    await expect(rows).toHaveCount(before - 1);
    // Still on the detail page after the in-place refresh.
    await expect(panel.locator('#back-btn')).toBeVisible();
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('appliance detail shows retained history of a removed task', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#tab-appliances').click();
    await panel.locator('.detail-open[data-detail-id="asset_water_heater"]').click();
    // The water heater's history includes a task that was deleted while still
    // assigned to it — surfaced as an archived "removed task" group.
    await expect(panel.locator('.hk-hist-group').first()).toBeVisible();
    await expect(panel).toContainText('Flush water heater tank');
    await expect(panel.locator('.hk-hist-archived').first()).toBeVisible();
  });

  test('filter + group-by controls re-bucket the task list', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    // Default grouping is by status — collapsible group sections are present.
    await expect(panel.locator('details.hk-group').first()).toBeVisible();
    // The "Overdue" quick filter narrows the list to the overdue chip(s).
    await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn', { hasText: 'Overdue' }).click();
    await expect(panel.locator('ha-assist-chip.hk-overdue').first()).toBeVisible();
    // Switching group-by to "None" renders a flat list (no group sections).
    await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn', { hasText: 'All' }).click();
    await panel.locator('.hk-seg[data-seg="group"] .hk-seg-btn', { hasText: 'None' }).click();
    await expect(panel.locator('details.hk-group')).toHaveCount(0);
    await expect(panel.locator('ha-card.hk-card').first()).toBeVisible();
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

});

test.describe('Home Keeper panel — deep linking & Back', () => {
  test('opening a detail page reflects in the URL', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('.detail-open[data-detail-id="task_fridge_filter"]').click();
    await expect(panel.locator('#back-btn')).toBeVisible();
    await expect(page).toHaveURL(/\/home-keeper\/tasks\/task_fridge_filter$/);
  });

  test('a task detail URL deep-links straight to the detail page', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await page.goto('/home-keeper/tasks/task_fridge_filter', { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    await panel.waitFor({ state: 'attached', timeout: 45_000 });
    // Lands on the detail page (Back button present), not the list.
    await expect(panel.locator('#back-btn')).toBeVisible();
    await expect(panel.locator('.hk-hist-list li').first()).toBeVisible();
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('the appliances tab is deep-linkable', async ({ page }) => {
    await page.goto('/home-keeper/appliances', { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    await panel.waitFor({ state: 'attached', timeout: 45_000 });
    await expect(panel.locator('.hk-name')).toContainText(['Garage water heater']);
  });

  test('browser Back returns to the list, not out of the panel', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('.detail-open[data-detail-id="task_fridge_filter"]').click();
    await expect(panel.locator('#back-btn')).toBeVisible();
    // The browser Back button steps back to the list inside the panel.
    await page.goBack();
    await expect(page).toHaveURL(/\/home-keeper(\/tasks)?$/);
    await expect(panel.locator('#tab-tasks')).toBeVisible();
    await expect(panel.locator('#back-btn')).toHaveCount(0);
  });

  test('the in-panel Back button returns to the list', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('.detail-open[data-detail-id="task_fridge_filter"]').click();
    await panel.locator('#back-btn').click();
    await expect(panel.locator('#tab-tasks')).toBeVisible();
    await expect(panel.locator('#back-btn')).toHaveCount(0);
  });

  test('Back from a task opened inside an appliance detail returns to the appliance detail', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    // Navigate to the Appliances tab and open the water heater (has active related tasks).
    await panel.locator('#tab-appliances').click();
    await panel.locator('.detail-open[data-detail-id="asset_water_heater"]').click();
    await expect(page).toHaveURL(/\/home-keeper\/appliances\/asset_water_heater$/);

    // Open the first related task from inside the appliance detail.
    const relatedTask = panel.locator('.hk-rel.detail-open[data-detail-kind="task"]').first();
    await expect(relatedTask).toBeVisible();
    const relatedTaskId = await relatedTask.getAttribute('data-detail-id');
    await relatedTask.click();
    await expect(page).toHaveURL(new RegExp(`/home-keeper/tasks/${relatedTaskId}$`));

    // In-panel Back must return to the appliance detail, not the task list.
    await panel.locator('#back-btn').click();
    await expect(page).toHaveURL(/\/home-keeper\/appliances\/asset_water_heater$/);
    // Back button is still visible because we're still inside a detail page.
    await expect(panel.locator('#back-btn')).toBeVisible();
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});

test.describe('Home Keeper panel — dashboard', () => {
  test('native to-do + calendar cards still render on the dashboard', async ({ page }) => {
    await openDashboard(page);
    await expect(page.locator('hui-todo-list-card, todo-list-card').first()).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.locator('ha-calendar, hui-calendar-card').first()).toBeVisible({
      timeout: 30_000,
    });
  });
});
