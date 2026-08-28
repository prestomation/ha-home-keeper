import { test, expect, Page } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';

/**
 * Settings at phone width is a section index that opens one section at a time — a
 * screen with no room for a rail beside six expanded sections has no room for the six
 * sections either.
 *
 * The split is entirely CSS: all three parts (rail, index, sections) are rendered at
 * every width, the layout carries which section the URL names, and the media query
 * picks. That is what these tests are really guarding — the rest of the suite runs at
 * desktop width and would never notice the phone rules regressing.
 */
const PHONE = { width: 390, height: 844 };

/** Open the panel with a phone-sized viewport, on the Settings tab. */
async function openSettingsOnPhone(page: Page) {
  await page.setViewportSize(PHONE);
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await panel.locator('#mtab-settings').click();
  return panel;
}

test.describe('Home Keeper panel — Settings on a phone', () => {
  test('opens on an index naming every section and what it is set to', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await openSettingsOnPhone(page);

    // Six rows, one per section, and the rail they replace is not on screen.
    const rows = panel.locator('.hk-index-row');
    await expect(rows).toHaveCount(6);
    await expect(panel.locator('.hk-settings-rail')).toBeHidden();
    // The row states the section's current value, so the index answers "is the mirror
    // on" without opening anything — the job the rail does on a wide screen.
    await expect(panel.locator('.hk-index-row[data-section="shopping"]')).toContainText(
      /not mirrored/i,
    );
    // Nothing scrolls sideways: every row is inside the viewport it is drawn in.
    const overflow = await panel.evaluate((el) => {
      const doc = el.shadowRoot?.querySelector('.hk-wrap') as HTMLElement | null;
      return doc ? doc.scrollWidth - doc.clientWidth : -1;
    });
    expect(overflow).toBeLessThanOrEqual(0);

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a row opens that section alone, and Back returns to the index', async ({ page }) => {
    const panel = await openSettingsOnPhone(page);
    await panel.locator('.hk-index-row[data-section="problem"]').click();

    // The section is a URL of its own, so it can be linked to and Back leaves it.
    await expect.poll(() => page.url()).toContain('/home-keeper/settings/problem');
    await expect(panel.locator('#hk-settings')).toBeVisible();
    await expect(panel.locator('.hk-settings-backbar')).toBeVisible();
    // Its five siblings are off the screen — that is the point of the split.
    await expect(panel.locator('#hk-settings-shopping')).toBeHidden();
    await expect(panel.locator('#hk-profiles')).toBeHidden();
    await expect(panel.locator('.hk-index-row').first()).toBeHidden();

    // The back arrow pops the pushed entry rather than leaving the panel.
    await panel.locator('#settings-back').click();
    await expect(panel.locator('.hk-index-row').first()).toBeVisible();
    await expect.poll(() => page.url()).toMatch(/\/home-keeper\/settings\/?$/);

    // …and so does the browser's own Back, which is the same history entry.
    await panel.locator('.hk-index-row[data-section="profiles"]').click();
    await expect(panel.locator('#hk-profiles')).toBeVisible();
    await page.goBack();
    await expect(panel.locator('.hk-index-row').first()).toBeVisible();
  });

  test('a section URL deep-links straight to that section', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await page.goto('/home-keeper/settings/notifications');
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('#hk-notifications')).toBeVisible();
    await expect(panel.locator('#hk-settings-general')).toBeHidden();

    // Nothing was pushed to go back to, so the back arrow navigates to the index
    // outright rather than ejecting from the panel.
    await panel.locator('#settings-back').click();
    await expect(panel.locator('.hk-index-row').first()).toBeVisible();
  });

  test('an unknown section falls back to the index rather than a blank page', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await page.goto('/home-keeper/settings/nonsense');
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('.hk-index-row')).toHaveCount(6);
  });

  test('the same URL on a wide screen is the whole page, with the rail', async ({ page }) => {
    // The split is CSS, so widening the window is the whole of the desktop story: the
    // rail comes back, every section shows, and the index goes away.
    await page.setViewportSize(PHONE);
    await page.goto('/home-keeper/settings/problem');
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('#hk-settings-general')).toBeHidden();

    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(panel.locator('.hk-settings-rail')).toBeVisible();
    await expect(panel.locator('#hk-settings-general')).toBeVisible();
    await expect(panel.locator('#hk-settings')).toBeVisible();
    await expect(panel.locator('.hk-index-row').first()).toBeHidden();
    // The rail marks the section the URL names. `page` rather than `true` because
    // these entries are real URLs, and it is what a screen reader renders usefully.
    await expect(panel.locator('.hk-rail-link[data-section="problem"]')).toHaveAttribute(
      'aria-current',
      'page',
    );
  });
});
