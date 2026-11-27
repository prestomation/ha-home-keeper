/**
 * One-off screenshot capture for the store link on a buy reminder (issue #613) — not
 * part of the e2e suite (the filename is not *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-buy-store-link.config.ts
 *
 * A part keeps its store link in `url`. The reminder that asks you to buy the part
 * now shows that link on its task page and on the dashboard card, desktop and phone.
 */
import { expect, test } from '@playwright/test';
import { callService, openCardDashboard, openPanel } from './tests/helpers';
import { PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/hk-shots';

const ASSET = 'Garage water heater';
/** The part that gets a store link and runs low. */
const WHOLE = 'Anode rod';
const STORE_URL = 'https://shop.example.com/anode-rod';

/**
 * The fields `update_asset` accepts on a part. A part's attached file is upload-only,
 * so echoing a read part back verbatim is rejected for its `file_*` keys — the same
 * whitelist `screenshots.capture.ts` keeps for the same reason.
 */
const WRITABLE = [
  'id',
  'name',
  'part_number',
  'type',
  'vendor',
  'cost',
  'url',
  'notes',
  'replace_interval',
  'replace_unit',
  'last_replaced',
  'stock',
  'reorder_at',
  'stock_unit',
  'consume_quantity',
  'create_buy_task',
  'restock_quantity',
];

/** *part* reduced to what the service will take back. */
function writable(part: Record<string, any>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of WRITABLE) if (part[key] !== undefined && part[key] !== null) out[key] = part[key];
  return out;
}

/** The parts as the committed seed fixture holds them, put back afterwards. */
let assetId = '';
let savedParts: Record<string, unknown>[] = [];

test.beforeAll(async () => {
  const { assets } = await callService('home_keeper', 'list_assets', {}, true);
  const asset = assets.find((a: Record<string, any>) => a.name === ASSET);
  assetId = asset.id;
  savedParts = asset.parts.map(writable);
  const parts = asset.parts.map((p: Record<string, any>) => {
    const out = writable(p);
    if (p.name === WHOLE) {
      Object.assign(out, { create_buy_task: true, reorder_at: 3, stock: 1, url: STORE_URL });
    }
    return out;
  });
  await callService('home_keeper', 'update_asset', { asset_id: assetId, parts });
  await expect
    .poll(
      async () => {
        try {
          const { tasks } = await callService('home_keeper', 'list_tasks', {}, true);
          return tasks.filter((t: Record<string, any>) => t.source?.buy).length;
        } catch {
          return 0;
        }
      },
      { timeout: 60_000, intervals: [1000] },
    )
    .toBeGreaterThanOrEqual(1);
});

test.afterAll(async () => {
  if (assetId) await callService('home_keeper', 'update_asset', { asset_id: assetId, parts: savedParts });
});

test('capture the store link on a buy reminder', async ({ page }) => {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  const { tasks } = await callService('home_keeper', 'list_tasks', {}, true);
  const reminder = tasks.find((t: Record<string, any>) => t.source?.buy && t.name.includes(WHOLE));

  // 1. The reminder's own page: the linked part row names the part as a store link.
  const shotDetail = async (path: string) => {
    await page.goto(`/home-keeper/tasks/${reminder.id}`, { waitUntil: 'domcontentloaded' });
    await expect(panel.locator('.hk-detail-actions').first()).toBeVisible({ timeout: 30_000 });
    await expect(panel.locator(`a[href="${STORE_URL}"]`)).toBeVisible();
    await page.waitForTimeout(500);
    await page.screenshot({ path, fullPage: true });
  };
  await shotDetail(`${OUT}/613-panel-buy-store-link.png`);

  // 2. The dashboard card: a link chip beside the Low stock chip.
  const shotCard = async (path: string) => {
    await openCardDashboard(page);
    // The "By status" card groups the reminder under Shopping; the first card cuts its list short.
    const row = page.locator('home-keeper-card').nth(1).locator('.hk-row', { hasText: `Buy ${WHOLE}` });
    await row.first().waitFor({ state: 'attached', timeout: 30_000 });
    await row.first().evaluate((el) => el.closest('details')?.setAttribute('open', ''));
    await expect(row.locator(`a[href="${STORE_URL}"]`)).toBeVisible({ timeout: 30_000 });
    await row.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    await row.screenshot({ path });
  };
  await shotCard(`${OUT}/613b-card-buy-store-link.png`);

  // Phone width.
  await page.setViewportSize(PHONE);
  await shotDetail(`${OUT}/613c-panel-mobile-buy-store-link.png`);
  await shotCard(`${OUT}/613d-card-mobile-buy-store-link.png`);
});
