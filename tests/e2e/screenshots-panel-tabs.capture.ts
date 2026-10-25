/**
 * Focused screenshot capture for the companion panel tabs, at desktop and phone width.
 *
 * The `hk_demo_tab` stub (tests/integration/stubs) registers a Library tab. The seeded
 * options hide it, so the other harnesses show the plain tab bar. This harness shows
 * the tab, takes the shots, and puts the seeded value back.
 *
 * Shots:
 *   79  the panel with the companion tab open
 *   79b Settings, Companions: the companion row with the Panel tab chip and its switch
 *   79c and 79d: the same 2 at phone width
 *
 * Run:
 *   CHROMIUM_EXEC=$(ls /opt/pw-browsers/chromium-*\/chrome-linux/chrome | head -1) \
 *     SHOT_DIR=../../docs/images \
 *     npx playwright test --config=screenshots-panel-tabs.config.ts
 */
import { test, expect, type Locator, type Page } from '@playwright/test';
import { PANEL_URL, callService, openSettingsSection } from './tests/helpers';
import { PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

async function openTab(page: Page, panel: Locator): Promise<void> {
  await page.goto(`${PANEL_URL}/demo-tab/books`, { waitUntil: 'domcontentloaded' });
  await expect(panel.locator('home-keeper-demo-tab #demo-path')).toHaveText('/books', {
    timeout: 30_000,
  });
  await page.mouse.move(0, 0);
  await page.waitForTimeout(600);
}

async function companionRow(page: Page, panel: Locator): Promise<Locator> {
  await page.goto(`${PANEL_URL}/tasks`, { waitUntil: 'domcontentloaded' });
  await openSettingsSection(panel, 'companions');
  const row = panel.locator('#hk-companions .hk-companion').filter({ hasText: 'Demo library' });
  await expect(row.locator('.hk-comp-tab-switch ha-form')).toBeAttached();
  await row.scrollIntoViewIfNeeded();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(600);
  return row;
}

test('capture the companion panel tab', async ({ page }) => {
  await callService('home_keeper', 'set_options', { hidden_panel_tabs: [] });
  try {
    const panel = page.locator('home-keeper-panel').first();

    await openTab(page, panel);
    await page.screenshot({ path: `${OUT}/79-panel-companion-tab.png` });

    await companionRow(page, panel);
    await panel.locator('#hk-companions').screenshot({
      path: `${OUT}/79b-panel-companion-tab-settings.png`,
    });

    await page.setViewportSize(PHONE);

    await openTab(page, panel);
    await page.screenshot({ path: `${OUT}/79c-panel-mobile-companion-tab.png` });

    // The whole card, so the shot shows that the Configure buttons line up.
    await companionRow(page, panel);
    await panel.locator('#hk-companions').screenshot({
      path: `${OUT}/79d-panel-mobile-companion-tab-settings.png`,
    });
  } finally {
    await callService('home_keeper', 'set_options', { hidden_panel_tabs: ['demo-tab'] });
  }
});
