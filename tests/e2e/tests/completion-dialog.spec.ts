import { test, expect } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';

test.describe('Home Keeper panel — completion dialog', () => {
  test('the completion-details dialog renders its action buttons and can be submitted', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    // "Replace fridge filter" is seeded with completion_detail: "optional", which
    // opens the completion-details dialog on Done instead of completing in one tap.
    await panel.locator('.done-btn[data-id="task_fridge_filter"]').click();

    // ha-dialog portals its surface, so wait on an inner field rather than the host.
    const dialog = panel.locator('ha-dialog[open]');
    const noteField = dialog.locator('ha-selector-text textarea, ha-selector-text input').first();
    await noteField.waitFor({ state: 'visible', timeout: 15_000 });

    // Regression guard for #144: HA's ha-dialog only exposes a "footer" slot, so
    // the dialog's action buttons must be wrapped in <ha-dialog-footer slot="footer">
    // — buttons slotted straight onto <ha-dialog> silently don't render at all.
    await expect(dialog.getByRole('button', { name: 'Mark done' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Skip details' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeVisible();

    await noteField.fill('E2E completion dialog regression check');
    await dialog.getByRole('button', { name: 'Mark done' }).click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
