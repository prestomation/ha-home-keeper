import { test, expect, Locator, Page } from '@playwright/test';
import { openCardDashboard } from './tests/helpers';

/**
 * One-off capture of the Home Keeper dashboard card for the README / PR. Run via:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     screenshots-card.capture.ts --config=screenshots-card.config.ts
 * Kept out of the *.spec.ts suite so it doesn't run as a normal test.
 */
const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

async function fillText(scope: Locator, nth: number, value: string): Promise<void> {
  await scope.locator('ha-selector-text').nth(nth).locator('input, textarea').fill(value);
}

/**
 * Clip a tight screenshot of a card's inner `ha-card`. We clip by bounding box at
 * scroll-0 (rather than element.screenshot, which auto-scrolls and lets HA's
 * sticky view header overlay the card's own header) with a tall viewport so the
 * whole card fits above the fold.
 */
async function shotCard(page: Page, card: Locator, path: string): Promise<void> {
  const box = await card.locator('ha-card').first().boundingBox();
  if (!box) throw new Error(`no bounding box for ${path}`);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path, clip: box });
}

test('capture Home Keeper card screenshots', async ({ page }) => {
  // Tall viewport so even the grouped card fits in one clip.
  await page.setViewportSize({ width: 1280, height: 1800 });
  const card = await openCardDashboard(page);
  await expect(card.locator('.hk-name').first()).toBeVisible();
  await page.waitForTimeout(1000); // let layout / chips settle

  // 1. The whole dashboard view (default card + grouped card + native cards).
  await page.screenshot({ path: `${OUT}/card-dashboard.png`, fullPage: true });

  // 2. The default card on its own.
  await shotCard(page, card, `${OUT}/card-default.png`);

  // 3. The grouped-by-status card.
  const grouped = page.locator('home-keeper-card').nth(1);
  await expect(grouped.locator('details.hk-group').first()).toBeVisible();
  await shotCard(page, grouped, `${OUT}/card-grouped.png`);

  // 4. The inline add/edit form opened from the card header.
  await card.locator('#hk-add').click();
  const form = card.locator('.hk-form');
  await expect(form.locator('ha-form').first()).toBeVisible();
  await fillText(form, 0, 'Replace dishwasher filter');
  await page.waitForTimeout(400);
  await shotCard(page, card, `${OUT}/card-add-form.png`);
});
