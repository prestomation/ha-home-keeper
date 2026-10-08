/**
 * Screenshot capture for QR code labels (#428). Not part of the e2e suite (the file
 * name is not *.spec.ts). Run:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-qr-labels.capture.ts \
 *     --config=screenshots-qr-labels.config.ts
 *
 * Shots, desktop then phone:
 *  79.  The appliance list with Print labels beside Add.
 *  79b. The Print labels checklist: 2 appliances checked, with their tasks.
 *  79c. The label dialog on an appliance page.
 *  79d. The label dialog on a task page.
 *  79e. The printed sheet, drawn from the document the panel hands the browser.
 *  79f-79i. The phone versions of 79 to 79d.
 *  79j/79k. The QR label button on the appliance page, desktop and phone.
 *  79l/79n. The label dialog with a 50 × 30 mm label roll, desktop and phone.
 *  79m. 1 page of the roll print, as Save as PDF makes it.
 *
 * The desktop dialog shots use a taller window, so the whole checklist is in frame.
 *
 * The text-line choice is kept per browser, and each shot starts from the default.
 */
import { test, expect, Locator, Page } from '@playwright/test';
import { gotoTab, openAppliance, openPanel } from './tests/helpers';
import { ASSET, TASK } from './fixture-ids';
import { DESKTOP, PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

function labelDialog(panel: Locator): Locator {
  return panel.locator('ha-dialog.hk-label-dialog');
}

/** Wait for the dialog's open animation, so a shot is not half faded. */
async function settled(page: Page, dialog: Locator): Promise<void> {
  await expect(dialog.locator('[data-label-print]')).toBeVisible({ timeout: 5_000 });
  await page.waitForTimeout(700);
}

async function closeDialog(page: Page): Promise<void> {
  await labelDialog(page.locator('home-keeper-panel').first())
    .locator('[data-label-close]')
    .click();
  await expect(labelDialog(page.locator('home-keeper-panel').first())).toHaveCount(0);
}

async function listShots(page: Page, list: string, picker: string): Promise<string> {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await gotoTab(panel, 'appliances');
  await expect(panel.locator('#labels-btn')).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/${list}.png` });

  await page.evaluate(() => {
    const w = window as unknown as { __hkPrints: string[] };
    w.__hkPrints = [];
    new MutationObserver((records) => {
      for (const r of records) {
        r.addedNodes.forEach((node) => {
          if (node instanceof HTMLIFrameElement && node.id === 'hk-label-print') {
            w.__hkPrints.push(node.srcdoc);
          }
        });
      }
    }).observe(document.body, { childList: true });
  });
  await panel.locator('#labels-btn').click();
  const dialog = labelDialog(panel);
  await dialog.locator(`[data-label-pick="${ASSET.waterHeater}"]`).check();
  await dialog.locator(`[data-label-pick="${ASSET.shades}"]`).check();
  await dialog.locator('[data-label-with-tasks]').check();
  // Checking a row scrolls the dialog to it. Start the shot at the top of the list.
  await dialog.locator('.hk-label-list-head').scrollIntoViewIfNeeded();
  await settled(page, dialog);
  await page.screenshot({ path: `${OUT}/${picker}.png` });
  await dialog.locator('[data-label-print]').click();
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { __hkPrints: string[] }).__hkPrints.length))
    .toBe(1);
  const html = await page.evaluate(() => (window as unknown as { __hkPrints: string[] }).__hkPrints[0]);
  await closeDialog(page);
  return html;
}

async function applianceShot(page: Page, name: string, button: string): Promise<void> {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  const dialog = labelDialog(panel);
  // The page before this one can still finish a navigation, which reloads the panel
  // and closes the dialog. So open the page and the dialog again until the shot holds.
  await expect(async () => {
    if (!(await panel.locator('.d-label').isVisible())) {
      await openAppliance(page, ASSET.waterHeater);
    }
    await expect(panel.locator('.d-label')).toBeVisible({ timeout: 5_000 });
    await page.mouse.move(0, 0);
    await page.waitForTimeout(400);
    await panel.locator('.hk-asset-head').first().screenshot({ path: `${OUT}/${button}.png` });
    await panel.locator('.d-label').click({ timeout: 5_000 });
    await expect(dialog.locator('.hk-label-qr svg')).toBeVisible({ timeout: 5_000 });
    await settled(page, dialog);
    await page.screenshot({ path: `${OUT}/${name}.png` });
    await expect(dialog.locator('[data-label-close]')).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 45_000 });
  await closeDialog(page);
}

async function taskShot(page: Page, name: string): Promise<void> {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  const dialog = labelDialog(panel);
  await expect(async () => {
    if (!(await panel.locator('.d-label').isVisible())) {
      await panel
        .locator(`.detail-open[data-detail-id="${TASK.waterFilter}"]`)
        .click({ timeout: 5_000 });
    }
    await panel.locator('.d-label').click({ timeout: 5_000 });
    await expect(dialog.locator('.hk-label-qr svg')).toBeVisible({ timeout: 5_000 });
    await settled(page, dialog);
    await page.screenshot({ path: `${OUT}/${name}.png` });
    await expect(dialog.locator('[data-label-close]')).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 45_000 });
  await closeDialog(page);
}

/** The appliance label dialog with a label roll picked. Returns the print document. */
async function rollShot(page: Page, name: string): Promise<string> {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  const dialog = labelDialog(panel);
  await page.evaluate(() => {
    const w = window as unknown as { __hkPrints: string[] };
    w.__hkPrints = [];
    new MutationObserver((records) => {
      for (const r of records) {
        r.addedNodes.forEach((node) => {
          if (node instanceof HTMLIFrameElement && node.id === 'hk-label-print') {
            w.__hkPrints.push(node.srcdoc);
          }
        });
      }
    }).observe(document.body, { childList: true });
  });
  await expect(async () => {
    if (!(await panel.locator('.d-label').isVisible())) {
      await openAppliance(page, ASSET.waterHeater);
    }
    await panel.locator('.d-label').click({ timeout: 5_000 });
    await dialog.locator('[data-label-paper]').selectOption('roll_50x30', { timeout: 5_000 });
    await expect(dialog.locator('[data-label-rotate-field]')).toBeVisible({ timeout: 5_000 });
    await settled(page, dialog);
    await page.screenshot({ path: `${OUT}/${name}.png` });
    await expect(dialog.locator('[data-label-close]')).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 45_000 });
  await dialog.locator('[data-label-print]').click();
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { __hkPrints: string[] }).__hkPrints.length))
    .toBe(1);
  const html = await page.evaluate(() => (window as unknown as { __hkPrints: string[] }).__hkPrints[0]);
  await closeDialog(page);
  await page.evaluate(() => localStorage.removeItem('home-keeper.labels'));
  return html;
}

test('capture QR code labels', async ({ page, context }) => {
  await page.setViewportSize({ width: DESKTOP.width, height: 900 });
  await page.evaluate(() => localStorage.removeItem('home-keeper.labels')).catch(() => {});
  const sheet = await listShots(page, '79-panel-qr-labels-button', '79b-panel-qr-labels-picker');
  await applianceShot(page, '79c-panel-qr-label-appliance', '79j-panel-qr-label-detail-button');
  await taskShot(page, '79d-panel-qr-label-task');

  // 79e. The sheet, as the browser prints it: page 1 of the document, at 96 dpi.
  const sheetPage = await context.newPage();
  await sheetPage.setViewportSize({ width: 820, height: 1130 });
  await sheetPage.setContent(sheet);
  await expect(sheetPage.locator('.label').first()).toBeVisible();
  await sheetPage.locator('.page').first().screenshot({ path: `${OUT}/79e-panel-qr-label-sheet.png` });
  await sheetPage.close();

  const roll = await rollShot(page, '79l-panel-qr-label-roll');
  // 79m. 1 roll label at 4 times its print size, so the shot is readable.
  const rollPage = await context.newPage();
  await rollPage.setViewportSize({ width: 800, height: 520 });
  await rollPage.setContent(roll);
  await rollPage.addStyleTag({ content: 'body{zoom:4;background:#ddd}.page{background:#fff}' });
  await expect(rollPage.locator('.label').first()).toBeVisible();
  await rollPage.locator('.page').first().screenshot({ path: `${OUT}/79m-panel-qr-label-roll-page.png` });
  await rollPage.close();

  await page.setViewportSize(PHONE);
  await listShots(page, '79f-panel-mobile-qr-labels-button', '79g-panel-mobile-qr-labels-picker');
  await applianceShot(
    page,
    '79h-panel-mobile-qr-label-appliance',
    '79k-panel-mobile-qr-label-detail-button',
  );
  await taskShot(page, '79i-panel-mobile-qr-label-task');
  await rollShot(page, '79n-panel-mobile-qr-label-roll');
  await page.setViewportSize(DESKTOP);
});
