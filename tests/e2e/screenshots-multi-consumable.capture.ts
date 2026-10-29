/**
 * Screenshot capture for several consumables on 1 task (issue #493) — not part of the
 * e2e suite (the filename is not *.spec.ts). Run from tests/e2e/:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-multi-consumable.config.ts
 *
 * Covers the 3 changed surfaces, desktop and phone:
 *  34b / 34c. The task form: Linked consumables with 2 filters, and 1 amount field
 *             for each filter.
 *  34d / 34f. The task page: 1 stock chip and 1 Linked consumables line for each part.
 *  34e / 34g. The task list row: 1 short "2 parts · Low stock" chip.
 *  34h / 34i. The task list row of a part with a long name: the name is cut, and the
 *             count stays in view.
 *  34j / 34k. The Remove part confirm, which names the task that takes the part.
 *  34l / 34m. The form of a task with no device: its link shows as "Part · Appliance",
 *             with its amount field.
 *
 * Its own file, as the counted-wear capture is, so the shots do not inherit the state
 * of the long walk in `screenshots.capture.ts`, and the appliance it makes is gone
 * before any other capture runs.
 */
import { expect, Locator, Page, test } from '@playwright/test';
import { centre, shotWithDrawer } from './shots';
import { PHONE } from './viewports';
import { openListFilters, openPanel } from './tests/helpers';
import { WATER, WaterIds, callWhenReady, removeWaterSystem, seedWaterSystem } from './water-system';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
const MANY = '2 parts · Low stock';
const LONG = 'Water soften… · 8 left';
const NO_DEVICE = 'Check softener salt';

async function openTask(page: Page, ids: WaterIds): Promise<Locator> {
  await page.goto(`/home-keeper/tasks/${ids.taskId}`, { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  await expect(panel.locator('.hk-asset-head .hk-part-chip')).toHaveCount(2);
  return panel;
}

async function shootForm(page: Page, panel: Locator, path: string): Promise<void> {
  await panel.locator('.d-edit').click();
  const form = panel.locator('#hk-task-form');
  await expect(form).toBeVisible();
  const amount = panel.locator('#hk-task-form-placement ha-selector-number').nth(1);
  await expect(amount).toBeVisible();
  await centre(amount);
  await page.mouse.move(0, 0);
  await page.waitForTimeout(500);
  await shotWithDrawer(page, path);
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });
}

async function shootRow(
  page: Page,
  path: string,
  taskId: string,
  query: string,
  label: string,
): Promise<void> {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  // Dismiss the first-run banner if it is up, so the row is in frame.
  const intro = panel.locator('ha-button.hk-intro-dismiss');
  if ((await intro.count()) > 0) {
    await intro.click();
    await expect(panel.locator('.hk-intro')).toHaveCount(0);
  }
  await openListFilters(panel);
  await panel.locator('.hk-search-input').fill(query);
  const row = panel.locator(`ha-card.hk-card[data-id="${taskId}"]`);
  await expect(row.locator('ha-assist-chip.hk-part-chip')).toHaveAttribute('label', label);
  await row.scrollIntoViewIfNeeded();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(500);
  await page.screenshot({ path });
  await panel.locator('.hk-search-input').fill('');
}

/** The Remove part confirm, which names the task that takes the part. */
async function shootRemoveConfirm(page: Page, path: string, ids: WaterIds): Promise<void> {
  await page.goto(`/home-keeper/appliances/${ids.assetId}`, { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await panel.locator('#part-edit-0').click();
  const part = panel.locator('#hk-asset-form details.hk-part[data-idx="0"]');
  await expect(part).toHaveAttribute('open', '');
  await part.locator('.part-del').click();
  const scrim = page.locator('.hk-confirm-scrim');
  await expect(scrim.locator('#hk-confirm-body')).toContainText(WATER.task);
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await page.screenshot({ path });
  await page.keyboard.press('Escape');
  await expect(scrim).toHaveCount(0);
  await panel.locator('#a-cancel').click();
}

/** The picker of a task with no device: its link shows as "Part · Appliance". */
async function shootNoDeviceForm(page: Page, path: string, taskId: string): Promise<void> {
  await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await panel.locator('.d-edit').click();
  const amount = panel.locator('#hk-task-form-placement ha-selector-number').first();
  await expect(amount).toBeVisible();
  await expect(panel.locator('#hk-task-form-placement')).toContainText(
    `${WATER.salt} · ${WATER.appliance}`,
  );
  await centre(amount);
  await page.mouse.move(0, 0);
  await page.waitForTimeout(500);
  await shotWithDrawer(page, path);
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });
}

test('capture several consumables on 1 task', async ({ page }) => {
  test.setTimeout(240_000);
  let ids: WaterIds | null = null;
  let looseId = '';
  try {
    ids = await seedWaterSystem();
    const loose = await callWhenReady(
      'add_task',
      { name: NO_DEVICE, recurrence_type: 'floating', interval: 1, unit: 'months' },
      true,
    );
    looseId = loose.task_id;
    await callWhenReady('set_task_consumable', {
      task_id: looseId,
      parts: [{ asset_id: ids.assetId, part_id: ids.saltId }],
    });

    // ── desktop ──
    let panel = await openTask(page, ids);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/34d-panel-multi-consumable-detail.png`, fullPage: true });
    await shootForm(page, panel, `${OUT}/34b-panel-multi-consumable-form.png`);
    await shootRow(page, `${OUT}/34e-panel-multi-consumable-list.png`, ids.taskId, 'filter', MANY);
    await shootRow(page, `${OUT}/34h-panel-multi-consumable-long-name.png`, ids.saltTaskId, 'salt', LONG);
    await shootRemoveConfirm(page, `${OUT}/34j-panel-multi-consumable-remove-part.png`, ids);
    await shootNoDeviceForm(page, `${OUT}/34l-panel-multi-consumable-no-device.png`, looseId);

    // ── phone ──
    await page.setViewportSize(PHONE);
    panel = await openTask(page, ids);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/34f-panel-mobile-multi-consumable-detail.png` });
    await shootForm(page, panel, `${OUT}/34c-panel-mobile-multi-consumable-form.png`);
    await shootRow(page, `${OUT}/34g-panel-mobile-multi-consumable-list.png`, ids.taskId, 'filter', MANY);
    await shootRow(
      page,
      `${OUT}/34i-panel-mobile-multi-consumable-long-name.png`,
      ids.saltTaskId,
      'salt',
      LONG,
    );
    await shootRemoveConfirm(page, `${OUT}/34k-panel-mobile-multi-consumable-remove-part.png`, ids);
    await shootNoDeviceForm(page, `${OUT}/34m-panel-mobile-multi-consumable-no-device.png`, looseId);
  } finally {
    if (looseId) await callWhenReady('delete_task', { task_id: looseId }).catch(() => undefined);
    await removeWaterSystem(ids);
  }
});
