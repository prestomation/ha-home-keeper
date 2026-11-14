import { test, expect, Locator, Page } from '@playwright/test';
import { resolve } from 'node:path';
import { callService, gotoTab, expectTabActive, openPanel } from './helpers';
import { ASSET, PART } from '../fixture-ids';

/**
 * The Parts view of the Appliances tab (#547): every part of every appliance in one
 * list, at `/home-keeper/appliances/parts`.
 *
 * The seed has 3 appliances with parts. Water heater: Anode rod (2 of 2, low), T&P
 * relief valve (not counted), Descaling solution, Sediment pre-filter. Rain jacket: DWR
 * coating (not counted). Batteries, which an integration owns: AA, AAA (2 of 4, low) and
 * CR2032 (not counted). A spec that adds an appliance deletes it again.
 */
const PARTS_URL = '/home-keeper/appliances/parts';
const VIEWER_STATE = resolve(__dirname, '../.auth/viewer-state.json');

const panelOf = (page: Page): Locator => page.locator('home-keeper-panel').first();
const rows = (panel: Locator): Locator => panel.locator('.hk-pt-row');
const row = (panel: Locator, partId: string): Locator =>
  panel.locator(`.hk-pt-row[data-part-row="${partId}"]`);

async function openParts(page: Page): Promise<Locator> {
  await page.goto(PARTS_URL, { waitUntil: 'domcontentloaded' });
  const panel = panelOf(page);
  await expect(panel.locator('.hk-parts-view')).toBeVisible({ timeout: 45_000 });
  return panel;
}

/** The parts that the active appliances hold, read from the service API. */
async function activeParts(): Promise<Array<Record<string, any>>> {
  const { assets } = await callService('home_keeper', 'list_assets', {}, true);
  return assets
    .filter((a: any) => !a.archived_at)
    .flatMap((a: any) => (a.parts ?? []).map((p: any) => ({ ...p, asset_id: a.id })));
}

test.describe('Home Keeper — Parts view', { tag: '@responsive' }, () => {
  test('the Appliances | Parts switch opens the view and closes it again', async ({ page }) => {
    await openPanel(page);
    const panel = panelOf(page);
    await gotoTab(panel, 'appliances');
    const mode = panel.locator('.hk-mode .hk-seg-btn');
    await expect(mode).toHaveText(['Appliances', 'Parts']);
    await expect(mode.nth(0)).toHaveAttribute('aria-pressed', 'true');
    await mode.nth(1).click();
    await expect(page).toHaveURL(/\/home-keeper\/appliances\/parts$/);
    await expect(panel.locator('.hk-parts-view')).toBeVisible();
    await expectTabActive(panel, 'appliances');
    await expect(panel.locator('.hk-mode .hk-seg-btn').nth(1)).toHaveAttribute('aria-pressed', 'true');
    // Add belongs to an appliance, so the view has none.
    await expect(panel.locator('#add-btn')).toHaveCount(0);
    await panel.locator('.hk-mode .hk-seg-btn').nth(0).click();
    await expect(page).toHaveURL(/\/home-keeper\/appliances$/);
    await expect(panel.locator('.hk-parts-view')).toHaveCount(0);
    await expect(panel.locator('.hk-card[data-id]').first()).toBeVisible();
  });

  test('lists every part of every appliance, grouped, and opens the part on its appliance', async ({
    page,
  }) => {
    const panel = await openParts(page);
    const expected = await activeParts();
    await expect(rows(panel)).toHaveCount(expected.length);
    expect(expected.length).toBeGreaterThanOrEqual(8);
    for (const title of ['Garage water heater', 'Batteries', 'Rain jacket']) {
      await expect(panel.locator('.hk-pt-group-title', { hasText: title })).toBeVisible();
    }
    // The integration-owned appliance's parts show, with a working stepper.
    await expect(row(panel, PART.aaa).locator('.hk-stock')).toBeVisible();
    await row(panel, PART.anode).locator('a.hk-pt-name').click();
    await expect(page).toHaveURL(new RegExp(`/appliances/${ASSET.waterHeater}/parts/${PART.anode}$`));
  });

  test('the chips count, filter and are remembered; search finds a vendor', async ({ page }) => {
    const panel = await openParts(page);
    const parts = await activeParts();
    const low = parts.filter((p) => p.stock != null && p.reorder_at != null && p.stock <= p.reorder_at);
    const chip = (v: string): Locator => panel.locator(`.hk-pt-filters [data-seg-val="${v}"]`);
    await expect(chip('all')).toHaveText(`All${parts.length}`);
    await expect(chip('low')).toHaveText(`Low stock${low.length}`);
    await chip('low').click();
    await expect(rows(panel)).toHaveCount(low.length);
    await expect(chip('low')).toHaveAttribute('aria-pressed', 'true');
    // A reload keeps the chip: it is stored in this browser.
    await page.reload();
    await expect(panel.locator('.hk-parts-view')).toBeVisible({ timeout: 45_000 });
    await expect(rows(panel)).toHaveCount(low.length);
    await chip('all').click();
    await expect(rows(panel)).toHaveCount(parts.length);
    const box = panel.locator('.hk-search-input');
    await box.fill('anode');
    await expect(rows(panel)).toHaveCount(1);
    await expect(row(panel, PART.anode)).toBeVisible();
    await box.fill('no such part');
    await expect(rows(panel)).toHaveCount(0);
    await expect(panel.locator('ha-alert')).toContainText('No parts match');
  });

  test('a low part has a marker and a status word, and its stock changes in the row', async ({
    page,
  }) => {
    const panel = await openParts(page);
    const aaa = row(panel, PART.aaa);
    await expect(aaa).toHaveClass(/low/);
    await expect(aaa.locator('.hk-pt-status ha-assist-chip')).toHaveAttribute('label', 'Low stock');
    const input = aaa.locator('.hk-stock-input');
    await expect(input).toHaveValue('2');
    try {
      await aaa.locator('.hk-stock-inc').click();
      await expect(row(panel, PART.aaa).locator('.hk-stock-input')).toHaveValue('3');
      const aaaNow = (await activeParts()).find((p) => p.id === PART.aaa);
      expect(aaaNow?.stock).toBe(3);
    } finally {
      const now = (await activeParts()).find((p) => p.id === PART.aaa);
      const drift = 2 - Number(now?.stock);
      if (drift) {
        await callService('home_keeper', 'adjust_part_stock', {
          asset_id: ASSET.batteries,
          part_id: PART.aaa,
          delta: drift,
        });
      }
    }
  });

  test('a low part with a Buy task links it', async ({ page }) => {
    await callService('home_keeper', 'add_asset', {
      name: 'E2E parts buy',
      parts: [
        { name: 'E2E cartridge', type: 'consumable', stock: 0, reorder_at: 1, create_buy_task: true },
      ],
    });
    const { assets } = await callService('home_keeper', 'list_assets', {}, true);
    const asset = assets.find((a: any) => a.name === 'E2E parts buy');
    try {
      const panel = await openParts(page);
      const buy = row(panel, asset.parts[0].id).locator('a.hk-pt-buy');
      await expect(buy).toBeVisible();
      await buy.click();
      await expect(page).toHaveURL(/\/home-keeper\/tasks\//);
    } finally {
      await callService('home_keeper', 'delete_asset', { asset_id: asset.id });
    }
  });

  test('archived appliances show only when the Archived scope is on', async ({ page }) => {
    await callService('home_keeper', 'add_asset', {
      name: 'E2E parts archived',
      parts: [{ name: 'E2E gasket', type: 'wear', stock: 1, reorder_at: 0 }],
    });
    const { assets } = await callService('home_keeper', 'list_assets', {}, true);
    const asset = assets.find((a: any) => a.name === 'E2E parts archived');
    try {
      await callService('home_keeper', 'archive_asset', { asset_id: asset.id });
      const panel = await openParts(page);
      await expect(row(panel, asset.parts[0].id)).toHaveCount(0);
      await panel.locator('.hk-seg[data-seg="assetFilter"] [data-seg-val="archived"]').click();
      await expect(row(panel, asset.parts[0].id)).toBeVisible();
      await expect(rows(panel)).toHaveCount(1);
      await panel.locator('.hk-seg[data-seg="assetFilter"] [data-seg-val="active"]').click();
      await expect(row(panel, asset.parts[0].id)).toHaveCount(0);
    } finally {
      await callService('home_keeper', 'delete_asset', { asset_id: asset.id });
    }
  });

  test('the appliance page still opens from its old URL', async ({ page }) => {
    await page.goto(`/home-keeper/appliances/${ASSET.waterHeater}`, { waitUntil: 'domcontentloaded' });
    const panel = panelOf(page);
    await expect(panel.locator('.hk-subtab').first()).toBeVisible({ timeout: 45_000 });
    await expect(panel.locator('.hk-parts-view')).toHaveCount(0);
  });
});

test.describe('Home Keeper — Parts view, read only', { tag: '@responsive' }, () => {
  test.use({ storageState: VIEWER_STATE });

  test('a non-admin sees the list with the view-only note and no stepper', async ({ page }) => {
    const panel = await openParts(page);
    await expect(panel.locator('.hk-view-only-banner')).toBeVisible();
    await expect(rows(panel).first()).toBeVisible();
    await expect(panel.locator('.hk-stock')).toHaveCount(0);
    await expect(panel.locator('#add-btn')).toHaveCount(0);
    await expect(row(panel, PART.anode).locator('.hk-pt-stock ha-assist-chip')).toHaveAttribute(
      'label',
      /In stock: 2/,
    );
  });
});
