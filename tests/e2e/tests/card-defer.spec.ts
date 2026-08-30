import { expect, test } from '@playwright/test';
import { openCardDashboard } from './helpers';

/**
 * The dashboard card's half of #268.
 *
 * The task page tucks snooze and skip behind a caret on Done; the card puts them on
 * the row as their own buttons, because a chevron beside a same-sized icon button had
 * nothing to lean on and read as decoration. Everything behind them — the dialogs, the
 * services — is the panel's, which is the point of the shared module.
 */
test.describe('Home Keeper card — snooze and skip', () => {
  test('both verbs are on the row, ahead of Done @responsive', async ({ page }) => {
    const card = await openCardDashboard(page);
    const acts = card.locator('.hk-acts').first();
    await expect(acts.locator('.hk-defer-snooze')).toBeVisible();
    await expect(acts.locator('.hk-defer-skip')).toBeVisible();

    // Done stays the rightmost target — the one a thumb reaches first — so the row
    // still has one obvious action despite carrying three.
    const [snooze, skip, done] = await Promise.all([
      acts.locator('.hk-defer-snooze').boundingBox(),
      acts.locator('.hk-defer-skip').boundingBox(),
      acts.locator('.hk-done').boundingBox(),
    ]);
    expect(snooze!.x).toBeLessThan(skip!.x);
    expect(skip!.x).toBeLessThan(done!.x);
  });

  test('snooze opens the same dialog the panel uses @responsive', async ({ page }) => {
    const card = await openCardDashboard(page);
    await card.locator('.hk-defer-snooze').first().click();
    // The resolved-date line is what makes it the panel's dialog rather than a
    // card-local imitation: it previews where the chosen preset lands.
    await expect(page.locator('ha-dialog[open] .hk-snooze-hint').first()).toBeVisible();
  });

  test('skip opens the skip dialog @responsive', async ({ page }) => {
    const card = await openCardDashboard(page);
    await card.locator('.hk-defer-skip').first().click();
    // Assert on what is inside the dialog, not on `ha-dialog` itself: the host
    // element has no box of its own — its surface is painted inside its shadow
    // root — so a visibility check on the host reads as hidden even when the
    // dialog is plainly on screen.
    const dialog = page.locator('ha-dialog[open]').first();
    await expect(dialog.locator('ha-form')).toBeVisible();
    await expect(dialog).toHaveAttribute('heading', /.+/);
  });

  test('a completion-blocked row offers snooze but not skip @responsive', async ({ page }) => {
    const card = await openCardDashboard(page);
    // The synced problem task: the store rejects skipping it, so the button that
    // would always error is absent — while snooze, which it does accept, is not.
    const row = card.locator('.hk-row', { hasText: 'Sump pump problem' }).first();
    await expect(row).toBeVisible();
    await expect(row.locator('.hk-defer-snooze')).toBeVisible();
    await expect(row.locator('.hk-defer-skip')).toHaveCount(0);
  });

  test('a dormant row offers neither @responsive', async ({ page }) => {
    const card = await openCardDashboard(page);
    // A completed one-off has no due date left to defer.
    const row = card.locator('.hk-row', { hasText: 'Renew car registration' }).first();
    await expect(row).toBeVisible();
    await expect(row.locator('.hk-defer-snooze')).toHaveCount(0);
    await expect(row.locator('.hk-defer-skip')).toHaveCount(0);
  });
});
