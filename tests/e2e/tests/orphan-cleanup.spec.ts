import { test, expect, Locator } from '@playwright/test';
import { openPanel, openPanelAt, trackPanelErrors } from './helpers';
import { TASK } from '../fixture-ids';

/**
 * "Remove orphaned tasks" asks first (F07-5), in a real modal dialog (X11-1).
 *
 * The seed has one task (Rex's vet visit) whose managing integration is not loaded,
 * so the task list shows the orphan banner. These open the confirm dialog and cancel
 * it — never confirm it, because the orphaned task is shared fixture data that the
 * capture harness and other specs photograph. The screenshots
 * `71-panel-orphan-confirm.png` / `71c-panel-mobile-orphan-confirm.png` photograph the
 * same dialog; a capture asserts nothing, so this spec does.
 */
/**
 * Whether *el* holds the keyboard. `ha-button` delegates focus to a button inside its
 * own shadow root, so Playwright's `toBeFocused` (which compares the innermost element)
 * reads the host as inactive. Walk the chain of shadow-root active elements instead.
 */
async function holdsFocus(el: Locator): Promise<boolean> {
  return el.evaluate((node: Element) => {
    let at: Element | null = document.activeElement;
    while (at) {
      if (at === node) return true;
      at = at.shadowRoot?.activeElement ?? null;
    }
    return false;
  });
}

test.describe('Home Keeper panel — orphan cleanup confirm', () => {
  test('opens a named dialog with focus on Cancel, and Cancel deletes nothing', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('.hk-orphan-banner')).toBeVisible();
    const orphanRow = panel.locator(`.detail-open[data-detail-id="${TASK.rexVet}"]`);
    await expect(orphanRow).toBeVisible();

    await panel.locator('#cleanup-orphans-btn').click();

    // The scrim is appended to document.body, outside the panel's shadow root.
    const dialog = page.getByRole('dialog', { name: 'Delete 1 orphaned task?' });
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAttribute('aria-modal', 'true');
    await expect(dialog.locator('#hk-confirm-body')).toContainText('This cannot be undone.');
    const cancel = dialog.locator('ha-button').filter({ hasText: 'Cancel' });
    await expect.poll(() => holdsFocus(cancel)).toBe(true);
    await expect(dialog.locator('ha-button').filter({ hasText: 'Delete' })).toBeVisible();

    await cancel.click();
    await expect(page.locator('.hk-confirm-scrim')).toHaveCount(0);
    // Nothing was deleted: the banner and the orphaned task are both still there.
    await expect(panel.locator('.hk-orphan-banner')).toBeVisible();
    await expect(orphanRow).toBeVisible();
    // Focus goes back to the button that opened the dialog.
    await expect.poll(() => holdsFocus(panel.locator('#cleanup-orphans-btn'))).toBe(true);
    expect(errors).toEqual([]);
  });

  test('fits a 320px screen and closes on Escape', async ({ page }) => {
    const panel = await openPanelAt(page, { width: 320, height: 640 });
    await expect(panel.locator('.hk-orphan-banner')).toBeVisible();
    await panel.locator('#cleanup-orphans-btn').click();
    const dialog = page.getByRole('dialog', { name: 'Delete 1 orphaned task?' });
    await expect(dialog).toBeVisible();
    const box = await dialog.boundingBox();
    expect(box, 'the dialog has a layout box').not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(320);
    await page.keyboard.press('Escape');
    await expect(page.locator('.hk-confirm-scrim')).toHaveCount(0);
    await expect(panel.locator('.hk-orphan-banner')).toBeVisible();
  });
});
