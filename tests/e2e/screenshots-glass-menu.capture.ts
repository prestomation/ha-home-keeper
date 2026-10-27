/**
 * One-off screenshot capture of the Done menu under a glass theme (#497). Not part of
 * the e2e suite (the filename does not match *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images SHOT_PREFIX=after npx playwright test \
 *     --config=screenshots-glass-menu.config.ts
 *
 * SHOT_PREFIX is "before" on the code without the top-layer menu and "after" on the
 * code with it. The Liquid Glass Tinted theme is not installed: the capture adds the
 * card rules that cause the fault (a blur behind each card, and a clip).
 * It opens the Done menu on the task list and on the task page, at desktop and phone
 * width.
 */
import { test, expect, Page } from '@playwright/test';
import { TASK } from './fixture-ids';
import { DESKTOP, PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
const PREFIX = process.env.SHOT_PREFIX || 'after';

const GLASS = `
  ha-card {
    backdrop-filter: blur(20px) saturate(1.6);
    -webkit-backdrop-filter: blur(20px) saturate(1.6);
    overflow: hidden;
    background: rgba(255, 255, 255, 0.35);
  }
`;

async function gotoPanel(page: Page, path: string) {
  await page.goto(`/home-keeper${path}`, { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  await panel.locator('ha-card').first().waitFor({ state: 'attached' });
  await panel.evaluate((el, css) => {
    const style = document.createElement('style');
    style.textContent = css;
    el.shadowRoot!.appendChild(style);
    (el as HTMLElement).style.background =
      'linear-gradient(135deg, #5b8def 0%, #b06ab3 60%, #f0a56b 100%)';
  }, GLASS);
  return panel;
}

for (const [name, viewport, tag] of [
  ['desktop', DESKTOP, ''],
  ['phone', PHONE, 'mobile-'],
] as const) {
  test(`glass menu at ${name} width`, async ({ page }) => {
    await page.setViewportSize(viewport);

    let panel = await gotoPanel(page, '/tasks');
    const row = panel
      .locator('ha-card.hk-card')
      .filter({ has: page.locator('.hk-split-caret') })
      .first();
    await row.scrollIntoViewIfNeeded();
    await row.locator('.hk-split-caret').first().click();
    await expect(row.locator('.hk-defer-skip')).toBeVisible();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${OUT}/glass-menu-${tag}list-${PREFIX}.png` });

    panel = await gotoPanel(page, `/tasks/${TASK.waterFilter}`);
    await panel.locator('.hk-detail-actions .hk-split-caret').click();
    await expect(panel.locator('.hk-detail-actions .hk-defer-skip')).toBeVisible();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${OUT}/glass-menu-${tag}detail-${PREFIX}.png` });
  });
}
