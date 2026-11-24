import { test, expect } from '@playwright/test';
import {
  callService,
  createTask,
  deleteTask,
  openAppliance,
  openPanel,
  trackPanelErrors,
} from './helpers';

/**
 * Deleting a history entry asks first (issue #597). A tap on the trash can used to
 * remove the entry at once, so a slip lost a record and the user could not tell which.
 * The dialog names the entry. Cancel, Escape and a tap outside keep it.
 */
test.describe('Home Keeper panel — history delete confirmation', { tag: '@responsive' }, () => {
  let taskId: string | undefined;

  test.afterEach(async () => {
    await deleteTask(taskId);
    taskId = undefined;
  });

  async function open(page: import('@playwright/test').Page) {
    taskId = await createTask({ name: 'E2E car oil', interval: 90, unit: 'days' });
    await callService('home_keeper', 'complete_task', { task_id: taskId, note: 'Synthetic oil' });
    await page.goto(`/home-keeper/tasks/${taskId}/history`, { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('.hk-hist-list li')).toHaveCount(1, { timeout: 45_000 });
    return panel;
  }

  test('the trash can opens a dialog that names the entry', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await open(page);
    await panel.locator('.hk-hist-del').click();

    const scrim = page.locator('.hk-confirm-scrim');
    await expect(scrim).toBeVisible();
    await expect(scrim.locator('#hk-confirm-title')).toContainText('Delete the entry of');
    await expect(scrim.locator('#hk-confirm-body')).toContainText('Synthetic oil');
    // Nothing is gone yet, and Cancel holds the keyboard.
    await expect(panel.locator('.hk-hist-list li')).toHaveCount(1);
    await expect(scrim.locator('ha-button[data-hk-weight="danger-primary"]')).toBeAttached();
    await expect(
      page.locator('.hk-confirm-scrim ha-button').filter({ hasText: 'Cancel' }),
    ).toBeFocused();
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('Cancel, Escape and a tap outside keep the entry', async ({ page }) => {
    const panel = await open(page);
    const scrim = page.locator('.hk-confirm-scrim');

    await panel.locator('.hk-hist-del').click();
    await scrim.locator('ha-button').filter({ hasText: 'Cancel' }).click();
    await expect(scrim).toHaveCount(0);

    await panel.locator('.hk-hist-del').click();
    await expect(scrim).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(scrim).toHaveCount(0);

    await panel.locator('.hk-hist-del').click();
    await expect(scrim).toBeVisible();
    await scrim.click({ position: { x: 4, y: 4 } });
    await expect(scrim).toHaveCount(0);

    await expect(panel.locator('.hk-hist-list li')).toHaveCount(1);
  });

  test('Delete removes the entry', async ({ page }) => {
    const panel = await open(page);
    await panel.locator('.hk-hist-del').click();
    await page.locator('.hk-confirm-scrim ha-button[data-hk-weight="danger-primary"]').click();
    await expect(page.locator('.hk-confirm-scrim')).toHaveCount(0);
    await expect(panel.locator('.hk-hist-list li')).toHaveCount(0, { timeout: 10_000 });
  });

  test('an archived completion on an appliance asks first too, and shows HTML as text', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    const name = 'E2E archive boiler';
    await callService('home_keeper', 'add_asset', { name });
    const read = async () =>
      (await callService('home_keeper', 'list_assets', {}, true)).assets.find(
        (a: any) => a.name === name,
      );
    const asset = await read();
    try {
      // A task on the appliance's device. Deleting it archives its history there.
      taskId = await createTask({
        name: 'E2E archive task',
        interval: 90,
        unit: 'days',
        device_id: asset.device_id,
      });
      await callService('home_keeper', 'complete_task', {
        task_id: taskId,
        note: '<b>Synthetic</b> oil',
      });
      await callService('home_keeper', 'delete_task', { task_id: taskId });
      taskId = undefined;

      await openPanel(page);
      const panel = await openAppliance(page, asset.id, 'history');
      const rows = panel.locator('.hk-hist-list li');
      await expect(rows).toHaveCount(1, { timeout: 45_000 });
      const scrim = page.locator('.hk-confirm-scrim');

      await panel.locator('.hk-hist-del[data-del-asset]').click();
      await expect(scrim.locator('#hk-confirm-title')).toContainText('Delete the entry of');
      // The note is shown as typed, not as markup.
      const body = scrim.locator('#hk-confirm-body');
      await expect(body).toContainText('<b>Synthetic</b> oil');
      await expect(body.locator('b')).toHaveCount(0);

      await scrim.locator('ha-button').filter({ hasText: 'Cancel' }).click();
      await expect(scrim).toHaveCount(0);
      await expect(rows).toHaveCount(1);

      await panel.locator('.hk-hist-del[data-del-asset]').click();
      await scrim.locator('ha-button[data-hk-weight="danger-primary"]').click();
      await expect(scrim).toHaveCount(0);
      await expect(rows).toHaveCount(0, { timeout: 10_000 });
    } finally {
      await callService('home_keeper', 'delete_asset', { asset_id: asset.id }).catch(() => {});
    }
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
