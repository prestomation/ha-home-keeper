import { test, expect } from '@playwright/test';
import { TASK } from '../fixture-ids';
import {
  createTask,
  deleteTask,
  openPanel,
  openSettingsSection,
  setMinimalLayout,
  trackPanelErrors,
} from './helpers';

/**
 * The minimal task layout: the per-user Settings toggle, the 2-column grid it
 * swaps in, and the tap-opens-popup / press-and-hold-opens-details interaction
 * on its cards.
 *
 * The preference is per-user, server-side state (HA's `frontend/set_user_data`,
 * like the intro-banner dismissal) — and the e2e suite runs every spec against
 * one shared HA container with a single browser session, so a test that turns it
 * on must always turn it back off, or every later spec's row-list locators break.
 * `setMinimalLayout` goes straight through the live `hass` rather than the
 * Settings UI so cleanup in `afterEach` can't itself fail.
 */

test.describe('Home Keeper panel — minimal task layout', () => {
  test.afterEach(async ({ page }) => {
    await setMinimalLayout(page, false);
  });

  test('the Settings toggle swaps the row list for the 2-column grid', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('#hk-list .hk-card-row').first()).toBeVisible();
    await expect(panel.locator('.hk-card-minimal')).toHaveCount(0);

    await openSettingsSection(panel, 'general');
    const sw = panel.locator('#hk-settings-general ha-switch');
    await expect(sw).toBeVisible();
    await sw.click();
    await expect
      .poll(() => sw.evaluate((el: HTMLElement & { checked?: boolean }) => !!el.checked))
      .toBe(true);

    await panel.locator('#tab-tasks').click();
    await expect(panel.locator('.hk-minimal-grid').first()).toBeVisible();
    await expect(panel.locator('.hk-card-minimal').first()).toBeVisible();
    await expect(panel.locator('#hk-list .hk-card-row')).toHaveCount(0);
    // Name and status only — no chips, no meta line, no inline button.
    await expect(panel.locator('.hk-card-minimal').first().locator('.hk-meta')).toHaveCount(0);
    await expect(panel.locator('.hk-card-minimal').first().locator('ha-button')).toHaveCount(0);

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a monitored task has no Done row in the quick-actions popup', async ({ page }) => {
    // setMinimalLayout reaches through the live `hass`, which needs the panel
    // (or any HA page) already loaded once — a brand-new page has no
    // `home-assistant` element yet, so open it first.
    await openPanel(page);
    await setMinimalLayout(page, true);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    // Renew car registration: a completed one-off, dormant like a monitored task —
    // nothing left to complete, so Done (and Skip/Snooze, which need a due date)
    // are all absent, leaving only View details. Completed is collapsed by
    // default, so expand it first.
    const completed = panel.locator('details.hk-group[data-group-key="status:completed"]');
    await expect(completed).toBeVisible();
    await completed.locator('summary').click();
    const card = panel.locator(`.hk-card-minimal[data-id="${TASK.carRegistration}"]`);
    await expect(card).toBeVisible();
    await card.click();
    const dialog = page.locator('ha-dialog[open]').first();
    // Not `expect(dialog).toBeVisible()`: the `ha-dialog` host itself is a zero-size
    // wrapper (its content renders through an internal, slotted `wa-dialog`), so
    // every dialog check in this codebase asserts on a descendant instead.
    await expect(dialog).toHaveAttribute('heading', 'Renew car registration');
    await expect(dialog.getByRole('button', { name: 'View details' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Done', exact: true })).toHaveCount(0);
    await expect(dialog.getByRole('button', { name: 'Skip', exact: true })).toHaveCount(0);
    await expect(dialog.getByRole('button', { name: 'Snooze', exact: true })).toHaveCount(0);
  });

  test('press-and-hold opens the task page; a tap opens quick actions and Done completes it', async ({
    page,
  }) => {
    const id = await createTask({
      name: 'E2E minimal-grid scratch task',
      recurrence_type: 'one-off',
      due: '2026-01-02T09:00:00-04:00',
    });
    try {
      // See the note above: `home-assistant` has to exist before `setMinimalLayout`
      // can reach its `hass`, so open the panel once before setting it.
      await openPanel(page);
      await setMinimalLayout(page, true);
      await openPanel(page);
      const panel = page.locator('home-keeper-panel').first();
      const card = panel.locator(`.hk-card-minimal[data-id="${id}"]`);
      await expect(card).toBeVisible();

      // Press-and-hold opens the task's own page — same page a click opens on the
      // standard list — rather than the popup. Retried like `openRow` in shots.ts:
      // a live entity update mid-hold can re-render the grid and cancel the
      // pointer capture (a real pointercancel, same class of race that helper
      // exists for), so one held press can land on nothing.
      const detailRow = panel.locator('.hk-detail-row', { hasText: 'Next due' });
      await expect
        .poll(
          async () => {
            if (await detailRow.isVisible().catch(() => false)) return true;
            const box = await card.boundingBox().catch(() => null);
            if (!box) return false;
            await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
            await page.mouse.down();
            await page.waitForTimeout(700);
            await page.mouse.up();
            return detailRow.isVisible().catch(() => false);
          },
          { timeout: 20_000 },
        )
        .toBe(true);
      await expect(page.locator('ha-dialog[open]')).toHaveCount(0);
      await panel.locator('#back-btn').click();
      await expect(card).toBeVisible();

      // A plain tap opens the quick-actions popup instead.
      await card.click();
      const dialog = page.locator('ha-dialog[open]').first();
      await expect(dialog).toHaveAttribute('heading', 'E2E minimal-grid scratch task');
      await expect(dialog.getByRole('button', { name: 'Done', exact: true })).toBeVisible();
      await expect(dialog.getByRole('button', { name: 'View details' })).toBeVisible();

      // Mark done actually completes it: the popup closes and the task moves into
      // the (collapsed-by-default) Completed section — still in the DOM, same as
      // the standard list, just no longer visible in the active groups.
      await dialog.getByRole('button', { name: 'Done', exact: true }).click();
      await expect(page.locator('ha-dialog[open]')).toHaveCount(0);
      await expect(card).not.toBeVisible({ timeout: 10_000 });
    } finally {
      await deleteTask(id);
    }
  });
});
