/**
 * Opens Home Assistant's "Add trigger" dialog in a new automation, and shows the
 * Home Keeper triggers in it. The trigger spec, the screenshot capture and the
 * walkthrough use these steps.
 *
 * A trigger row is a button whose name is the trigger name plus its target, so a
 * step finds it by a name that starts with the trigger name.
 */
import { expect, type Locator, type Page } from '@playwright/test';

/** Open a new automation and its Add trigger dialog. Return the dialog. */
export async function openAddTrigger(page: Page): Promise<Locator> {
  await page.goto('/config/automation/edit/new', { waitUntil: 'domcontentloaded' });
  await page.getByText('Add trigger').first().click();
  const dialog = page.locator('add-automation-element-dialog');
  await expect(dialog.getByText('By target', { exact: true })).toBeVisible({
    timeout: 30000,
  });
  return dialog;
}

/** The row of 1 trigger in the dialog. */
export function triggerRow(dialog: Locator, name: string): Locator {
  return dialog.getByRole('button', { name: new RegExp(`^${name}`) }).first();
}

/** By target: open the device, so the dialog lists its triggers. */
export async function showDeviceTriggers(dialog: Locator, device: string): Promise<void> {
  await dialog.getByText('Devices', { exact: true }).click();
  await dialog.getByText(device, { exact: true }).first().click();
  await expect(triggerRow(dialog, 'Task became overdue')).toBeAttached({ timeout: 15000 });
}

/** By type: select the Home Keeper integration. */
export async function showHomeKeeperByType(dialog: Locator): Promise<void> {
  await dialog.getByText('By type', { exact: true }).click();
  await dialog.getByText('Home Keeper', { exact: true }).first().click();
  await expect(dialog.getByText('Triggers when an appliance is added.')).toBeVisible({
    timeout: 15000,
  });
}

/** Type in the dialog search. */
export async function searchTriggers(dialog: Locator, text: string): Promise<void> {
  await dialog.getByPlaceholder('Search').fill(text);
  await expect(dialog.getByText('Triggers when a task becomes overdue.')).toBeVisible({
    timeout: 15000,
  });
}
