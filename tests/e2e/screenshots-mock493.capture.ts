/**
 * SCRATCH capture for the #493 options page (more than 1 consumable on a task).
 * Not product code. Each option sets `window.__HK_MOCK493` before it opens a form.
 *   SHOT_DIR=/tmp/shots npx playwright test --config=screenshots-mock493.config.ts
 */
import { expect, test, Page } from '@playwright/test';
import { centre, shotWithDrawer } from './shots';
import { DESKTOP, PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
type Ids = { assetId: string; deviceId: string; sed: string; carbon: string; taskId: string };
type Ids2 = { assetId: string; wearId: string; carbon: string };

test.describe.configure({ mode: 'serial' });

let ids: Ids;
let ids2: Ids2;

async function hassReady(page: Page): Promise<void> {
  await page.goto('/home-keeper', { waitUntil: 'domcontentloaded' });
  await page.locator('home-keeper-panel').first().waitFor({ state: 'attached', timeout: 45_000 });
  await page.waitForFunction(() => !!(document.querySelector('home-assistant') as any)?.hass);
}

async function setMock(page: Page, values: Record<string, unknown>): Promise<void> {
  await page.evaluate((v) => Object.assign(window as any, v), values);
}

async function openTask(page: Page, id: string): Promise<void> {
  await page.goto(`/home-keeper/tasks/${id}`, { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.d-edit')).toBeVisible({ timeout: 45_000 });
  await page.waitForTimeout(600);
}

async function openTaskForm(page: Page, id: string, mock: Record<string, unknown>) {
  await openTask(page, id);
  await setMock(page, mock);
  const panel = page.locator('home-keeper-panel').first();
  await panel.locator('.d-edit').click();
  const form = panel.locator('#hk-task-form');
  await expect(form).toBeVisible();
  return { panel, form };
}

async function shoot(page: Page, name: string, el?: () => Promise<void>) {
  for (const [vp, tag] of [
    [DESKTOP, ''],
    [PHONE, '-mobile'],
  ] as const) {
    await page.setViewportSize(vp);
    if (el) await el();
    await page.mouse.move(0, 0);
    await page.waitForTimeout(500);
    await shotWithDrawer(page, `${OUT}/${name}${tag}.png`);
  }
}

test('seed the reporter case', async ({ page }) => {
  await hassReady(page);
  [ids, ids2] = await page.evaluate(async () => {
    const hass = (document.querySelector('home-assistant') as any).hass;
    const parts = [
      { name: 'Sediment filter 5 µm', type: 'consumable', stock: 4, reorder_at: 1 },
      { name: 'Carbon block filter', type: 'consumable', stock: 2, reorder_at: 1 },
    ];
    const before = (await hass.callWS({ type: 'home_keeper/get_assets' })).assets;
    const seeded = before.some((x: any) => x.name === 'Under-sink water filter');
    if (!seeded) await hass.callService('home_keeper', 'add_asset', { name: 'Under-sink water filter', parts });
    if (!seeded) await hass.callService('home_keeper', 'add_asset', {
      name: 'Whole-house water filter',
      parts: [
        { name: 'Sediment cartridge', type: 'wear', replace_interval: 6, replace_unit: 'months', stock: 3, reorder_at: 1 },
        { name: 'Carbon cartridge', type: 'consumable', stock: 2, reorder_at: 1 },
      ],
    });
    await new Promise((r) => setTimeout(r, 2500));
    const { assets } = await hass.callWS({ type: 'home_keeper/get_assets' });
    const a = assets.find((x: any) => x.name === 'Under-sink water filter');
    const b = assets.find((x: any) => x.name === 'Whole-house water filter');
    if (!seeded) await hass.callService('home_keeper', 'add_task', {
      name: 'Replace water filters',
      device_id: a.device_id,
      recurrence_type: 'floating',
      interval: 6,
      unit: 'months',
    });
    await new Promise((r) => setTimeout(r, 2500));
    const { tasks } = await hass.callWS({ type: 'home_keeper/get_tasks' });
    const task = tasks.find((x: any) => x.name === 'Replace water filters');
    const sed = a.parts.find((p: any) => p.name.startsWith('Sediment')).id;
    const carbon = a.parts.find((p: any) => p.name.startsWith('Carbon')).id;
    return [
      { assetId: a.id, deviceId: a.device_id, sed, carbon, taskId: task.id },
      {
        assetId: b.id,
        wearId: b.parts.find((p: any) => p.type === 'wear').id,
        carbon: b.parts.find((p: any) => p.type === 'consumable').id,
      },
    ];
  });
  expect(ids.taskId).toBeTruthy();
});

test('A: today, with a better hint', async ({ page }) => {
  await hassReady(page);
  await page.evaluate(async (i) => {
    const hass = (document.querySelector('home-assistant') as any).hass;
    await hass.callService('home_keeper', 'set_task_consumable', {
      task_id: i.taskId,
      asset_id: i.assetId,
      part_id: i.sed,
    });
  }, ids);
  await openTask(page, ids.taskId);
  await shoot(page, 'A1-detail-today');
  const { form } = await openTaskForm(page, ids.taskId, { __HK_MOCK493: 'A' });
  await shoot(page, 'A2-form-hint', () => centre(form.getByText('Linked consumable').first()));
  // The appliance page with 2 consumables: what the reporter sees today.
  await page.goto(`/home-keeper/appliances/${ids.assetId}/parts`, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('home-keeper-panel').locator('.d-edit')).toBeVisible();
  await shoot(page, 'A3-appliance-parts');
});

test('B: a quantity on the link', async ({ page }) => {
  await hassReady(page);
  // The backend takes a link quantity today; only the panel form lacks the field.
  await page.evaluate(async (i) => {
    const hass = (document.querySelector('home-assistant') as any).hass;
    await hass.callService('home_keeper', 'set_task_consumable', {
      task_id: i.taskId,
      asset_id: i.assetId,
      part_id: i.sed,
      quantity: 2,
    });
  }, ids);
  await openTask(page, ids.taskId);
  await shoot(page, 'B1-detail-takes-2');
  const { form } = await openTaskForm(page, ids.taskId, {
    __HK_MOCK493: 'B',
    __HK_MOCK493_DATA: { consumable_quantity: 2 },
  });
  await shoot(page, 'B2-form-quantity', () => centre(form.getByText('Linked consumable').first()));
});

test('C: a list of consumables', async ({ page }) => {
  await hassReady(page);
  await page.evaluate(async (i) => {
    const hass = (document.querySelector('home-assistant') as any).hass;
    await hass.callService('home_keeper', 'set_task_consumable', {
      task_id: i.taskId,
      asset_id: i.assetId,
      part_id: i.sed,
      quantity: 1,
    });
  }, ids);
  const extra = {
    __HK_MOCK493_EXTRA: { [ids.taskId]: [{ asset_id: ids.assetId, part_id: ids.carbon, quantity: 1 }] },
  };
  await page.goto('/home-keeper', { waitUntil: 'domcontentloaded' });
  await setMock(page, extra);
  // The task list row, with 2 chips.
  const panel = page.locator('home-keeper-panel').first();
  await panel.locator('#hk-task-search, input[type=search]').first().waitFor({ timeout: 45_000 }).catch(() => {});
  await page.evaluate(() => (document.querySelector('home-keeper-panel') as any)?._render?.());
  await page.waitForTimeout(800);
  await shoot(page, 'C0-list-two-chips', async () => {
    const row = panel.locator(`[data-detail-id="${ids.taskId}"]`).first();
    await row.evaluate((n) => n.scrollIntoView({ block: 'center' }));
  });
  await page.goto(`/home-keeper/tasks/${ids.taskId}`, { waitUntil: 'domcontentloaded' });
  await setMock(page, extra);
  await expect(panel.locator('.d-edit')).toBeVisible();
  await page.evaluate(() => (document.querySelector('home-keeper-panel') as any)?._render?.());
  await page.waitForTimeout(800);
  await shoot(page, 'C1-detail-two-chips');
  await setMock(page, {
    __HK_MOCK493: 'C',
    __HK_MOCK493_DATA: {
      consumable_links: [`${ids.assetId}:${ids.sed}`, `${ids.assetId}:${ids.carbon}`],
      [`consumable_qty_${ids.sed}`]: 1,
      [`consumable_qty_${ids.carbon}`]: 1,
    },
  });
  await panel.locator('.d-edit').click();
  const form = panel.locator('#hk-task-form');
  await expect(form).toBeVisible();
  await shoot(page, 'C2-form-list', () => centre(form.getByText('Linked consumables').first()));
});

test('D: parts replaced together', async ({ page }) => {
  await hassReady(page);
  await setMock(page, {
    __HK_MOCK493: 'D',
    __HK_MOCK493_SIBLINGS: [{ value: ids2.carbon, label: 'Carbon cartridge' }],
    __HK_MOCK493_WITH: [ids2.carbon],
  });
  await page.goto(`/home-keeper/appliances/${ids2.assetId}`, { waitUntil: 'domcontentloaded' });
  await setMock(page, {
    __HK_MOCK493: 'D',
    __HK_MOCK493_SIBLINGS: [{ value: ids2.carbon, label: 'Carbon cartridge' }],
    __HK_MOCK493_WITH: [ids2.carbon],
  });
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.d-edit')).toBeVisible({ timeout: 45_000 });
  await panel.locator('.d-edit').click();
  const form = panel.locator('#hk-asset-form');
  await expect(form).toBeVisible();
  const section = form.locator('details.hk-collapsible').filter({ hasText: 'Parts & wear items' }).first();
  if ((await section.getAttribute('open')) === null) await section.locator('summary').first().click();
  const wear = form.locator('details.hk-part-acc').filter({ hasText: 'Sediment cartridge' }).first();
  if ((await wear.getAttribute('open')) === null) await wear.locator('summary').first().click();
  await expect(form.getByText('Replaced together with').first()).toBeVisible();
  await shoot(page, 'D1-part-editor', () => centre(form.getByText('Replaced together with').first()));
});
