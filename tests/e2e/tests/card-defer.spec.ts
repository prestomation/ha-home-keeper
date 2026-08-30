import { expect, test } from '@playwright/test';
import { openCardDashboard } from './helpers';

/**
 * The dashboard card's half of #268.
 *
 * The panel got the caret first and the card was deferred; this is the guard that it
 * did not stay deferred. The card's Done is a dense icon button, so the caret is a
 * narrower sibling rather than a segment of a pill — but everything behind it is the
 * panel's, which is the point of the shared module.
 */
test.describe('Home Keeper card — snooze and skip', () => {
  test('the caret opens the menu, and the menu opens the snooze dialog @responsive', async ({
    page,
  }) => {
    const card = await openCardDashboard(page);
    const split = card.locator('.hk-split').first();
    await expect(split).toBeVisible();

    const menu = split.locator('.hk-defer-menu');
    await expect(menu).toBeHidden();
    await split.locator('.hk-row-caret').click();
    await expect(menu.locator('.hk-defer-snooze')).toBeVisible();
    await expect(menu.locator('.hk-defer-skip')).toBeVisible();

    await menu.locator('.hk-defer-snooze').click();
    // The dialog is the panel's, resolving its preset to a real date.
    await expect(page.locator('ha-dialog[open] .hk-snooze-hint').first()).toBeVisible();
  });

  test('the closed menu takes up no space and swallows no clicks @responsive', async ({
    page,
  }) => {
    const card = await openCardDashboard(page);
    const menu = card.locator('.hk-defer-menu').first();
    // `display: flex` beats the user-agent rule for the bare `hidden` attribute, so a
    // closed menu would still be laid out — over the row beneath it, eating its Done.
    await expect(menu).toHaveCSS('display', 'none');
  });

  test('Escape closes the menu without acting @responsive', async ({ page }) => {
    const card = await openCardDashboard(page);
    const split = card.locator('.hk-split').first();
    await split.locator('.hk-row-caret').click();
    await expect(split.locator('.hk-defer-menu .hk-defer-skip')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(split.locator('.hk-defer-menu')).toBeHidden();
    await expect(page.locator('ha-dialog[open]')).toHaveCount(0);
  });
});
