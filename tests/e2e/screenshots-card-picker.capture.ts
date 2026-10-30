import { test, expect, Page } from '@playwright/test';
import { callService, deleteTask, listTasks } from './tests/helpers';
import { PHONE } from './viewports';

/**
 * Capture the Home Assistant card picker with the Home Keeper Tasks card in it, in a
 * home with many tasks (#524). Run via:
 *   SHOT_DIR=../../docs/images SHOT_NAME=picker-before npx playwright test \
 *     --config=screenshots-card-picker.config.ts
 */
const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
const NAME = process.env.SHOT_NAME || 'picker';
const COUNT = Number(process.env.TASK_COUNT || 200);
const DASH = 'hk-picker';

async function ws(page: Page, msg: Record<string, unknown>): Promise<any> {
  return page.evaluate(
    (m) => (document.querySelector('home-assistant') as any).hass.callWS(m),
    msg,
  );
}

/** Open the card picker on the edit dashboard, search for the card and shoot the dialog. */
async function shootPicker(page: Page, file: string): Promise<void> {
  await page.goto(`/${DASH}/0`, { waitUntil: 'domcontentloaded' });
  if ((page.viewportSize()?.width ?? 1280) < 700) {
    // On a phone the Edit button sits in the overflow menu at the top right.
    await page.locator('hui-root').waitFor({ state: 'attached', timeout: 30_000 });
    await page.waitForTimeout(2000);
    const width = page.viewportSize()!.width;
    await page.mouse.click(width - 28, 28);
    await page.getByText(/edit dashboard/i).first().click({ timeout: 15_000 });
  } else {
    await page.locator('hui-root ha-icon-button').last().click({ timeout: 30_000 });
  }
  await page.getByText(/add card/i).first().click({ timeout: 15_000 });
  await page.getByText('By card', { exact: true }).first().click({ timeout: 15_000 });
  const started = Date.now();
  await page.getByPlaceholder(/search cards/i).first().fill('Home Keeper');
  const card = page.locator('hui-card-picker home-keeper-card').first();
  await expect(card.locator('.hk-row').first()).toBeVisible({ timeout: 120_000 });
  const ms = Date.now() - started;
  const rows = await card.locator('.hk-row').count();
  const height = await card.evaluate((el) => Math.round(el.getBoundingClientRect().height));
  console.log(`PICKER ${file}: ${rows} rows, card ${height}px high, ready in ${ms} ms`);
  // Scroll to the end of the card, so the shot shows where the preview stops.
  await card.locator('.hk-row, .hk-more').last().scrollIntoViewIfNeeded();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/${file}` });
}

test('card picker preview with many tasks', async ({ page }) => {
  test.setTimeout(600_000);
  const made: string[] = [];
  try {
    for (let i = 0; i < COUNT; i++) {
      const r = await callService(
        'home_keeper',
        'add_task',
        { name: `Picker task ${i + 1}`, recurrence_type: 'floating', interval: 1, unit: 'months' },
        true,
      );
      made.push(r.task_id);
    }
    await page.goto('/lovelace/0', { waitUntil: 'domcontentloaded' });
    await page.locator('home-assistant').waitFor({ state: 'attached' });
    await page.waitForTimeout(3000);
    const dashes = await ws(page, { type: 'lovelace/dashboards/list' });
    if (!dashes.some((d: any) => d.url_path === DASH)) {
      await ws(page, {
        type: 'lovelace/dashboards/create',
        url_path: DASH,
        mode: 'storage',
        title: 'Picker',
        require_admin: true,
        show_in_sidebar: false,
      });
    }
    await ws(page, {
      type: 'lovelace/config/save',
      url_path: DASH,
      config: { views: [{ title: 'Picker', cards: [{ type: 'markdown', content: 'Hello' }] }] },
    });
    await shootPicker(page, `524-card-picker-${NAME}.png`);
    await page.setViewportSize(PHONE);
    await shootPicker(page, `524b-card-picker-mobile-${NAME}.png`);
  } finally {
    await Promise.all(made.map(deleteTask));
  }
  expect((await listTasks()).length).toBeGreaterThan(0);
});
