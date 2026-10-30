/**
 * One-off screenshot capture for what a user sees after a notification sent to
 * `persistent_notification` (#521) — not part of the e2e suite (the filename is not
 * *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-notify-sent.config.ts
 *
 * Two shots for each width: the panel with the saved notification and its chosen target,
 * then Home Assistant's own notifications drawer holding the text that Test delivered.
 */
import { expect, test, type Page } from '@playwright/test';
import { callService, createTask, deleteTask, openPanel } from './tests/helpers';
import { PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/hk-shots';
const LABEL = 'hk_shot_sent_521';

let taskId = '';
let savedProfiles: unknown[] = [];

test.beforeAll(async () => {
  savedProfiles = (await callService('home_keeper', 'list_profiles', {}, true)).profiles ?? [];
  taskId = await createTask({
    name: 'Rinse the compost bin',
    recurrence_type: 'floating',
    interval: 7,
    unit: 'days',
    labels: [LABEL],
  });
});

test.afterAll(async () => {
  await callService('persistent_notification', 'dismiss_all', {});
  await deleteTask(taskId);
  // The seed fixture holds no notification, so an empty list is the original state.
  await callService('home_keeper', 'set_options', { profiles: savedProfiles, notifications: [] });
});

/** Seed a notification with no target, pick one in the form, and press Test. */
async function sendFromPicker(page: Page, panelShot: string): Promise<void> {
  await callService('home_keeper', 'set_options', {
    profiles: [
      {
        id: 'shot-sent-profile',
        name: 'Compost',
        filter: { status: 'all', labels: [LABEL] },
      },
    ],
    notifications: [
      {
        id: 'shot-sent-notify',
        name: 'Compost walk',
        profile_id: 'shot-sent-profile',
        targets: [],
        actions: ['complete'],
        snooze_hours: 24,
        style: 'walk',
        channel: '',
        urgency: 'normal',
        icon: '',
        color: '',
        auto: { overdue: false, due_soon: false },
      },
    ],
  });
  await callService('persistent_notification', 'dismiss_all', {});
  await openPanel(page);
  await page.goto('/home-keeper/settings/notifications', { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  const card = panel.locator('#hk-notifications');
  await expect(card).toBeVisible({ timeout: 30_000 });
  const row = card.locator('.hk-item-card').first();
  await row.locator('> .hk-item-header').click();
  const form = row.locator('.hk-item-body > ha-form').nth(1);
  await expect(form).toBeVisible({ timeout: 20_000 });
  await form.getByText('Send to', { exact: true }).first().click();
  await page.getByText('persistent_notification', { exact: true }).first().click();
  await page.keyboard.press('Escape');
  // The pick is saved by a debounce; wait until the chip shows and the write is done.
  await expect(card.locator('.hk-save-status')).toHaveText('Saved', { timeout: 15_000 });
  // The saved notification, with the chosen target in the form.
  await expect(form.getByText('persistent_notification', { exact: true })).toBeVisible();
  await form.getByText('Send to', { exact: true }).first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  await page.screenshot({ path: panelShot });
  await row.locator('.hk-notify-test').click();
  await expect(page.locator('.message')).toContainText('Notification sent.');
}

test('capture the delivered notification', async ({ page }) => {
  await sendFromPicker(page, `${OUT}/22e-panel-notify-sent.png`);

  await page.locator('ha-sidebar').getByText('Notifications', { exact: true }).click();
  await expect(page.getByText('Rinse the compost bin').first()).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('Due now.').first()).toBeVisible();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/22f-ha-notification-delivered.png` });
});

test('capture the delivered notification on a phone', async ({ page }) => {
  await page.setViewportSize(PHONE);
  await sendFromPicker(page, `${OUT}/22e-panel-mobile-notify-sent.png`);

  // The sidebar is a drawer on a phone: open it with the menu button first.
  await page.locator('ha-menu-button').first().click();
  await page.locator('ha-sidebar').getByText('Notifications', { exact: true }).click();
  await expect(page.getByText('Rinse the compost bin').first()).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('Due now.').first()).toBeVisible();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/22f-ha-mobile-notification-delivered.png` });
});
