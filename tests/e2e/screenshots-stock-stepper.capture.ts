/**
 * One-off screenshot capture for the stock stepper that merges taps. Not part of the
 * e2e suite (the filename is not *.spec.ts). Run:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-stock-stepper.capture.ts \
 *     --config=screenshots-stock-stepper.config.ts
 *
 * The appliance page with a stock stepper: 1 tap starts a save that the capture holds
 * back, and 2 more taps show the merged count while the save runs. Desktop and phone.
 */
import { expect, test, type Locator, type Page } from '@playwright/test';
import { PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

/** Hold back each stock save for *ms*, so the shot shows the stepper while it runs. */
async function slowStockSaves(panel: Locator, ms: number): Promise<void> {
  await panel.evaluate((p: any, delay: number) => {
    const conn = p._hass.connection;
    if (conn.__hkSlow) return;
    conn.__hkSlow = true;
    const send = conn.sendMessagePromise.bind(conn);
    (window as any).__hkDeltas = [];
    conn.sendMessagePromise = (msg: { type: string; delta?: number }) => {
      if (msg.type !== 'home_keeper/adjust_part_stock') return send(msg);
      (window as any).__hkDeltas.push(msg.delta);
      return new Promise((r) => setTimeout(r, delay)).then(() => send(msg));
    };
  }, ms);
}

async function shoot(page: Page, panel: Locator, name: string): Promise<void> {
  await page.evaluate(() => ((window as any).__hkDeltas = []));
  const box = panel.locator('.hk-stock[data-part]').first();
  await expect(box).toBeVisible();
  const before = Number(await box.locator('.hk-stock-input').inputValue());
  const inc = box.locator('.hk-stock-inc');
  await inc.click();
  // The first save starts and is held back. The next taps come while it runs.
  await page.waitForTimeout(500);
  await inc.click();
  await inc.click();
  const now = panel.locator('.hk-stock[data-part]').first();
  await expect(now.locator('.hk-stock-input')).toHaveValue(String(before + 3));
  await expect(now).toHaveAttribute('data-busy', '');
  await now.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/${name}` });
  // The saves end, and the store holds the merged count.
  await expect(panel.locator('.hk-stock[data-part]').first()).not.toHaveAttribute('data-busy', '', {
    timeout: 30_000,
  });
  await expect(panel.locator('.hk-stock[data-part]').first().locator('.hk-stock-input')).toHaveValue(
    String(before + 3),
  );
  // 1 save for the first tap, and 1 save for the 2 taps that came while it ran.
  expect(await page.evaluate(() => (window as any).__hkDeltas)).toEqual([1, 2]);
}

test('capture the stock stepper while a save runs', async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto('/home-keeper/appliances', { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  await expect.poll(() => panel.evaluate((p: any) => p._loaded), { timeout: 45_000 }).toBe(true);
  const id = await panel.evaluate(
    (p: any) => p._assets.find((a: any) => (a.parts ?? []).some((x: any) => x.stock != null))?.id,
  );
  expect(id).toBeTruthy();
  await page.goto(`/home-keeper/appliances/${id}`, { waitUntil: 'domcontentloaded' });
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  await expect(panel.locator('.hk-stock[data-part]').first()).toBeVisible({ timeout: 45_000 });
  await slowStockSaves(panel, 4000);
  await shoot(page, panel, 'stock-stepper-merged.png');

  await page.setViewportSize(PHONE);
  await page.waitForTimeout(500);
  await slowStockSaves(panel, 4000);
  await shoot(page, panel, 'stock-stepper-mobile-merged.png');
});
