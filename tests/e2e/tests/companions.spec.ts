import { test, expect } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';

/**
 * Settings → Companions, exercised end-to-end against real installed companions.
 *
 * The e2e container ships two stub companion integrations (tests/integration/stubs,
 * bind-mounted + installed via seeded config entries):
 *   - `pawsistant` self-registers on setup via `home_keeper.register_companion`
 *     (the push path), so it surfaces as a *connected* companion.
 *   - `home_keeper_battery_notes` is in Home Keeper's companion catalog, so simply
 *     being installed makes Home Keeper detect it as connected (the pull path).
 *
 * This locks the rendered Companions surface (previously only the pure
 * `build_companion_list` logic was unit-tested) so it can't silently regress.
 */
test.describe('Home Keeper panel — companions', () => {
  test('Settings → Companions lists the connected stub companions', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    await panel.locator('#tab-settings').click();
    const companions = panel.locator('#hk-companions');
    await expect(companions).toBeVisible();

    // Both stubs render as connected, each with a working Configure action. The
    // name lives in `.hk-companion-name` alongside the connected status chip.
    await expect(
      companions.locator('.hk-companion-name', { hasText: 'Pawsistant' }),
    ).toBeVisible();
    await expect(
      companions.locator('.hk-companion-name', { hasText: 'Battery Notes' }),
    ).toBeVisible();
    await expect(companions.locator('.hk-comp-configure')).toHaveCount(2);
    // The push-registered companion carries its docs link from the descriptor.
    await expect(companions.locator('.hk-comp-docs').first()).toBeVisible();

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a connected companion exposes a Configure deep-link', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#tab-settings').click();

    // Pawsistant's Configure button targets its own integration domain.
    const configure = panel
      .locator('.hk-comp-configure[data-domain="pawsistant"]')
      .first();
    await expect(configure).toBeVisible();
  });
});
