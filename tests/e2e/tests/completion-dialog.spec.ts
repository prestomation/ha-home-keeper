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
    // Assert the structure, not just visibility, so a future revert back to
    // slotting directly on <ha-dialog> fails here even before it's visibly broken.
    const footer = dialog.locator('ha-dialog-footer[slot="footer"]');
    await expect(footer).toHaveCount(1);
    await expect(footer.locator('ha-button[slot="primaryAction"]')).toHaveCount(1);
    await expect(footer.locator('ha-button[slot="secondaryAction"]')).toHaveCount(2);

    await expect(dialog.getByRole('button', { name: 'Mark done' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Skip details' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeVisible();

    await noteField.fill('E2E completion dialog regression check');
    await dialog.getByRole('button', { name: 'Mark done' }).click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('the move-date dialog renders its action buttons and can be cancelled', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    await panel.locator('.detail-open[data-detail-id="task_fridge_filter"]').click();
    await expect(panel.locator('.hk-hist-list li').first()).toBeVisible();
    await panel.locator('.hk-hist-move').first().click();

    const dialog = panel.locator('ha-dialog[open]');
    const dateField = dialog.locator('ha-selector-datetime').first();
    await dateField.waitFor({ state: 'visible', timeout: 15_000 });

    // Same regression guard as the completion dialog (#144/#147): the move-date
    // dialog is built by hand alongside it and must wrap its buttons the same way.
    const footer = dialog.locator('ha-dialog-footer[slot="footer"]');
    await expect(footer).toHaveCount(1);
    await expect(footer.locator('ha-button[slot="primaryAction"]')).toHaveCount(1);
    await expect(footer.locator('ha-button[slot="secondaryAction"]')).toHaveCount(1);

    await expect(dialog.getByRole('button', { name: 'Save' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeVisible();

    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
