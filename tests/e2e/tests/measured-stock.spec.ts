import { test, expect } from '@playwright/test';
import { callService, listStates, openPanel } from './helpers';

/**
 * Stock measured rather than counted (issue #220), from the household's side.
 *
 * The unit tests prove the arithmetic. What only a browser shows is that the unit
 * actually reaches the surfaces people read — the part's chips on the appliance
 * page, the fields in its editor, and the stock control on the device page — and
 * that a fractional draw-down survives the whole round trip through storage rather
 * than being rounded back to whole spares somewhere in the stack. The README
 * screenshots capture these same surfaces, and a captured surface with nothing
 * asserting on it is how #221 hid in plain sight for months.
 */

const ASSET = 'asset_water_heater';
const PART = 'part_descaler';
const SEEDED_STOCK = 750;

/** The seeded measured part, read back over the public service API. */
async function readPart(): Promise<Record<string, any>> {
  const { assets } = await callService('home_keeper', 'list_assets', {}, true);
  const asset = assets.find((a: any) => a.id === ASSET);
  return asset.parts.find((p: any) => p.id === PART);
}

test.describe('a part measured in units, not whole spares', () => {
  test.afterEach(async () => {
    // The e2e container's store is the committed seed fixture, so put the stock
    // back however the test left it.
    const part = await readPart();
    const drift = SEEDED_STOCK - Number(part.stock);
    if (drift) {
      await callService('home_keeper', 'adjust_part_stock', {
        asset_id: ASSET,
        part_id: PART,
        delta: drift,
      });
    }
  });

  test('shows its unit on the appliance page, on both amounts', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#tab-appliances').click();
    await panel.locator(`.detail-open[data-detail-id="${ASSET}"]`).click();

    const row = panel.locator('.hk-part-row').filter({ hasText: 'Descaling solution' });
    await expect(row).toBeVisible();
    // Not "In stock: 750" — a bare count of somethings is exactly the problem.
    await expect(row.getByText('In stock: 750 ml')).toBeVisible();
    await expect(row.getByText('Uses 250 ml per completion')).toBeVisible();
  });

  test('offers the unit and per-completion fields in its editor', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#tab-appliances').click();
    await panel.locator(`.detail-open[data-detail-id="${ASSET}"]`).click();
    await panel.locator('.d-edit').click();

    const form = panel.locator('#hk-asset-form');
    await expect(form).toBeVisible();
    const parts = form.locator('details').filter({ hasText: 'Parts & wear items' });
    if ((await parts.count()) > 0) {
      const open = await parts.first().evaluate((d: HTMLDetailsElement) => d.open);
      if (!open) await parts.first().locator('summary').click();
    }
    // Third part in the seed: the only one with a unit.
    const measured = parts.locator('.hk-part').nth(2);
    await measured.scrollIntoViewIfNeeded();
    await expect(measured.getByText('Stock unit', { exact: false })).toBeVisible();
    await expect(measured.getByText('Used per completion', { exact: false })).toBeVisible();
  });

  test('a fractional adjustment survives the round trip', async () => {
    await callService('home_keeper', 'adjust_part_stock', {
      asset_id: ASSET,
      part_id: PART,
      delta: -0.5,
    });
    // Truncating to an int here is the bug this guards: 749.5, not 749 or 750.
    await expect.poll(async () => (await readPart()).stock).toBe(749.5);
  });

  test("the device page's stock control carries the part's unit", async () => {
    const states = await listStates();
    const stock = states.find(
      (s: any) =>
        s.entity_id.startsWith('number.') &&
        String(s.attributes.friendly_name || '').includes('Descaling solution'),
    );
    expect(stock, 'the measured part should have a stock number entity').toBeTruthy();
    expect(stock.attributes.unit_of_measurement).toBe('ml');
    expect(Number(stock.state)).toBe(SEEDED_STOCK);
    // A measured part steps finely; a part counted in whole spares still steps by 1.
    expect(stock.attributes.step).toBeLessThan(1);
  });
});
