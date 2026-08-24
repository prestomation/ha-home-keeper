/**
 * Focused screenshot capture for the declarative-companions surface.
 *
 * The main ``screenshots.capture.ts`` walks every documented panel surface in
 * one big test — great for a complete refresh, brittle when a single earlier
 * step flakes. This standalone capture only touches Settings → Companions and
 * the declarative-companion add/preset dialogs, so a green run gives us the
 * three shots the PR needs even when other steps upstream are flaky.
 *
 * Run:
 *   CHROMIUM_EXEC=$(ls /opt/pw-browsers/chromium-*\/chrome-linux/chrome | head -1) \
 *     SHOT_DIR=../../docs/images \
 *     npx playwright test --config=screenshots-declarative.config.ts
 */
import { test, expect } from '@playwright/test';
import { openPanel } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

test('capture declarative-companion panel surfaces', async ({ page }) => {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await panel.locator('#tab-settings').click();
  await expect(panel.locator('#hk-companions')).toBeVisible();

  // Section header + empty-state row + Add / Add-from-preset buttons.
  await expect(panel.locator('.hk-companion-group-decl')).toBeVisible();
  await panel.locator('.hk-companion-group-decl').scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  await page.screenshot({
    path: `${OUT}/21b-panel-declarative-companions-empty.png`,
    fullPage: true,
  });

  // Preset picker modal (native <dialog> the panel appends inside its shadowRoot).
  await panel.locator('.hk-decl-preset').click();
  const picker = panel.locator('dialog.hk-decl-modal');
  await expect(picker).toBeVisible();
  await expect(picker.locator('.hk-decl-preset-card')).toHaveCount(3);
  await page.waitForTimeout(400);
  await page.screenshot({
    path: `${OUT}/21c-panel-declarative-preset-picker.png`,
    fullPage: true,
  });

  // Add dialog seeded from the Low Battery preset (no upstream integration
  // required). Live-preview panel visible on the right.
  await picker
    .locator('.hk-decl-preset-card')
    .filter({ hasText: /Low battery/i })
    .click();
  const addDlg = panel.locator('dialog.hk-decl-dialog');
  await expect(addDlg).toBeVisible();
  await expect(addDlg.locator('.hk-decl-preview')).toBeVisible();
  // Wait for the debounced preview poll.
  await page.waitForTimeout(1_500);
  await page.screenshot({
    path: `${OUT}/21d-panel-declarative-add-dialog.png`,
    fullPage: true,
  });
});
