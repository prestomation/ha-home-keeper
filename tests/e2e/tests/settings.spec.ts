import { test, expect } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';

test.describe('Home Keeper panel — Settings tab', () => {
  test('Settings tab renders the options form and deep-links', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    await panel.locator('#tab-settings').click();
    // The ha-form mirror of the options flow is rendered. The problem-sensor card
    // renders as two forms — the sync switch, then the exclusions indented behind
    // it — so both halves have to be on screen for the card to be usable.
    await expect(panel.locator('#hk-settings ha-form')).toHaveCount(2);
    await expect(panel.locator('#hk-settings ha-form').first()).toBeVisible();
    await expect(panel.locator('#hk-settings ha-form').last()).toBeVisible();
    // …and so is the Shopping list card, which is where the buy-reminder mirror
    // is turned on.
    await expect(panel.locator('#hk-settings-shopping ha-form')).toBeVisible();
    // …and the Profiles card, which is where a saved filter is edited — and, inside
    // each one, the to-do list it syncs its tasks onto. With no profiles saved the
    // card is an empty state plus its Add button, so the button is what proves it
    // rendered either way.
    await expect(panel.locator('#hk-profiles')).toBeVisible();
    await expect(panel.locator('#hk-profile-add')).toBeVisible();
    // Deep-linked: the panel URL reflects the settings view (so Back/Forward work).
    await expect.poll(() => page.url()).toContain('/home-keeper/settings');

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a settings detail URL deep-links straight to the Settings tab', async ({ page }) => {
    await page.goto('/home-keeper/settings');
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('#hk-settings ha-form').first()).toBeVisible();
  });

  test('the problem-sensor toggle explains what clears a synced task', async ({ page }) => {
    // The consequences of the toggle aren't guessable from its label: such a task
    // clears only when its source integration resolves the problem, so its reminders
    // offer Snooze rather than Mark done. The helper says so in place.
    await page.goto('/home-keeper/settings');
    const panel = page.locator('home-keeper-panel').first();
    const card = panel.locator('#hk-settings');
    await expect(card.locator('ha-form').first()).toBeVisible();
    await expect(card).toContainText(/clears only when the source integration/i);
    await expect(card).toContainText(/offer Snooze in place of Mark done/i);
  });
});
