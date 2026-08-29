import { test, expect } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';
import { ASSET, TASK } from '../fixture-ids';

/**
 * Editing happens beside the page Edit was pressed on.
 *
 * Edit used to navigate: from a task's own page it went back to the task list and
 * opened the drawer there, so the history, the notes and the schedule that explain
 * the values being edited went off screen at the moment they mattered most. These
 * pin the page staying put — and, on an appliance, the master list stepping aside so
 * the form is a second column rather than a third.
 *
 * Untagged: this is the desktop layout, where the drawer is a column. Below 1150px it
 * is a sheet over the page, which `responsive-layout.spec.ts` owns.
 */
test.describe('Home Keeper panel — editing beside a detail page', () => {
  test('a task keeps its page while the form is open', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    await panel.locator(`.detail-open[data-detail-id="${TASK.fridgeFilter}"]`).click();
    await expect(page).toHaveURL(new RegExp(`/home-keeper/tasks/${TASK.fridgeFilter}$`));
    await expect(panel.locator('.hk-hist-list li').first()).toBeVisible();

    await panel.locator('.d-edit').click();

    // The form is open…
    await expect(panel.locator('#hk-form')).toBeVisible();
    await expect(panel.locator('.hk-drawer[data-open]')).toBeVisible();
    // …beside the page it was opened from, which is still on screen and still legible
    // (the history is the context the form is being filled in against).
    await expect(page).toHaveURL(new RegExp(`/home-keeper/tasks/${TASK.fridgeFilter}$`));
    await expect(panel.locator('#back-btn')).toBeVisible();
    await expect(panel.locator('.hk-hist-list li').first()).toBeVisible();
    // History in the drawer's footer is a way to this page, so it is not offered here.
    await expect(panel.locator('.hk-drawer-history')).toHaveCount(0);

    // Closing leaves the page rather than a list.
    await panel.locator('#f-cancel').click();
    await expect(panel.locator('#hk-form')).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`/home-keeper/tasks/${TASK.fridgeFilter}$`));
    await expect(panel.locator('.d-edit')).toBeVisible();

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('an appliance keeps its page, and its list steps aside for the form', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await page.goto(`/home-keeper/appliances/${ASSET.waterHeater}`, {
      waitUntil: 'domcontentloaded',
    });
    const panel = page.locator('home-keeper-panel').first();
    await panel.waitFor({ state: 'attached', timeout: 45_000 });
    // An appliance is read beside its list, so both are on screen to begin with.
    await expect(panel.locator('.hk-master')).toBeVisible();
    await expect(panel.locator('.hk-detail-pane')).toBeVisible();

    await panel.locator('.d-edit').click();

    await expect(panel.locator('#hk-asset-form')).toBeVisible();
    await expect(panel.locator('.hk-detail-pane')).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/home-keeper/appliances/${ASSET.waterHeater}`));
    // Three columns do not fit, so the list is the one that goes.
    await expect(panel.locator('.hk-master')).toBeHidden();

    await panel.locator('#a-cancel').click();
    await expect(panel.locator('#hk-asset-form')).toHaveCount(0);
    await expect(panel.locator('.hk-master')).toBeVisible();

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('saving from the page updates it in place', async ({ page }) => {
    // The point of editing here: the change lands on the page you are reading, and
    // the reading position is not spent going back to it.
    const errors = trackPanelErrors(page);
    await page.goto(`/home-keeper/tasks/${TASK.waterFilter}`, {
      waitUntil: 'domcontentloaded',
    });
    const panel = page.locator('home-keeper-panel').first();
    await panel.waitFor({ state: 'attached', timeout: 45_000 });
    const heading = panel.locator('.hk-detail-title').first();
    const original = (await heading.textContent())?.trim() ?? '';
    expect(original, 'the seeded task should have a name').not.toBe('');

    await panel.locator('.d-edit').click();
    await expect(panel.locator('#hk-form')).toBeVisible();

    const renamed = `${original} (edited)`;
    const nameField = panel.locator('#hk-form input').first();
    await nameField.fill(renamed);
    await panel.locator('#f-save').click();

    // Still the same page, now showing the new name.
    await expect(panel.locator('#hk-form')).toHaveCount(0);
    await expect(heading).toHaveText(renamed);
    await expect(page).toHaveURL(new RegExp('/home-keeper/tasks/'));

    // Put the name back so the seeded fixture is unchanged for the next spec.
    await panel.locator('.d-edit').click();
    await expect(panel.locator('#hk-form')).toBeVisible();
    await panel.locator('#hk-form input').first().fill(original);
    await panel.locator('#f-save').click();
    await expect(heading).toHaveText(original);

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
