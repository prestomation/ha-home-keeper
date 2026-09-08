/**
 * Focused screenshot capture for the Profile delete dialogs.
 *
 * Deleting a Profile used to happen on the press, and a notification that named the
 * Profile then kept an id with nothing behind it and sent nothing, with no signal.
 * Delete now opens one of two dialogs — a blocking notice naming the notifications
 * when any hold the Profile, and an ordinary confirmation when none do — and these
 * are the two shots for it, at desktop and phone width.
 *
 * Standalone rather than a step in ``screenshots.capture.ts``: that harness walks
 * every documented surface in one test, so a single earlier step going stale takes
 * the whole run with it. This seeds its own Profile and notification over the
 * service, photographs them, then restores the options it found — same contract as
 * ``screenshots-declarative.capture.ts``.
 *
 * The scrim is `position: fixed` on `document.body`, so both shots are **viewport**
 * captures: a `fullPage: true` shot grows the page around the dialog and photographs
 * the settings cards behind it.
 *
 * Run:
 *   CHROMIUM_EXEC=$(ls /opt/pw-browsers/chromium-*\/chrome-linux/chrome | head -1) \
 *     SHOT_DIR=../../docs/images \
 *     npx playwright test --config=screenshots-profile-delete.config.ts
 */
import { test, expect } from '@playwright/test';
import { callService, openPanel, openSettingsSection } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

const FILTER = { status: 'overdue', labels: [], areas: [], devices: [] };

const HELD = { id: 'shot_held', name: 'My chores', filter: FILTER };
const FREE = { id: 'shot_free', name: 'Garden', filter: FILTER };
const HOLDER = {
  id: 'shot_notify',
  name: 'Walk my chores',
  profile_id: 'shot_held',
  targets: [],
  actions: ['complete'],
  style: 'walk',
  snooze_hours: 24,
  channel: '',
  urgency: 'normal',
  auto: { overdue: false, due_soon: false },
};

test('capture the profile delete dialogs', async ({ page }) => {
  await callService('home_keeper', 'set_options', {
    profiles: [HELD, FREE],
    notifications: [HOLDER],
  });

  try {
    const panel = page.locator('home-keeper-panel').first();

    const openProfile = async (name: string) => {
      const row = panel
        .locator('#hk-profiles .hk-item-card')
        .filter({ hasText: name })
        .first();
      // A profile row holds a *second* `.hk-item-card` — its sync group — so this
      // takes the row's own header rather than both.
      const header = row.locator('> .hk-item-header');
      if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click();
      return row;
    };

    // 58. Delete saying no. "Walk my chores" names this Profile, so removing it would
    // leave that notification pointing at nothing. The dialog names what is in the way
    // and offers only Close, because the backend refuses the save either way.
    await openPanel(page);
    await openSettingsSection(panel, 'profiles');
    await expect(panel.locator('#hk-profiles')).toBeVisible();
    let row = await openProfile('My chores');
    await row.locator('> .hk-item-body .hk-notify-delete').click();
    const scrim = page.locator('.hk-confirm-scrim');
    await expect(scrim).toBeVisible();
    await expect(scrim).toContainText('Walk my chores');
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/58-panel-profile-delete-blocked.png` });
    await scrim.locator('ha-button').click();
    await expect(scrim).toBeHidden();

    // 58b. The other half: a Profile nothing uses still asks first. Delete used to
    // take the row on the press, with no question.
    row = await openProfile('Garden');
    await row.locator('> .hk-item-body .hk-notify-delete').click();
    await expect(scrim).toBeVisible();
    await expect(scrim.locator('ha-button')).toHaveCount(2);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/58b-panel-profile-delete-confirm.png` });
    await scrim.locator('ha-button', { hasText: 'Cancel' }).click();
    await expect(scrim).toBeHidden();

    // 58c. The blocking dialog on a phone, where it has to hold its own against a
    // 390px screen and the Settings tab opens on an index rather than the sections.
    await page.setViewportSize({ width: 390, height: 844 });
    await openPanel(page);
    await openSettingsSection(panel, 'profiles');
    await expect(panel.locator('#hk-profiles')).toBeVisible();
    row = await openProfile('My chores');
    await row.locator('> .hk-item-body .hk-notify-delete').click();
    await expect(scrim).toBeVisible();
    await expect(scrim).toContainText('Walk my chores');
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/58c-panel-mobile-profile-held.png` });
    await scrim.locator('ha-button').click();
    await expect(scrim).toBeHidden();
    await page.setViewportSize({ width: 1280, height: 720 });
  } finally {
    // The seeded container has no profiles or notifications of its own, so this is
    // what it started with. Both lists in one call: clearing the profile alone is
    // exactly the save the new guard refuses.
    await callService('home_keeper', 'set_options', { profiles: [], notifications: [] });
  }
});
