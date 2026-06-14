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
    await chooseHaSelect(form.locator('ha-select').first(), /Fixed/);
    await expect(panel.locator('#hk-task-form ha-selector-datetime')).toBeVisible();
  });

  test('Appliances tab lists the seeded virtual device and opens its form', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#tab-appliances').click();
    // The seeded "Garage water heater" virtual appliance appears with its chip.
    await expect(panel.locator('.hk-name')).toContainText(['Garage water heater']);
    await expect(panel.getByText('Virtual device').first()).toBeVisible();
    // Add-appliance form: name (text) + warranty (date) fields are present.
    await panel.locator('#add-btn').click();
    const form = panel.locator('#hk-asset-form');
    await expect(form).toBeVisible();
    await expect(form.locator('ha-selector-text').first()).toBeVisible();
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
    // Add a part; switching its type to "wear item" reveals the replacement
    // interval (a second ha-select — the replace unit — appears in the part).
    await panel.locator('#a-add-part').click();
    await expect(panel.locator('.hk-part')).toHaveCount(1);
    const part = panel.locator('.hk-part').first();
    await chooseHaSelect(part.locator('ha-select').first(), 'wear item');
    await expect(panel.locator('.hk-part').first().locator('ha-select')).toHaveCount(2);
  });

  test('native to-do + calendar cards render on the dashboard', async ({ page }) => {
    await openDashboard(page);
    await expect(page.locator('hui-todo-list-card, todo-list-card').first()).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.locator('ha-calendar, hui-calendar-card').first()).toBeVisible({
      timeout: 30_000,
    });
  });
});
