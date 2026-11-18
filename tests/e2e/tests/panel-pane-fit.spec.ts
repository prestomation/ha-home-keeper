import { test, expect } from '@playwright/test';
import { callService, openAppliance, openPanel } from './helpers';
import { ASSET } from '../fixture-ids';

/**
 * The Appliances list pane fits the window.
 *
 * #551: with a long list, the pane is taller than the room that the page leaves for it
 * at the end of the page. The container pushed the pane up, so its first rows sat above
 * the window. The rows must be inside the window at the end of the page.
 */
const WINDOW = { width: 1015, height: 904 };
const EXTRA = Array.from({ length: 14 }, (_, i) => `E2E scroll appliance ${i + 1}`);

test.describe('Home Keeper — appliance list pane layout', () => {
  test.beforeAll(async () => {
    for (const name of EXTRA) await callService('home_keeper', 'add_asset', { name });
  });

  test.afterAll(async () => {
    const assets = (await callService('home_keeper', 'list_assets', {}, true)) as any;
    for (const a of assets?.assets ?? []) {
      if (EXTRA.includes(a.name)) await callService('home_keeper', 'delete_asset', { asset_id: a.id });
    }
  });

  test('a long list stays inside the window at the end of the page (#551)', async ({ page }) => {
    await page.setViewportSize(WINDOW);
    await openPanel(page);
    const panel = await openAppliance(page, ASSET.waterHeater);
    const pane = panel.locator('.hk-master');
    await expect(pane).toBeVisible();
    // The list must be longer than its pane, or the test proves nothing.
    expect(await pane.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);
    const box = (await pane.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, Math.min(box.y + 100, WINDOW.height - 50));
    for (let i = 0; i < 40; i++) {
      await page.mouse.wheel(0, 400);
      await page.waitForTimeout(40);
    }
    await page.waitForTimeout(300);
    const last = panel.locator('.hk-master ha-card').last();
    const r = (await last.boundingBox())!;
    const p = (await pane.boundingBox())!;
    expect(r.y + r.height, 'last row ends inside the window').toBeLessThanOrEqual(WINDOW.height);
    expect(r.y + r.height, 'last row ends inside the pane').toBeLessThanOrEqual(p.y + p.height + 1);
    expect(p.y, 'the pane top is not above the window').toBeGreaterThanOrEqual(0);
  });

  test('a press on a row keeps the list scroll and shows the open row (#586)', async ({ page }) => {
    await page.setViewportSize(WINDOW);
    await openPanel(page);
    const panel = await openAppliance(page, ASSET.waterHeater);
    const pane = panel.locator('.hk-master');
    await expect(pane).toBeVisible();
    expect(await pane.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);
    // Scroll the pane to its end, then press the last row.
    await pane.evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });
    const before = await pane.evaluate((el) => el.scrollTop);
    expect(before, 'the pane should be scrolled down').toBeGreaterThan(100);
    const last = panel.locator('.hk-master ha-card.hk-card').last();
    const name = (await last.locator('.hk-name').innerText()).trim();
    await last.locator('.detail-open').click();
    await expect(panel.locator('.hk-master ha-card.hk-selected .hk-name')).toHaveText(name);
    // Playwright may scroll a row a few pixels before the press, so allow some slack.
    const SLACK = 40;
    const after = await pane.evaluate((el) => el.scrollTop);
    expect(after, 'the press should not send the list to the top').toBeGreaterThanOrEqual(
      before - SLACK,
    );
    const row = (await panel.locator('.hk-master ha-card.hk-selected').boundingBox())!;
    const view = (await pane.boundingBox())!;
    expect(row.y, 'the open row starts inside the pane').toBeGreaterThanOrEqual(view.y - 1);
    expect(row.y + row.height, 'the open row ends inside the pane').toBeLessThanOrEqual(
      view.y + view.height + 1,
    );
  });
});
