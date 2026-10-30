/**
 * One-off screenshot capture for the notification "Send to" picker (#521) — not part of
 * the e2e suite (the filename is not *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-notify-targets.config.ts
 *
 * The picker lists `persistent_notification` next to the phones. The container has no
 * phone, so the list in the shot holds that one service, which is what a user without a
 * phone sees.
 */
import { expect, test } from '@playwright/test';
import { callService, openPanel } from './tests/helpers';
import { PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/hk-shots';

let savedProfiles: unknown[] = [];

test.beforeAll(async () => {
  savedProfiles = (await callService('home_keeper', 'list_profiles', {}, true)).profiles ?? [];
  await callService('home_keeper', 'set_options', {
    profiles: [
      {
        id: 'shot-targets-profile',
        name: 'My chores',
        filter: { status: 'all' },
      },
    ],
    notifications: [
      {
        id: 'shot-targets-notify',
        name: 'Walk my chores',
        profile_id: 'shot-targets-profile',
        targets: [],
        actions: ['complete', 'snooze', 'open'],
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
});

test.afterAll(async () => {
  // The seed fixture holds no notification, so an empty list is the original state.
  await callService('home_keeper', 'set_options', { profiles: savedProfiles, notifications: [] });
});

test('capture the Send to picker', async ({ page }) => {
  const open = async () => {
    await openPanel(page);
    await page.goto('/home-keeper/settings/notifications', { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    const card = panel.locator('#hk-notifications');
    await expect(card).toBeVisible({ timeout: 30_000 });
    await card.locator('.hk-item-header').first().click();
    const form = card.locator('.hk-item-body > ha-form').nth(1);
    await expect(form).toBeVisible({ timeout: 20_000 });
    await expect(form).toContainText('Send to');
    return { card, form };
  };

  const { card, form } = await open();
  await form.locator('ha-select').first().click();
  await expect(page.getByText('persistent_notification').first()).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/22d-panel-notify-targets.png` });
  await page.keyboard.press('Escape');
  void card;

  await page.setViewportSize(PHONE);
  const phone = await open();
  await phone.form.locator('ha-select').first().click();
  await expect(page.getByText('persistent_notification').first()).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/22d-panel-mobile-notify-targets.png` });
});
