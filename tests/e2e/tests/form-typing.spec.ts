import { test, expect } from '@playwright/test';
import { gotoTab, openPanel } from './helpers';
import { ASSET } from '../fixture-ids';

/**
 * Typing in a Home Keeper form must reach the field, not Home Assistant.
 *
 * HA registers single-letter global shortcuts on `window` (tinykeys): `e` entity
 * quick bar, `c` commands, `d` devices, `m` a my-link, `a` Assist. They stand down
 * only while the keydown target is a text input — so the moment a panel re-render
 * replaces the box being typed in, focus falls back to `<body>` and the rest of the
 * word is swallowed as hotkeys. A user hit exactly that: typing a task name popped
 * up the device search, and once opened Assist.
 *
 * This is the end-to-end guard, against the real `ha-form` and the real shortcut
 * handler; `frontend/test/form-focus.test.js` pins the re-render invariant underneath
 * it. Both matter: only the browser can prove HA didn't take the keystrokes.
 */
test.describe('form typing vs. HA global keyboard shortcuts', { tag: '@responsive' }, () => {
  test('a typed task name stays in the field (no quick bar, no Assist)', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#add-btn').click();

    const form = panel.locator('#hk-task-form');
    await expect(form).toBeVisible();
    const name = form.locator('ha-selector-text input').first();
    await name.click();
    await expect(name).toBeFocused();

    // Every one of HA's shortcut letters appears here: d, e, c, a, m.
    const typed = 'Descale machine';
    await page.keyboard.type(typed, { delay: 40 });

    await expect(name).toHaveValue(typed);
    await expect(name, 'the field must still hold focus after the last character').toBeFocused();
    // The dialogs those letters open, none of which the user asked for.
    await expect(page.locator('ha-quick-bar')).toHaveCount(0);
    await expect(page.locator('ha-voice-command-dialog')).toHaveCount(0);
    await expect(page.locator('dialog-shortcuts')).toHaveCount(0);
  });

  test('a typed appliance name stays in the field', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await gotoTab(panel, 'appliances');
    await panel.locator('#add-btn').click();

    const form = panel.locator('#hk-asset-form');
    await expect(form).toBeVisible();
    const name = form.locator('ha-selector-text input').first();
    await name.click();
    await expect(name).toBeFocused();

    const typed = 'Dehumidifier';
    await page.keyboard.type(typed, { delay: 40 });

    await expect(name).toHaveValue(typed);
    await expect(page.locator('ha-quick-bar')).toHaveCount(0);
    await expect(page.locator('ha-voice-command-dialog')).toHaveCount(0);
  });
});

/**
 * Issue #296: the first digit typed into an empty Stock box rebuilt the appliance
 * drawer, so the box lost focus and the sheet scrolled back to its top (on iOS the
 * keyboard closed with it). Driven at the sheet width, where the scroll reset was
 * the symptom, and through the Parts tab's Edit — the drawer opens on that part.
 */
test.describe('typing a part quantity keeps the field and the drawer where they are', {
  tag: '@narrow',
}, () => {
  test('the first digit into an empty Stock box reveals the next field in place', async ({
    page,
  }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await gotoTab(panel, 'appliances');
    await panel.locator(`.detail-open[data-detail-id="${ASSET.waterHeater}"]`).click();
    // The T&P relief valve (second part) tracks no stock in the seed.
    await panel.locator('#part-edit-1').click();

    const form = panel.locator('#hk-asset-form');
    await expect(form).toBeVisible();
    // `details`: the custom-fields editor boxes share the class and index.
    const part = form.locator('details.hk-part[data-idx="1"]');
    await expect(part).toHaveAttribute('open', '');
    await expect(part.getByText('Used per completion', { exact: false })).toHaveCount(0);

    // The Stock box: the part's number fields run cost, stock, reorder at.
    const stock = part.locator('ha-selector-number input').nth(1);
    await stock.click();
    await expect(stock).toBeFocused();
    const scroller = panel.locator('.hk-drawer-sticky');
    const before = await scroller.evaluate((el) => el.scrollTop);
    expect(before, 'the opened part should have been scrolled to').toBeGreaterThan(0);

    await page.keyboard.type('2', { delay: 40 });

    await expect(stock).toHaveValue('2');
    await expect(stock, 'the field must keep focus once the part starts tracking stock').toBeFocused();
    // Revealed in place, in the part's own dependent form.
    await expect(part.getByText('Used per completion', { exact: false })).toBeVisible();
    const after = await scroller.evaluate((el) => el.scrollTop);
    expect(Math.abs(after - before), 'the sheet must not jump').toBeLessThan(4);
    await expect(page.locator('ha-quick-bar')).toHaveCount(0);

    // Leave the seed alone.
    await panel.locator('#a-cancel').click();
  });
});
