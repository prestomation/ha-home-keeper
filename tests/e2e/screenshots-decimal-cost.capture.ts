/**
 * One-off screenshot capture for decimal cost fields (issue #539) — not part of the
 * e2e suite (the filename is not *.spec.ts). Run:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-decimal-cost.capture.ts \
 *     --config=screenshots-decimal-cost.config.ts
 *
 * Covers the spare part form with 3.99 typed in the cost box, desktop and phone.
 */
import { expect, test } from '@playwright/test';
import { ASSET } from './fixture-ids';
import { centre } from './shots';
import { PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

test('capture decimal part cost', async ({ page }) => {
  await page.goto(`/home-keeper/appliances/${ASSET.rainJacket}`, {
    waitUntil: 'domcontentloaded',
  });
  const panel = page.locator('home-keeper-panel').first();
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  await expect(panel.locator('.hk-detail-pane')).toBeVisible();
  await panel.locator('.d-edit').click();
  const form = panel.locator('#hk-asset-form');
  await expect(form).toBeVisible();
  const section = form
    .locator('details.hk-collapsible')
    .filter({ hasText: 'Parts & wear items' })
    .first();
  if ((await section.getAttribute('open')) === null) {
    await section.locator('summary').first().click();
  }
  await expect(section).toHaveAttribute('open', '');
  const part = form.locator('.hk-part').first();
  await part.scrollIntoViewIfNeeded();
  const cost = part.locator('input[type="number"]').first();
  await expect(cost).toBeVisible();
  await cost.fill('3.99');
  await expect(cost).toHaveValue('3.99');
  // The box reports itself valid: a whole-number step would mark 3.99 invalid.
  expect(await cost.evaluate((el) => (el as HTMLInputElement).validity.valid)).toBe(true);
  await centre(cost);
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/539-panel-part-decimal-cost.png` });

  await page.setViewportSize(PHONE);
  await centre(cost);
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/539-panel-mobile-part-decimal-cost.png` });
});
