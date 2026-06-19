import { test, expect } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';

test.describe('Home Keeper panel — synced problem task', () => {
  test('the Tasks-list Done is disabled and explains (not completes) on click', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    // The synced "Sump pump problem" task is armed (sensor reports a problem), so it
    // shows in the Tasks list — not just on its detail page.
    const card = panel.locator('.hk-card', { hasText: 'Sump pump problem' });
    await expect(card).toBeVisible();

    // Its Done is a *disabled* (greyed) button, not a working complete action.
    const blocked = card.locator('.done-blocked-wrap');
    await expect(blocked).toBeVisible();
    await expect(blocked.locator('ha-button[disabled]')).toHaveCount(1);

    // Clicking it surfaces the explanation toast …
    await blocked.click();
    await expect(
      page.getByText(/clears automatically once the originating integration/i),
    ).toBeVisible();
    // … and does NOT complete the task — its card is still in the list afterwards.
    await expect(card).toBeVisible();

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
