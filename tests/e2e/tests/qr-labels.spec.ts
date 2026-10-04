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
    expect(html).toContain('<div class="l1">Garage water heater</div>');
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
    expect(html).toContain('Garage water heater');
    expect(html).toContain('Living room shades');
    expect(html).not.toContain('Rain jacket');

    // Clear unchecks every row again.
    await dialog.locator('[data-label-none]').click();
    await expect(print).toHaveText('Print 0 labels');
    await dialog.locator('[data-label-all]').click();
    await expect(dialog.locator('[data-label-pick]:checked')).toHaveCount(
      await dialog.locator('[data-label-pick]').count(),
    );
  });
});
