/**
 * One-off screenshot capture for how a buy reminder reads *away from the task list* —
 * not part of the e2e suite (the filename is not *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-shopping-status.config.ts
 *
 * The task list and the dashboard card already say "Low stock" (see
 * `45-panel-shopping-section.png`, captured by the main tour). These two shots cover
 * the surfaces that did not: a reminder's own detail page, and the appliance's Tasks
 * tab. Both read "Overdue" in red until now, so one reminder had two statuses
 * depending on where it was looked at — and the appliance tab put that red pill inches
 * from the parts list already saying the part was low.
 *
 * Its own harness rather than two more steps in `screenshots.capture.ts`: the tour is
 * a single 8-minute test that has to walk the whole panel to reach this state, so a
 * shot of one surface is far cheaper to re-take from a capture that seeds the part
 * directly. Same reason `screenshots-companion-filter` and the other focused captures
 * beside it exist.
 */
import { expect, test } from '@playwright/test';
import { callService, openPanel } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/hk-shots';

const ASSET = 'Garage water heater';
/** Measured in a unit, so the shopping line also shows the amount to buy. */
const MEASURED = 'Descaling solution';
/** Restocks one plain spare, so its line stays bare — the two cases side by side. */
const WHOLE = 'Anode rod';

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

/** Read the appliance fresh — a buy reminder appearing schedules a reload. */
async function waterHeater(): Promise<Record<string, any>> {
  const { assets } = await callService('home_keeper', 'list_assets', {}, true);
  return assets.find((a: Record<string, any>) => a.name === ASSET);
}

test.beforeAll(async () => {
  const asset = await waterHeater();
  assetId = asset.id;
  savedParts = asset.parts.map(writable);

  // Take both parts under their reorder point, which is the whole trigger: the
  // reconciler mints a "Buy {part}" one-off per low part on its next pass.
  const parts = asset.parts.map((p: Record<string, any>) => {
    const out = writable(p);
    if (p.name === MEASURED) Object.assign(out, { create_buy_task: true, restock_quantity: 750, stock: 100 });
    if (p.name === WHOLE) Object.assign(out, { create_buy_task: true, reorder_at: 3, stock: 1 });
    return out;
  });
  await callService('home_keeper', 'update_asset', { asset_id: assetId, parts });

  // Wait for the reminders rather than sleeping: creating one owns device entities and
  // schedules a deferred reload, during which a read can 500.
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
    .toBeGreaterThanOrEqual(2);
});

test.afterAll(async () => {
  if (assetId) await callService('home_keeper', 'update_asset', { asset_id: assetId, parts: savedParts });
});

test('capture a buy reminder off the task list', async ({ page }) => {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();

  const { tasks } = await callService('home_keeper', 'list_tasks', {}, true);
  const reminder = tasks.find(
    (t: Record<string, any>) => t.source?.buy && t.name.includes(WHOLE),
  );

  // 1. The reminder's own page. "Low stock" in the warn colour, not "Overdue" in red —
  // and a greyed Duplicate, because the reconciler owns this row: a copy would carry no
  // `source.buy`, so nothing would ever retire it.
  await page.goto(`/home-keeper/tasks/${reminder.id}`, { waitUntil: 'domcontentloaded' });
  await expect(panel.locator('.hk-detail-actions').first()).toBeVisible({ timeout: 30_000 });
  await expect(panel.locator('.hk-chips ha-assist-chip.hk-shopping').first()).toBeVisible();
  await expect(panel.locator('.d-dup-blocked')).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/45b-panel-shopping-detail.png`, fullPage: true });

  // 2. The appliance's Tasks tab, where the reminders sit under the parts list that
  // already says the part is low. Real maintenance keeps its red "Overdue" in the same
  // list, which is the contrast worth photographing.
  await page.goto(`/home-keeper/appliances/${assetId}/tasks`, { waitUntil: 'domcontentloaded' });
  await expect(panel.locator('.hk-rel').first()).toBeVisible({ timeout: 30_000 });
  await expect(panel.locator('.hk-rel ha-assist-chip.hk-shopping').first()).toBeVisible();
  await expect(panel.locator('.hk-rel ha-assist-chip.hk-overdue').first()).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/45c-panel-appliance-tasks.png`, fullPage: true });
});
