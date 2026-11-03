import { test, expect } from '@playwright/test';
import { callService, openPanel, openListFilters } from './helpers';
import { WATER, WaterIds, removeWaterSystem, seedWaterSystem } from '../water-system';

/**
 * Several consumables on 1 task (#493), in the browser.
 *
 * The unit and integration tiers prove the store and the service. This spec proves
 * the 3 surfaces a user sees: the task form lists each linked part with its own
 * amount, the task page shows 1 chip for each part, and the list row folds them
 * into 1 short chip that opens the task.
 */
test.describe('Home Keeper — several consumables on 1 task @responsive', () => {
  test.describe.configure({ mode: 'serial' });
  let ids: WaterIds | null = null;

  test.beforeAll(async () => {
    ids = await seedWaterSystem();
  });

  test.afterAll(async () => {
    await removeWaterSystem(ids);
    ids = null;
  });

  test('the list row folds the parts into 1 chip that opens the task', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await openListFilters(panel);
    await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="all"]').click();
    const row = panel.locator(`ha-card.hk-card[data-id="${ids!.taskId}"]`);
    await row.scrollIntoViewIfNeeded();
    const chip = row.locator('ha-assist-chip.hk-part-chip');
    await expect(chip).toHaveAttribute('label', '2 parts · Low stock');
    // The stock chip leads the strip, so the column never cuts it off.
    await expect(row.locator('.hk-chips-inline > :first-child')).toHaveClass(/hk-part-chip/);
    const box = await chip.boundingBox();
    const strip = await row.locator('.hk-chips-inline').boundingBox();
    expect(box!.x + box!.width).toBeLessThanOrEqual(strip!.x + strip!.width + 1);
    await expect(chip).toHaveAttribute(
      'title',
      `Takes 2 ${WATER.sediment}\nTakes 1 ${WATER.carbon}`,
    );
    await chip.click();
    await expect(page).toHaveURL(new RegExp(`/home-keeper/tasks/${ids!.taskId}$`));
  });

  test('a long part name keeps the count on the row chip', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await openListFilters(panel);
    await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="all"]').click();
    const row = panel.locator(`ha-card.hk-card[data-id="${ids!.saltTaskId}"]`);
    await row.scrollIntoViewIfNeeded();
    const chip = row.locator('ha-assist-chip.hk-part-chip');
    await expect(chip).toHaveAttribute('label', 'Water soften… · 8 left');
    await expect(chip).toHaveAttribute('title', `Takes 1 ${WATER.salt} · 8 left`);
    const box = await chip.boundingBox();
    const strip = await row.locator('.hk-chips-inline').boundingBox();
    expect(box!.x + box!.width).toBeLessThanOrEqual(strip!.x + strip!.width + 1);
    // The device chip folds behind +1, in view, and opens with it.
    const more = row.locator('.hk-chip-more');
    await expect(more).toHaveText('+1');
    const plus = await more.boundingBox();
    // Clear of the 18px fade at the end of the chip track, where the track has one.
    const masked = await row
      .locator('.hk-chips-inline')
      .evaluate((el) => getComputedStyle(el).maskImage !== 'none');
    const fade = masked ? 18 : 0;
    expect(plus!.x + plus!.width).toBeLessThanOrEqual(strip!.x + strip!.width - fade);
    await more.click();
    await expect(row.locator('ha-assist-chip.hk-device-chip')).toBeVisible();
    await more.click();
  });

  test('a pick keeps the keyboard in the picker', async ({ page }) => {
    await page.goto(`/home-keeper/tasks/${ids!.saltTaskId}`, { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('.d-edit').click();
    const picker = panel
      .locator('#hk-task-form-placement ha-selector-select')
      .filter({ hasText: WATER.salt });
    const focusPath = () =>
      page.evaluate(() => {
        const out: string[] = [];
        let el: Element | null | undefined = document.activeElement;
        while (el) {
          out.push(el.tagName.toLowerCase());
          el = el.shadowRoot?.activeElement;
        }
        return out.join(' > ');
      });
    await picker.locator('ha-generic-picker ha-button').click();
    // Type only once the search box has the keyboard, or HA's shortcuts take the keys.
    await expect.poll(focusPath).toContain('ha-input-search');
    await page.keyboard.type(WATER.carbon);
    await page.keyboard.press('Enter');
    const amounts = panel.locator('#hk-task-form-placement ha-selector-number');
    await expect(amounts).toHaveCount(2);
    // The keyboard stays on the picker's own Add button. Stable HA nests the button in
    // `ha-generic-picker`. The 2026.11 beta slots it from `ha-selector-select`. Tab goes on from it.
    await expect
      .poll(focusPath)
      .toMatch(/ha-selector-select > (ha-generic-picker > )?ha-button > button$/);
    await page.keyboard.press('Tab');
    await expect.poll(focusPath).toContain('ha-selector-number');
    await panel.locator('#f-cancel').click();
    await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });
  });

  test('the task page shows 1 chip and 1 line for each part', async ({ page }) => {
    await page.goto(`/home-keeper/tasks/${ids!.taskId}`, { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    const chips = panel.locator('.hk-asset-head .hk-chips ha-assist-chip.hk-part-chip');
    await expect(chips).toHaveCount(2);
    await expect(chips.nth(0)).toHaveAttribute('label', `Takes 2 ${WATER.sediment} · 6 left`);
    await expect(chips.nth(1)).toHaveAttribute('label', `Takes 1 ${WATER.carbon} · 1 left`);
    const lines = panel.locator('a.hk-part-link');
    await expect(lines).toHaveCount(2);
    // A chip opens its own part on the appliance page.
    await chips.nth(1).click();
    await expect(page).toHaveURL(
      new RegExp(`/home-keeper/appliances/${ids!.assetId}/parts/${ids!.carbonId}$`),
    );
  });

  test('the form shows an amount for each part and saves a changed amount', async ({ page }) => {
    await page.goto(`/home-keeper/tasks/${ids!.taskId}`, { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('.d-edit').click();
    const form = panel.locator('#hk-task-form');
    await expect(form).toBeVisible();
    await expect(form.getByText('Linked consumables').first()).toBeVisible();
    // The 2 amount fields are the only numbers in the placement section, in the
    // order of the links, each named for its part.
    const amounts = panel.locator('#hk-task-form-placement ha-selector-number');
    await expect(amounts).toHaveCount(2);
    await expect(form.getByText(`${WATER.sediment}: takes per completion`)).toHaveCount(1);
    await expect(form.getByText(`${WATER.carbon}: takes per completion`)).toHaveCount(1);
    const sediment = amounts.nth(0).locator('input');
    const carbon = amounts.nth(1).locator('input');
    await expect(sediment).toHaveValue('2');
    await expect(carbon).toHaveValue('');
    await carbon.fill('3');
    await panel.locator('#f-save').click();
    await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 15_000 });
    await expect
      .poll(async () => {
        const { tasks } = await callService('home_keeper', 'list_tasks', {}, true);
        return tasks.find((t: any) => t.id === ids!.taskId)?.source?.parts;
      })
      .toEqual([
        { asset_id: ids!.assetId, part_id: ids!.sedimentId, quantity: 2 },
        { asset_id: ids!.assetId, part_id: ids!.carbonId, quantity: 3 },
      ]);
    // Put the seed back for the next width.
    await callService('home_keeper', 'set_task_consumable', {
      task_id: ids!.taskId,
      parts: [
        { asset_id: ids!.assetId, part_id: ids!.sedimentId, quantity: 2 },
        { asset_id: ids!.assetId, part_id: ids!.carbonId },
      ],
    });
  });
});
