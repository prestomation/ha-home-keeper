import { test, expect, type Locator, type Page } from '@playwright/test';
import {
  callService,
  createTask,
  deleteTask,
  holdsFocus,
  openCardDashboard,
  openPanel,
  openSettingsSection,
  trackPanelErrors,
} from './helpers';

/**
 * Every action that loses data asks first, in 1 dialog, and the safe answer is the
 * default. This spec checks that for each kind of dialog:
 * Cancel holds the keyboard, and Cancel, Escape and a tap outside each leave the data
 * alone. The delete of a history entry has its own spec (`history-delete-confirm`).
 *
 * Each spec makes what it deletes and removes it again, and never confirms a delete of
 * a seeded record.
 */

const scrim = (page: Page) => page.locator('.hk-confirm-scrim');
const cancelOf = (page: Page) =>
  scrim(page).locator('ha-button').filter({ hasText: 'Cancel' });
const danger = (page: Page) => scrim(page).locator('ha-button[data-hk-weight="danger-primary"]');

/**
 * Open a dialog, then close it 3 ways. After each, `unchanged` must still hold.
 * Cancel must hold the keyboard while the dialog is open.
 */
async function safeByDefault(
  page: Page,
  open: () => Promise<void>,
  unchanged: () => Promise<void>,
): Promise<void> {
  await open();
  await expect(scrim(page)).toBeVisible();
  await expect.poll(() => holdsFocus(cancelOf(page))).toBe(true);
  await expect(scrim(page).locator('[role="alertdialog"]')).toHaveAttribute('aria-modal', 'true');

  await cancelOf(page).click();
  await expect(scrim(page)).toHaveCount(0);
  await unchanged();

  await open();
  await expect(scrim(page)).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(scrim(page)).toHaveCount(0);
  await unchanged();

  await open();
  await expect(scrim(page)).toBeVisible();
  await scrim(page).click({ position: { x: 4, y: 4 } });
  await expect(scrim(page)).toHaveCount(0);
  await unchanged();
}

test.describe('Home Keeper — every delete asks first', { tag: '@responsive' }, () => {
  test('deleting a task says what happens to its history', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const taskId = await createTask({ name: 'E2E confirm task', interval: 90, unit: 'days' });
    try {
      await callService('home_keeper', 'complete_task', { task_id: taskId });
      await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
      const panel = page.locator('home-keeper-panel').first();
      await expect(panel.locator('.d-del')).toBeVisible({ timeout: 45_000 });

      await safeByDefault(
        page,
        async () => {
          await panel.locator('.d-del').click();
        },
        async () => {
          await expect(panel.locator('.d-del')).toBeVisible();
        },
      );

      await panel.locator('.d-del').click();
      await expect(scrim(page).locator('#hk-confirm-title')).toHaveText(
        'Delete "E2E confirm task"?',
      );
      // A task that no appliance owns takes its history with it, and the dialog says so.
      await expect(scrim(page).locator('#hk-confirm-body')).toContainText(
        'History entries deleted with it: 1.',
      );
      await expect(danger(page)).toHaveText('Delete task');
      await danger(page).click();
      await expect(scrim(page)).toHaveCount(0);
      await expect
        .poll(async () => (await callService('home_keeper', 'list_tasks', {}, true)).tasks.some(
          (t: any) => t.id === taskId,
        ))
        .toBe(false);
    } finally {
      await deleteTask(taskId);
    }
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('deleting an appliance says what goes with it', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const name = 'E2E confirm appliance';
    await callService('home_keeper', 'add_asset', { name });
    const read = async () =>
      (await callService('home_keeper', 'list_assets', {}, true)).assets.find(
        (a: any) => a.name === name,
      );
    const asset = await read();
    try {
      await page.goto(`/home-keeper/appliances/${asset.id}`, { waitUntil: 'domcontentloaded' });
      const panel = page.locator('home-keeper-panel').first();
      await expect(panel.locator('.d-del')).toBeVisible({ timeout: 45_000 });

      await safeByDefault(
        page,
        async () => {
          await panel.locator('.d-del').click();
        },
        async () => {
          expect(await read()).toBeTruthy();
        },
      );

      await panel.locator('.d-del').click();
      await expect(scrim(page).locator('#hk-confirm-title')).toHaveText(`Delete "${name}"?`);
      await expect(scrim(page).locator('#hk-confirm-body')).toContainText(
        'Its parts, documents and notes are deleted too.',
      );
      await expect(danger(page)).toHaveText('Delete appliance');
      await danger(page).click();
      await expect.poll(async () => await read()).toBeFalsy();
    } finally {
      await callService('home_keeper', 'delete_asset', { asset_id: asset.id }).catch(() => {});
    }
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('deleting a notification asks, and a profile in use blocks with only Close', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    const filter = { status: 'all', labels: [], areas: [], devices: [] };
    await callService('home_keeper', 'set_options', {
      profiles: [{ id: 'e2e_ce_profile', name: 'E2E held profile', filter }],
      notifications: [
        {
          id: 'e2e_ce_notify',
          name: 'E2E bin day',
          profile_id: 'e2e_ce_profile',
          targets: [],
          actions: ['complete'],
          style: 'walk',
          snooze_hours: 24,
          channel: '',
          urgency: 'normal',
          auto: { overdue: false, due_soon: false },
        },
      ],
    });
    const stored = async () =>
      page.evaluate(async () => {
        const hass = (document.querySelector('home-assistant') as any).hass;
        const res = await hass.callWS({ type: 'home_keeper/get_options' });
        return { n: res.options.notifications.length, p: res.options.profiles.length };
      });
    const openRow = async (panel: Locator, list: string, name: string): Promise<Locator> => {
      const row = panel.locator(`${list} .hk-item-card`).filter({ hasText: name }).first();
      const header = row.locator('> .hk-item-header');
      if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click();
      return row.locator('> .hk-item-body .hk-notify-delete');
    };
    try {
      await openPanel(page);
      const panel = page.locator('home-keeper-panel').first();

      // The notification.
      await openSettingsSection(panel, 'notifications');
      await expect(panel.locator('#hk-notifications')).toBeVisible();
      const del = await openRow(panel, '#hk-notifications', 'E2E bin day');
      await safeByDefault(
        page,
        async () => {
          await del.click();
        },
        async () => {
          expect((await stored()).n).toBe(1);
        },
      );
      await del.click();
      await expect(scrim(page).locator('#hk-confirm-title')).toHaveText('Delete "E2E bin day"?');
      await expect(danger(page)).toHaveText('Delete notification');

      // The profile that this notification uses: a notice with only Close, which holds
      // the keyboard too.
      await cancelOf(page).click();
      await openSettingsSection(panel, 'profiles');
      await expect(panel.locator('#hk-profiles')).toBeVisible();
      const blocked = await openRow(panel, '#hk-profiles', 'E2E held profile');
      await blocked.click();
      await expect(scrim(page)).toContainText('E2E bin day');
      const close = scrim(page).locator('ha-button');
      await expect(close).toHaveCount(1);
      await expect(close).toHaveText('Close');
      await expect.poll(() => holdsFocus(close)).toBe(true);
      await page.keyboard.press('Escape');
      await expect(scrim(page)).toHaveCount(0);
      expect((await stored()).p).toBe(1);
    } finally {
      await callService('home_keeper', 'set_options', { profiles: [], notifications: [] });
    }
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});

test.describe('Home Keeper card — confirm before completing', { tag: '@responsive' }, () => {
  test('asks in the panel dialog, and Cancel, Escape and a tap outside complete nothing', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    const card = await openCardDashboard(page);
    // The seeded dashboard card does not set the option, so set it on the live card.
    await card.evaluate((el: any) => el.setConfig({ ...el._config, confirm_complete: true }));
    await expect(card.locator('.hk-done').first()).toBeVisible();
    const before = await card.locator('.hk-row').count();

    await safeByDefault(
      page,
      async () => {
        await card.locator('.hk-done:not(.blocked)').first().click();
      },
      async () => {
        await expect(card.locator('.hk-row')).toHaveCount(before);
      },
    );

    await card.locator('.hk-done:not(.blocked)').first().click();
    await expect(scrim(page).locator('#hk-confirm-title')).toContainText('done?');
    // The button says what it does and is not red: marking done loses nothing.
    await expect(
      scrim(page).locator('ha-button[data-hk-weight="primary"]'),
    ).toHaveText('Done');
    await cancelOf(page).click();
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
