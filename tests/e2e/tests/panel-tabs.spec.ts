import { test, expect, type Page } from '@playwright/test';
import { TASK } from '../fixture-ids';
import { PANEL_URL, callService, openSettingsSection, trackPanelErrors } from './helpers';

/**
 * Companion panel tabs, end to end against a real companion.
 *
 * The e2e container ships the `hk_demo_tab` stub (tests/integration/stubs). At setup it
 * serves `demo-tab.js` from its own static path and registers the `demo-tab` tab with
 * `panel_tabs.async_register_panel_tab`. The module defines `home-keeper-demo-tab`,
 * which shows `route.path` and has a button that calls `host.navigate('/sub')`.
 *
 * The seeded options hide the tab, so the other screenshots show the plain tab bar.
 * Each test here shows it and puts the seeded value back after.
 */
const SEEDED_HIDDEN = ['demo-tab'];

async function setHidden(hidden: string[]): Promise<void> {
  await callService('home_keeper', 'set_options', { hidden_panel_tabs: hidden });
}

async function gotoPanelPath(page: Page, path: string): Promise<void> {
  await page.goto(`${PANEL_URL}${path}`, { waitUntil: 'domcontentloaded' });
  await page.locator('home-keeper-panel').first().waitFor({ state: 'attached', timeout: 45_000 });
}

test.describe('Home Keeper panel — companion tabs', { tag: '@responsive' }, () => {
  test.afterEach(async () => {
    await setHidden(SEEDED_HIDDEN);
  });

  test('a deep link opens the tab, and the tab navigates through the host', async ({
    page,
  }) => {
    await setHidden([]);
    const errors = trackPanelErrors(page);
    await gotoPanelPath(page, '/demo-tab/x');
    const panel = page.locator('home-keeper-panel').first();
    const tab = panel.locator('home-keeper-demo-tab');

    await expect(tab.locator('#demo-path')).toHaveText('/x', { timeout: 30_000 });
    await expect(tab.locator('#demo-api')).toHaveText('1');
    // The tab bar on screen marks the tab as the current destination.
    await expect(
      panel
        .locator(
          '#tab-x-demo-tab[active]:visible, #mtab-x-demo-tab[aria-current="page"]:visible',
        )
        .first(),
    ).toBeVisible();

    await tab.locator('#demo-go').click();
    await expect(page).toHaveURL(/\/home-keeper\/demo-tab\/sub$/);
    await expect(tab.locator('#demo-path')).toHaveText('/sub');

    // Back moves inside the panel, to the path before.
    await page.goBack();
    await expect(page).toHaveURL(/\/home-keeper\/demo-tab\/x$/);
    await expect(tab.locator('#demo-path')).toHaveText('/x');

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a plain link and the host open Home Keeper pages with no page load', async ({
    page,
  }) => {
    await setHidden([]);
    await gotoPanelPath(page, '/demo-tab');
    const panel = page.locator('home-keeper-panel').first();
    const tab = panel.locator('home-keeper-demo-tab');
    await expect(tab.locator('#demo-path')).toHaveText('/', { timeout: 30_000 });
    // A page load would remove this value from the window.
    await page.evaluate(() => {
      (window as unknown as { hkNoReload: boolean }).hkNoReload = true;
    });
    const noReload = () =>
      page.evaluate(() => (window as unknown as { hkNoReload?: boolean }).hkNoReload === true);

    await tab.locator('#demo-link').click();
    await expect(page).toHaveURL(/\/home-keeper\/demo-tab\/linked$/);
    await expect(tab.locator('#demo-path')).toHaveText('/linked');
    expect(await noReload()).toBe(true);

    await tab.locator('#demo-appliances').click();
    await expect(page).toHaveURL(/\/home-keeper\/appliances$/);
    await expect(panel.locator('#add-btn, #add-fab').first()).toBeAttached();
    expect(await noReload()).toBe(true);

    // The host methods: back to the tab, then open a seeded task page.
    await page.goBack();
    await expect(tab.locator('#demo-path')).toHaveText('/linked');
    await tab.evaluate((el, id) => {
      (el as unknown as { host: { openTask(id: string): void } }).host.openTask(id);
    }, TASK.fridgeFilter);
    await expect(page).toHaveURL(new RegExp(`/home-keeper/tasks/${TASK.fridgeFilter}$`));
    expect(await noReload()).toBe(true);
  });

  test('the tab sits between Appliances and Settings', async ({ page }) => {
    await setHidden([]);
    await gotoPanelPath(page, '/tasks');
    const panel = page.locator('home-keeper-panel').first();
    const bar = panel.locator('ha-tab-group:visible, .hk-bottombar:visible').first();
    await expect(bar.locator('#tab-x-demo-tab, #mtab-x-demo-tab').first()).toHaveText(
      /Library/,
    );
    const ids = await bar
      .locator('ha-tab-group-tab, .hk-bottomtab')
      .evaluateAll((els) => els.map((el) => el.id.replace(/^m?tab-/, '')));
    expect(ids).toEqual(['tasks', 'appliances', 'x-demo-tab', 'settings']);

    await bar.locator('#tab-x-demo-tab, #mtab-x-demo-tab').first().click();
    await expect(page).toHaveURL(/\/home-keeper\/demo-tab$/);
    await expect(panel.locator('home-keeper-demo-tab #demo-path')).toHaveText('/');
  });

  test('a hidden tab is not in the tab bar, and its URL opens the task list', async ({
    page,
  }) => {
    await setHidden(['demo-tab']);
    await gotoPanelPath(page, '/demo-tab/x');
    const panel = page.locator('home-keeper-panel').first();
    await expect(page).toHaveURL(/\/home-keeper\/tasks$/, { timeout: 30_000 });
    await expect(panel.locator('#add-btn, #add-fab').first()).toBeAttached();
    await expect(panel.locator('#tab-x-demo-tab, #mtab-x-demo-tab')).toHaveCount(0);
    await expect(panel.locator('home-keeper-demo-tab')).toHaveCount(0);
  });

  test('Settings, Companions shows the Panel tab chip and the switch', async ({ page }) => {
    await setHidden(['demo-tab']);
    await gotoPanelPath(page, '/tasks');
    const panel = page.locator('home-keeper-panel').first();
    await openSettingsSection(panel, 'companions');
    const row = panel
      .locator('#hk-companions .hk-companion')
      .filter({ hasText: 'Demo library' });
    await expect(row.locator('ha-assist-chip.hk-comp-tab')).toHaveAttribute('label', 'Panel tab');
    await expect(row.locator('.hk-comp-tab-switch[data-panel-tab-id="demo-tab"] ha-form')).toBeAttached();

    // The switch writes the option, and the tab comes into the tab bar.
    await row.locator('.hk-comp-tab-switch ha-switch').first().click();
    await expect(panel.locator('#tab-x-demo-tab:visible, #mtab-x-demo-tab:visible').first()).toBeVisible({
      timeout: 30_000,
    });
  });
});
