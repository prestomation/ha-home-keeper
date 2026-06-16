import { Page, expect } from '@playwright/test';

/** Route for the Home Keeper sidebar panel. */
export const PANEL_URL = '/home-keeper';
/** YAML e2e dashboard rendering the native to-do + calendar cards. */
export const DASHBOARD = '/home-keeper-e2e/card';

/**
 * Navigate to the Home Keeper panel and wait for the custom element to upgrade.
 * The element renders into its shadow root, so we wait for it to be attached.
 */
export async function openPanel(page: Page): Promise<void> {
  await page.goto(PANEL_URL, { waitUntil: 'domcontentloaded' });
  await page.locator('home-keeper-panel').first().waitFor({ state: 'attached', timeout: 45_000 });
  // Wait for the panel to finish its first render (title appears in shadow DOM).
  await expect(page.locator('home-keeper-panel').first()).toBeVisible();
}

export async function openDashboard(page: Page): Promise<void> {
  await page.goto(DASHBOARD, { waitUntil: 'domcontentloaded' });
  await page.locator('hui-view, home-assistant').first().waitFor({ state: 'attached', timeout: 45_000 });
}

/**
 * Open the e2e dashboard and wait for the (first) custom Home Keeper card to
 * upgrade and render its first row. Returns the card locator. The card lives in
 * the dashboard's nested shadow DOM, which Playwright locators pierce.
 */
export async function openCardDashboard(page: Page) {
  // The card JS is an auto-registered extra module. On the very first dashboard
  // load of a run HA may not have finished loading it, so the custom element
  // doesn't upgrade in time; a reload (the module is warm by then) fixes it.
  // Retry a couple of times so the first test isn't flaky on a cold frontend.
  let lastErr: unknown;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt === 0) await openDashboard(page);
    else await page.reload({ waitUntil: 'domcontentloaded' });
    const card = page.locator('home-keeper-card').first();
    try {
      await card.waitFor({ state: 'attached', timeout: 20_000 });
      await expect(card.locator('.hk-row, .hk-empty').first()).toBeVisible({ timeout: 20_000 });
      return card;
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr;
}

/** Collect panel-relevant console/page errors. Attach BEFORE navigating. */
export function trackPanelErrors(page: Page): string[] {
  const errors: string[] = [];
  const isRelated = (s: string) => /home.?keeper/i.test(s);
  page.on('pageerror', (e) => {
    const text = `${e.message}\n${e.stack || ''}`;
    if (isRelated(text)) errors.push(`pageerror: ${text}`);
  });
  page.on('console', (msg) => {
    if (msg.type() === 'error' && isRelated(msg.text())) {
      errors.push(`console.error: ${msg.text()}`);
    }
  });
  return errors;
}
