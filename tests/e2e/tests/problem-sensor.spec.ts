import { test, expect } from '@playwright/test';
import { callService, openPanel, trackPanelErrors } from './helpers';

test.describe('Home Keeper panel — synced problem task', () => {
  test('the Tasks-list Done is replaced by a caption and explains (not completes) on click', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    // The synced "Sump pump problem" task is armed (sensor reports a problem), so it
    // shows in the Tasks list — not just on its detail page.
    const card = panel.locator('.hk-card', { hasText: 'Sump pump problem' });
    await expect(card).toBeVisible();

    // Instead of a working Done, it shows a muted "Clears automatically" caption.
    const blocked = card.locator('.hk-auto-clear');
    await expect(blocked).toBeVisible();
    await expect(blocked).toContainText(/clears automatically/i);

    // Clicking it surfaces the explanation toast … scoped to the toast's visible
    // `.message` span, not the page-wide text search, which also matches HA's hidden
    // `assistive-message` echo of the same text (rendered for screen readers) and
    // trips Playwright's strict-mode "multiple elements matched" check.
    await blocked.click();
    const toast = page.locator('.message');
    await expect(toast).toBeVisible();
    await expect(toast).toContainText(/clears automatically once the originating integration/i);
    // … and does NOT complete the task — its card is still in the list afterwards.
    await expect(card).toBeVisible();

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a synced task still shows when the list is filtered by a Profile (#248)', async ({
    page,
  }) => {
    // The profile matcher used to drop problem-sensor tasks outright, under every
    // status — so picking any Profile made every synced problem vanish from the list.
    // The plain (unfiltered) list never showed the bug, which is why it went unnoticed.
    await callService('home_keeper', 'set_options', {
      profiles: [
        {
          id: 'e2e_everything',
          name: 'Everything',
          filter: { status: 'all', labels: [], areas: [], devices: [] },
        },
      ],
    });
    try {
      const errors = trackPanelErrors(page);
      await openPanel(page);
      const panel = page.locator('home-keeper-panel').first();
      const card = panel.locator('.hk-card', { hasText: 'Sump pump problem' });
      await expect(card).toBeVisible();

      const picker = panel.locator('select[data-profile-filter]');
      await expect(picker).toBeVisible();
      await picker.selectOption('e2e_everything');

      // Still listed under the Profile, with its "Clears automatically" caption.
      await expect(card).toBeVisible();
      await expect(card.locator('.hk-auto-clear')).toBeVisible();

      expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
    } finally {
      // The panel remembers the picked profile in localStorage; clearing the option
      // makes the panel fall back to no filter, so the next spec starts clean.
      await callService('home_keeper', 'set_options', { profiles: [] });
    }
  });
});
