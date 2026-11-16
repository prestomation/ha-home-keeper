/**
 * One-off screenshot capture for the stale draft fix. Not part of the e2e suite (the
 * filename is not *.spec.ts). Run:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-stale-draft.capture.ts \
 *     --config=screenshots-stale-draft.config.ts
 *
 * Opens the New task form, closes it, opens it again, and types a name. The form stays
 * open with the text. Desktop and phone.
 */
import { expect, test } from '@playwright/test';
import { PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

test('capture the New task form after a reopen', async ({ page }) => {
  await page.goto('/home-keeper/tasks', { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  await panel.locator('#add-btn').click();
  const form = panel.locator('#hk-task-form-basics');
  await expect(form).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(form).toHaveCount(0);
  await panel.locator('#add-btn').click();
  await expect(form).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/stale-draft-panel-task-form.png` });

  await page.setViewportSize(PHONE);
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/stale-draft-panel-mobile-task-form.png` });
});
