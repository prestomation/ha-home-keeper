import { test, expect, type Locator, type Page } from '@playwright/test';
import { TASK } from '../fixture-ids';

/**
 * The Done menu under a "glass" theme (#497).
 *
 * Themes such as Liquid Glass Tinted put `backdrop-filter` (and a clip) on every
 * `ha-card`. Each card then paints as its own layer, so a menu that is a child of one
 * card is covered by the card after it, and a clip on the card cuts it off. The
 * stock theme has neither, which is why only some users saw it. The theme itself is
 * not installed here: these styles are the part of it that matters.
 */
const GLASS = `
  ha-card {
    backdrop-filter: blur(20px) saturate(1.6);
    -webkit-backdrop-filter: blur(20px) saturate(1.6);
    overflow: hidden;
    background: rgba(255, 255, 255, 0.35);
  }
`;

async function gotoPanel(page: Page, path: string) {
  await page.goto(`/home-keeper${path}`, { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  await panel.locator('ha-card').first().waitFor({ state: 'attached' });
  await panel.evaluate((el, css) => {
    const style = document.createElement('style');
    style.textContent = css;
    el.shadowRoot!.appendChild(style);
  }, GLASS);
  return panel;
}

/** Whether the real hit target at 5 points of the menu is the menu itself. */
async function menuIsOnTop(panel: Locator, menu: Locator): Promise<boolean[]> {
  const box = (await menu.boundingBox())!;
  const points = [
    [0.5, 0.5],
    [0.15, 0.15],
    [0.85, 0.15],
    [0.15, 0.85],
    [0.85, 0.85],
  ].map(([fx, fy]) => [box.x + box.width * fx, box.y + box.height * fy]);
  return panel.evaluate(
    (el, pts) =>
      (pts as number[][]).map(([x, y]) => {
        const hit = el.shadowRoot!.elementFromPoint(x, y);
        return !!hit?.closest('.hk-defer-menu');
      }),
    points,
  );
}

test.describe('Home Keeper panel — Done menu under a glass theme', { tag: '@responsive' }, () => {
  test('the menu on the task page is not clipped by its card', async ({ page }) => {
    const panel = await gotoPanel(page, `/tasks/${TASK.waterFilter}`);
    await panel.locator('.hk-detail-actions .hk-split-caret').click();
    const menu = panel.locator('.hk-detail-actions .hk-defer-menu');
    await expect(menu).toBeVisible();
    expect(await menuIsOnTop(panel, menu)).toEqual([true, true, true, true, true]);
  });

  test('the menu on a list row is not covered by the row below', async ({ page }) => {
    const panel = await gotoPanel(page, '/tasks');
    const row = panel.locator('ha-card.hk-card').filter({ has: page.locator('.hk-split-caret') }).first();
    await expect(row).toBeVisible();
    await row.locator('.hk-split-caret').first().click();
    const menu = row.locator('.hk-defer-menu').first();
    await expect(menu.locator('.hk-defer-skip')).toBeVisible();
    expect(await menuIsOnTop(panel, menu)).toEqual([true, true, true, true, true]);
  });
});
