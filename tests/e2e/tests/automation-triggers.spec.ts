import { test, expect } from '@playwright/test';
import {
  openAddTrigger,
  searchTriggers,
  showDeviceTriggers,
  showHomeKeeperByType,
  triggerRow,
} from '../automation-triggers';

/**
 * The Home Keeper triggers in Home Assistant's Add trigger dialog (#415).
 *
 * Home Keeper ships its own triggers (`trigger.py`, `triggers.yaml`), so the dialog
 * lists them by name: in the search, under By type and under By target on a device
 * with Home Keeper entities. The garage water heater is a seeded appliance with a
 * task and parts.
 */
test.describe('Home Keeper triggers in the automation editor', () => {
  test('a search finds a Home Keeper trigger by name @responsive', async ({ page }) => {
    const dialog = await openAddTrigger(page);
    await searchTriggers(dialog, 'overdue');
    // A search result is a list item, not a target row.
    await expect(dialog.getByText('Task became overdue', { exact: true })).toBeVisible();
  });

  test('By type lists the Home Keeper triggers with descriptions', async ({ page }) => {
    const dialog = await openAddTrigger(page);
    await showHomeKeeperByType(dialog);
    await expect(triggerRow(dialog, 'Task completed')).toBeAttached();
    await expect(triggerRow(dialog, 'Spare part low on stock')).toBeAttached();
    await expect(triggerRow(dialog, 'Data exported')).toBeAttached();
  });

  test('By target on an appliance device lists its triggers', async ({ page }) => {
    const dialog = await openAddTrigger(page);
    await showDeviceTriggers(dialog, 'Garage water heater');
    await expect(dialog.getByText('Home Keeper', { exact: true })).toBeVisible();
    await expect(triggerRow(dialog, 'Spare part low on stock')).toBeAttached();
    // The device has no event entity, so Event received is not offered here.
    await expect(triggerRow(dialog, 'Event received')).toHaveCount(0);
    // A trigger with no target, such as Data exported, is not a device trigger.
    await expect(triggerRow(dialog, 'Data exported')).toHaveCount(0);
  });

  test('a trigger picked by target keeps the device as its target', async ({ page }) => {
    const dialog = await openAddTrigger(page);
    await showDeviceTriggers(dialog, 'Garage water heater');
    await triggerRow(dialog, 'Task became overdue').click();
    await expect(dialog).toBeHidden();
    const row = page.locator('ha-automation-trigger-row').first();
    await expect(row).toContainText('Task became overdue');
    await expect(row).toContainText('Garage water heater');
  });
});
