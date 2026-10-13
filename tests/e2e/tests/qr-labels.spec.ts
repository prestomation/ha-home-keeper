import { readFileSync } from 'node:fs';
import { test, expect, Locator, Page } from '@playwright/test';
import { gotoTab, openAppliance, openPanel, trackPanelErrors } from './helpers';
import { ASSET, TASK } from '../fixture-ids';

/**
 * QR code labels (#428), end to end.
 *
 * A label is a QR code of a panel deep link. The spec checks the link in the dialog,
 * and the print document the panel hands the browser. The panel removes the hidden
 * print frame after `afterprint`, so each test records the frame's `srcdoc` with a
 * MutationObserver as it is added, before a print can remove it.
 *
 * The label size is kept per browser, so a test that changes it clears the key after.
 */

function labelDialog(panel: Locator): Locator {
  return panel.locator('ha-dialog.hk-label-dialog');
}

/** Record every print document the panel makes, in `window.__hkPrints`. */
async function watchPrints(page: Page): Promise<void> {
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
}

/**
 * The text of the first-line rows of each label in a print document. The panel
 * measures the text, so a long name can wrap over 2 or 3 rows.
 */
function firstLines(html: string): string[] {
  const labels = html.split(/class="(?:label|page)"/).slice(1);
  return labels
    .map((label) =>
      [...label.matchAll(/<div class="row l1" style="top:[\d.]+mm">([^<]*)<\/div>/g)]
        .map((m) => m[1])
        .join(' '),
    )
    .filter(Boolean);
}

async function prints(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as unknown as { __hkPrints: string[] }).__hkPrints);
}

test.describe('Home Keeper panel — QR labels', { tag: '@responsive' }, () => {
  test('the appliance page makes a label of its own deep link', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = await openAppliance(page, ASSET.waterHeater);
    await watchPrints(page);
    await panel.locator('.d-label').click();
    const dialog = labelDialog(panel);
    const link = dialog.locator('[data-label-link]');
    await expect(link).toBeVisible();
    const origin = await page.evaluate(() => location.origin);
    const url = `${origin}/home-keeper/appliances/${ASSET.waterHeater}`;
    await expect(link).toHaveValue(url);
    await expect(dialog.locator('.hk-label-qr svg')).toBeVisible();
    await expect(dialog.locator('[data-label-text] .hk-label-l1')).toHaveText('Garage water heater');
    await expect(dialog.locator('[data-label-text]')).toContainText('XE50T10HS45U0');

    // A text line the admin turns off leaves the preview and the print.
    await dialog.locator('[data-label-line="model"]').uncheck();
    await expect(dialog.locator('[data-label-text]')).not.toContainText('XE50T10HS45U0');

    const print = dialog.locator('[data-label-print]');
    await expect(print).toHaveText('Print 1 label');
    await print.click();
    await expect.poll(async () => (await prints(page)).length).toBe(1);
    const [html] = await prints(page);
    expect(firstLines(html)).toEqual(['Garage water heater']);
    expect(html).not.toContain('XE50T10HS45U0');
    // The sheet is the whole document the browser prints, with the sheet size set.
    expect(html).toMatch(/@page\{size:(letter|A4);margin:0\}/);
    expect(html.match(/class="label"/g)).toHaveLength(1);

    // Put the text choice back: it is kept per browser.
    await dialog.locator('[data-label-line="model"]').check();
    expect(errors).toEqual([]);
  });

  test('the task page makes a label of the task link', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator(`.detail-open[data-detail-id="${TASK.fridgeFilter}"]`).click();
    await expect(panel.locator('.hk-detail-title')).toBeVisible();
    await panel.locator('.d-label').click();
    const origin = await page.evaluate(() => location.origin);
    await expect(labelDialog(panel).locator('[data-label-link]')).toHaveValue(
      `${origin}/home-keeper/tasks/${TASK.fridgeFilter}`,
    );
    // Close leaves the page as it was.
    await labelDialog(panel).locator('[data-label-close]').click();
    await expect(labelDialog(panel)).toHaveCount(0);
    await expect(panel.locator('.hk-detail-title')).toBeVisible();
  });

  test('Print labels prints only the checked appliances, and their tasks on request', async ({
    page,
  }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await gotoTab(panel, 'appliances');
    await watchPrints(page);
    await panel.locator('#labels-btn').click();
    const dialog = labelDialog(panel);
    const print = dialog.locator('[data-label-print]');
    // Nothing starts checked, so the print starts empty.
    await expect(dialog.locator('[data-label-pick]').first()).toBeVisible();
    await expect(print).toHaveText('Print 0 labels');
    await expect(print).toHaveAttribute('disabled', '');

    await dialog.locator(`[data-label-pick="${ASSET.waterHeater}"]`).check();
    await dialog.locator(`[data-label-pick="${ASSET.shades}"]`).check();
    await expect(print).toHaveText('Print 2 labels');
    await expect(print).not.toHaveAttribute('disabled', '');

    // With the tasks, each appliance's tasks join the print.
    await dialog.locator('[data-label-with-tasks]').check();
    await expect(print).not.toHaveText('Print 2 labels');
    const withTasks = Number((await print.textContent())?.match(/\d+/)?.[0]);
    expect(withTasks).toBeGreaterThan(2);
    await dialog.locator('[data-label-with-tasks]').uncheck();
    await expect(print).toHaveText('Print 2 labels');

    await print.click();
    await expect.poll(async () => (await prints(page)).length).toBe(1);
    const [html] = await prints(page);
    expect(html.match(/class="label"/g)).toHaveLength(2);
    expect(firstLines(html).sort()).toEqual(['Garage water heater', 'Living room shades']);
    expect(html).not.toContain('Rain jacket');

    // Clear unchecks every row again.
    await dialog.locator('[data-label-none]').click();
    await expect(print).toHaveText('Print 0 labels');
    await dialog.locator('[data-label-all]').click();
    await expect(dialog.locator('[data-label-pick]:checked')).toHaveCount(
      await dialog.locator('[data-label-pick]').count(),
    );
  });

  test('a label roll prints 1 page per label and saves the whole label as a PNG', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = await openAppliance(page, ASSET.waterHeater);
    await watchPrints(page);
    try {
      await panel.locator('.d-label').click();
      const dialog = labelDialog(panel);
      const skip = dialog.locator('[data-label-skip-field]');
      const rotate = dialog.locator('[data-label-rotate-field]');
      const custom = dialog.locator('[data-label-custom-field]');
      // A sheet skips used labels and does not turn.
      await expect(skip).toBeVisible();
      await expect(rotate).toBeHidden();
      await expect(custom).toHaveCount(2);
      await expect(custom.first()).toBeHidden();

      await dialog.locator('[data-label-paper]').selectOption('roll_50x30');
      await expect(skip).toBeHidden();
      await expect(rotate).toBeVisible();
      await expect(custom.first()).toBeHidden();
      await expect(dialog.locator('[data-label-hint]')).toContainText('Save as PDF');

      await dialog.locator('[data-label-print]').click();
      await expect.poll(async () => (await prints(page)).length).toBe(1);
      let [html] = await prints(page);
      expect(html).toContain('@page{size:50mm 30mm;margin:0}');
      expect(html.match(/class="page"/g)).toHaveLength(1);
      expect(firstLines(html)).toEqual(['Garage water heater']);

      // A custom size and the rotation reach the print.
      await dialog.locator('[data-label-paper]').selectOption('roll_custom');
      await expect(custom.first()).toBeVisible();
      await dialog.locator('[data-label-custom-w]').fill('62');
      await dialog.locator('[data-label-custom-w]').press('Tab');
      await dialog.locator('[data-label-custom-h]').fill('5');
      await dialog.locator('[data-label-custom-h]').press('Tab');
      // Below the 10 mm minimum: the field shows the size that prints.
      await expect(dialog.locator('[data-label-custom-h]')).toHaveValue('10');
      await dialog.locator('[data-label-custom-h]').fill('29');
      await dialog.locator('[data-label-custom-h]').press('Tab');
      await dialog.locator('[data-label-rotate]').check();
      await dialog.locator('[data-label-print]').click();
      await expect.poll(async () => (await prints(page)).length).toBe(2);
      html = (await prints(page))[1];
      expect(html).toContain('@page{size:29mm 62mm;margin:0}');
      expect(html).toContain('rotate(90deg)');

      // The PNG is the label at 203 dpi, turned: 29 × 62 mm is 232 × 496 dots.
      await dialog.locator('[data-label-rotate]').uncheck();
      await dialog.locator('[data-label-paper]').selectOption('roll_50x30');
      const [download] = await Promise.all([
        page.waitForEvent('download'),
        dialog.locator('[data-label-png]').click(),
      ]);
      expect(download.suggestedFilename()).toBe('home-keeper-appliance-garage-water-heater.png');
      const png = readFileSync((await download.path())!);
      expect(png.subarray(1, 4).toString('ascii')).toBe('PNG');
      // The IHDR chunk holds the width and the height: 50 × 30 mm at 8 dots per mm.
      expect(png.readUInt32BE(16)).toBe(400);
      expect(png.readUInt32BE(20)).toBe(240);

      await dialog.locator('[data-label-dpi]').selectOption('300');
      const [download300] = await Promise.all([
        page.waitForEvent('download'),
        dialog.locator('[data-label-png]').click(),
      ]);
      const png300 = readFileSync((await download300.path())!);
      expect(png300.readUInt32BE(16)).toBe(591);
      expect(png300.readUInt32BE(20)).toBe(354);
      expect(errors).toEqual([]);
    } finally {
      await page.evaluate(() => localStorage.removeItem('home-keeper.labels'));
    }
  });
});

test.describe('Home Keeper panel — QR label text position and base address', {
  tag: '@responsive',
}, () => {
  test('a 24 x 24 mm roll prints its text below the code when asked', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = await openAppliance(page, ASSET.waterHeater);
    await watchPrints(page);
    try {
      await panel.locator('.d-label').click();
      const dialog = labelDialog(panel);
      const field = dialog.locator('[data-label-text-pos-field]');
      // A sheet keeps its fixed layout, so the field shows for a roll only.
      await expect(field).toBeHidden();
      await dialog.locator('[data-label-paper]').selectOption('roll_custom');
      await expect(field).toBeVisible();
      for (const [sel, mm] of [['[data-label-custom-w]', '24'], ['[data-label-custom-h]', '24']]) {
        await dialog.locator(sel).fill(mm);
        await dialog.locator(sel).press('Tab');
      }
      const preview = dialog.locator('[data-label-preview]');
      await expect(preview).toHaveAttribute('data-fit', 'code');
      await dialog.locator('[data-label-print]').click();
      await expect.poll(async () => (await prints(page)).length).toBe(1);
      expect(firstLines((await prints(page))[0])).toEqual([]);

      await dialog.locator('[data-label-text-pos]').selectOption('below');
      await expect(preview).toHaveAttribute('data-fit', 'below');
      await dialog.locator('[data-label-print]').click();
      await expect.poll(async () => (await prints(page)).length).toBe(2);
      const html = (await prints(page))[1];
      expect(html).toContain('class="text below"');
      expect(firstLines(html).join(' ')).toContain('Garage');
      expect(errors).toEqual([]);
    } finally {
      await page.evaluate(() => localStorage.removeItem('home-keeper.labels'));
    }
  });

  test('the dialog names the base address and warns that it is not HTTPS', async ({ page }) => {
    await openPanel(page);
    const panel = await openAppliance(page, ASSET.waterHeater);
    await panel.locator('.d-label').click();
    const dialog = labelDialog(panel);
    // The test instance has no external URL and serves plain HTTP.
    await expect(dialog.locator('[data-label-base]')).toBeVisible();
    await expect(dialog.locator('[data-label-not-https]')).toBeVisible();
    await expect(dialog.locator('[data-label-app-warning]')).toHaveCount(0);
  });
});

test.describe('Home Keeper panel — QR labels in the Home Assistant app', () => {
  test.use({ userAgent: 'Mozilla/5.0 (Linux; Android 14) Chrome/130.0 Home Assistant/2025.4.1' });

  test('the dialog warns that print and download can fail', async ({ page }) => {
    await openPanel(page);
    const panel = await openAppliance(page, ASSET.waterHeater);
    await panel.locator('.d-label').click();
    const warning = labelDialog(panel).locator('[data-label-app-warning]');
    await expect(warning).toBeVisible();
    await expect(warning).toContainText('Copy link');
  });
});

test.describe('Home Keeper panel — QR labels from the task list', () => {
  test('the task picker lists the tasks that the list shows', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await gotoTab(panel, 'tasks');
    const listed = async (): Promise<string[]> =>
      (
        await panel
          .locator('#hk-list .detail-open[data-detail-kind="task"]')
          .evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.detailId ?? ''))
      ).sort();
    const picked = async (): Promise<string[]> => {
      await panel.locator('#labels-btn').click();
      const dialog = labelDialog(panel);
      await expect(dialog.locator('[data-label-pick]').first()).toBeVisible();
      const ids = await dialog
        .locator('[data-label-pick]')
        .evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.labelPick ?? ''));
      await dialog.locator('[data-label-close]').click();
      await expect(dialog).toHaveCount(0);
      return ids.sort();
    };
    const all = await listed();
    expect(all.length).toBeGreaterThan(1);
    expect(await picked()).toEqual(all);

    await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="overdue"]').click();
    await expect.poll(async () => (await listed()).length).toBeLessThan(all.length);
    const overdue = await listed();
    expect(overdue.length).toBeGreaterThan(0);
    expect(await picked()).toEqual(overdue);
    await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="all"]').click();
  });
});
