import { test, expect, Page } from '@playwright/test';

/**
 * Block service workers. A fresh browser context loads Home Assistant, installs its
 * service worker, and the page then reloads by itself about 8 seconds after the first
 * load (seen on /home-keeper, /lovelace/0 and /profile/general, with no test action).
 * A slow runner moves a test step across that moment: an `evaluate` dies with
 * "Execution context was destroyed", a new document has no `hass` yet, and an open
 * row or dialog is gone. With the worker blocked, no reload happens.
 */
test.use({ serviceWorkers: 'block' });

/**
 * #524: the card picker of the dashboard editor draws the card as a preview, so the
 * card must show only a few rows there. The seeded home has more than 3 tasks.
 */
const DASH = 'hk-picker-spec';

/**
 * Wait until the Home Assistant frontend has a live connection. The `home-assistant`
 * element is in the DOM long before its `hass` object exists, and the page can still
 * navigate while it starts. `waitForFunction` runs again in each new page context, so
 * it survives a navigation that a bare `evaluate` does not.
 */
async function hassReady(page: Page): Promise<void> {
  await page.waitForLoadState('load');
  await page.waitForFunction(
    () => {
      const hass = (document.querySelector('home-assistant') as any)?.hass;
      return Boolean(hass?.connection && typeof hass.callWS === 'function');
    },
    undefined,
    { timeout: 45_000 },
  );
}

async function ws(page: Page, msg: Record<string, unknown>): Promise<any> {
  await hassReady(page);
  return page.evaluate(
    (m) => (document.querySelector('home-assistant') as any).hass.callWS(m),
    msg,
  );
}

test.describe('Home Keeper card — card picker preview', () => {
  test.afterEach(async ({ page }) => {
    await page.goto('/lovelace/0', { waitUntil: 'domcontentloaded' });
    await hassReady(page);
    const dashes = await ws(page, { type: 'lovelace/dashboards/list' });
    const hit = dashes.find((d: any) => d.url_path === DASH);
    if (hit) await ws(page, { type: 'lovelace/dashboards/delete', dashboard_id: hit.id });
  });

  test('the picker preview shows at most 3 tasks', async ({ page }) => {
    await page.goto('/lovelace/0', { waitUntil: 'domcontentloaded' });
    await hassReady(page);
    await ws(page, {
      type: 'lovelace/dashboards/create',
      url_path: DASH,
      mode: 'storage',
      title: 'Picker spec',
      require_admin: true,
      show_in_sidebar: false,
    });
    await ws(page, {
      type: 'lovelace/config/save',
      url_path: DASH,
      config: { views: [{ title: 'Picker', cards: [{ type: 'markdown', content: 'Hello' }] }] },
    });

    await page.goto(`/${DASH}/0`, { waitUntil: 'domcontentloaded' });
    await page.locator('hui-root ha-icon-button').last().click({ timeout: 30_000 });
    await page.getByText(/add card/i).first().click({ timeout: 15_000 });
    await page.getByText('By card', { exact: true }).first().click({ timeout: 15_000 });
    await page.getByPlaceholder(/search cards/i).first().fill('Home Keeper');

    const card = page.locator('hui-card-picker home-keeper-card').first();
    await expect(card.locator('.hk-row').first()).toBeVisible({ timeout: 60_000 });
    await expect(card.locator('.hk-row')).toHaveCount(3);
    await expect(card.locator('.hk-more')).toBeVisible();
  });
});
