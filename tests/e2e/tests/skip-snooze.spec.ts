import { test, expect } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';
import { TASK } from '../fixture-ids';

/** Deep-link straight to a panel destination and wait for the element to attach. */
async function gotoPanel(page: import('@playwright/test').Page, path: string) {
  await page.goto(`/home-keeper${path}`, { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  return panel;
}

/**
 * Snooze and skip, reached from the panel (issue #268).
 *
 * Both verbs shipped as services and notification buttons long before this, but
 * neither had a websocket command, so the panel — which only talks `callWS` — could
 * not offer them at all. These drive the real chrome: the caret beside Done, the
 * snooze dialog's preset picker, and the skip appearing in history without being
 * counted as a completion.
 */
test.describe('Home Keeper panel — snooze and skip', { tag: '@responsive' }, () => {
  test('the caret beside Done opens a menu naming both verbs', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await gotoPanel(page, `/tasks/${TASK.waterFilter}`);

    const caret = panel.locator('.hk-detail-actions .hk-split-caret');
    await expect(caret).toBeVisible();
    await expect(caret).toHaveAttribute('aria-expanded', 'false');

    await caret.click();
    const menu = panel.locator('.hk-defer-menu');
    await expect(menu).toBeVisible();
    await expect(caret).toHaveAttribute('aria-expanded', 'true');
    await expect(menu.locator('.hk-defer-snooze')).toBeVisible();
    await expect(menu.locator('.hk-defer-skip')).toBeVisible();
    // Each entry says what it does to the schedule — the verbs are not
    // self-explanatory, which is what the issue was about.
    await expect(menu.locator('.hk-defer-snooze .hk-defer-sub')).not.toBeEmpty();

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('Escape closes the menu without acting', async ({ page }) => {
    const panel = await gotoPanel(page, `/tasks/${TASK.waterFilter}`);

    await panel.locator('.hk-split-caret').click();
    await expect(panel.locator('.hk-defer-menu')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(panel.locator('.hk-defer-menu')).toBeHidden();
  });

  test('the snooze dialog previews the date its preset resolves to', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await gotoPanel(page, `/tasks/${TASK.waterFilter}`);

    await panel.locator('.hk-split-caret').click();
    await panel.locator('.hk-defer-snooze').click();

    const dialog = panel.locator('ha-dialog[open]');
    // Same `ha-dialog-footer` structure every other dialog needs (#144): buttons
    // slotted straight onto ha-dialog silently do not render.
    const footer = dialog.locator('ha-dialog-footer[slot="footer"]');
    await expect(footer).toHaveCount(1);
    await expect(footer.locator('ha-button[slot="primaryAction"]')).toHaveCount(1);
    await expect(dialog.locator('[slot="headerTitle"]')).toBeVisible();

    // The user reads the resolved date rather than doing the arithmetic.
    const hint = dialog.locator('.hk-snooze-hint');
    await expect(hint).toBeVisible();
    await expect(hint).not.toBeEmpty();

    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('skipping logs the skip in history without counting it as a completion', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    const panel = await gotoPanel(page, `/tasks/${TASK.carRegistration}`);

    const before = await panel.locator('.hk-hist-sub').first().textContent();

    await panel.locator('.hk-split-caret').click();
    await panel.locator('.hk-defer-skip').click();

    const dialog = panel.locator('ha-dialog[open]');
    await expect(dialog.locator('[slot="headerTitle"]')).toBeVisible();
    await dialog.getByRole('button', { name: 'Skip' }).click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });

    // The skip shows in history, marked as one…
    const skipRow = panel.locator('.hk-hist-list li.hk-hist-is-skip').first();
    await expect(skipRow).toBeVisible({ timeout: 10_000 });
    await expect(skipRow.locator('.hk-hist-skip-chip')).toBeVisible();
    // …and the completion tally is exactly what it was, because a skip is the record
    // of *not* doing the thing. This is the assertion the separate log exists for.
    await expect(panel.locator('.hk-hist-sub').first()).toHaveText(before ?? '');

    // Undo it, so the seeded fixture is left as the other specs expect it.
    await skipRow.locator('.hk-hist-skip-del').click();
    await expect(panel.locator('.hk-hist-list li.hk-hist-is-skip')).toHaveCount(0, {
      timeout: 10_000,
    });

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a problem-sensor task offers snooze but not skip', async ({ page }) => {
    // The store rejects skip on a synced mirror — only the originating integration
    // can say the problem is dealt with — so offering it would be a dead button.
    // Snooze asserts nothing about the problem, so it stays.
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const blocked = panel.locator('.hk-card .done-blocked-wrap, .hk-card .hk-auto-clear').first();
    if ((await blocked.count()) === 0) test.skip(true, 'no completion-blocked task seeded');

    const row = panel.locator('.hk-card').filter({ has: blocked }).first();
    const caret = row.locator('.hk-split-caret');
    if ((await caret.count()) === 0) return; // dormant mirror: no caret at all, also correct
    await caret.click();
    await expect(row.locator('.hk-defer-snooze')).toBeVisible();
    await expect(row.locator('.hk-defer-skip')).toHaveCount(0);
  });

  test('turning a verb off in Settings withdraws it from the task page', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await gotoPanel(page, '/settings/skipsnooze');

    const card = panel.locator('#hk-settings-skipsnooze');
    await expect(card).toBeVisible();
    // Both default on, so the summary says so before anything is touched.
    await expect(card).toContainText(/available/i);

    const skipSwitch = card.locator('ha-selector-boolean ha-switch, ha-switch').nth(1);
    await skipSwitch.click();

    await gotoPanel(page, `/tasks/${TASK.waterFilter}`);
    await panel.locator('.hk-split-caret').click();
    await expect(panel.locator('.hk-defer-snooze')).toBeVisible();
    await expect(panel.locator('.hk-defer-skip')).toHaveCount(0);

    // Put it back — the seeded options are shared with the other specs.
    await gotoPanel(page, '/settings/skipsnooze');
    await panel.locator('#hk-settings-skipsnooze ha-switch').nth(1).click();
    await expect(panel.locator('#hk-settings-skipsnooze')).toContainText(/available/i);

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
