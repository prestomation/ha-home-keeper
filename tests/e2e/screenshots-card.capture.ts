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

  // The seeded water-filter task points at a placeholder device_id; re-attach it to
  // its real (runtime-provisioned) appliance device so the row's device chip resolves
  // to "Garage water heater" rather than a raw id — and its pinned links still resolve
  // (they reference the appliance by id, independent of the device).
  await page.evaluate(async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { assets } = await hass.callWS({ type: 'home_keeper/get_assets' });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const wh = assets.find((a: any) => a.name === 'Garage water heater');
    if (wh?.device_id) {
      await hass.callService('home_keeper', 'update_task', {
        task_id: 'task_water_filter',
        device_id: wh.device_id,
      });
    }
  });
  await page.waitForTimeout(1500); // attaching a device reloads the entry; let it settle
  await expect(card.locator('a.hk-doc').first()).toBeVisible();
  await page.waitForTimeout(500); // let layout / chips settle

  // 1. The whole dashboard view (default card + grouped card + native cards).
  await page.screenshot({ path: `${OUT}/card-dashboard.png`, fullPage: true });

  // 2. The default card on its own. The seeded water-filter task pins some of its
  // appliance's documents, so this clip also shows the per-task document chips.
  await shotCard(page, card, `${OUT}/card-default.png`);

  // 2b. Same card, named for the per-task "documents to show on card" feature — the
  // water-filter row carries "Owner's manual", "Reorder filter" and a file chip.
  await expect(card.locator('a.hk-doc').first()).toBeVisible();
  await shotCard(page, card, `${OUT}/card-task-links.png`);

  // 3. The grouped-by-status card.
  const grouped = page.locator('home-keeper-card').nth(1);
  await expect(grouped.locator('details.hk-group').first()).toBeVisible();
  await shotCard(page, grouped, `${OUT}/card-grouped.png`);

  // 3b. The label-filtered "Dog" card — only tasks carrying the `dog` label, with
  // each row's label chips shown (exercises labels filter + show_labels).
  const labelCard = page.locator('home-keeper-card').nth(2);
  await expect(labelCard.locator('.hk-name').first()).toBeVisible();
  await expect(labelCard.locator('ha-assist-chip.hk-label').first()).toBeVisible();
  await shotCard(page, labelCard, `${OUT}/card-label-filter.png`);

  // 4. The inline add/edit form opened from the card header.
  await card.locator('#hk-add').click();
  const form = card.locator('.hk-form');
  await expect(form.locator('ha-form').first()).toBeVisible();
  await fillText(form, 0, 'Replace dishwasher filter');
  await page.waitForTimeout(400);
  await shotCard(page, card, `${OUT}/card-add-form.png`);
});
