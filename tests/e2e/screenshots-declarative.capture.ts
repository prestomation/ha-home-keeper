/**
 * Focused screenshot capture for the declarative-companions surface.
 *
 * The main ``screenshots.capture.ts`` walks every documented panel surface in one big
 * test — great for a complete refresh, brittle when a single earlier step flakes.
 * This standalone capture only touches Settings → Companions and the two
 * declarative-companion dialogs, so a green run gives us the three shots the PR needs
 * even when other steps upstream are flaky.
 *
 * Both dialogs are `ha-dialog`s, which centre themselves in the **viewport**. The
 * Settings page is several screens tall, so a `fullPage: true` capture would grow the
 * page around a dialog pinned near the top and photograph mostly empty cards — the
 * two dialog shots are therefore viewport captures, and the subsection shot is the
 * Companions card on its own.
 *
 * Run:
 *   CHROMIUM_EXEC=$(ls /opt/pw-browsers/chromium-*\/chrome-linux/chrome | head -1) \
 *     SHOT_DIR=../../docs/images \
 *     npx playwright test --config=screenshots-declarative.config.ts
 */
import { test, expect } from '@playwright/test';
import { openPanel, openSettingsSection } from './tests/helpers';
import { centre } from './shots';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

test('capture declarative-companion panel surfaces', async ({ page }) => {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();

  await openSettingsSection(panel, 'companions');
  const companions = panel.locator('#hk-companions');
  await expect(companions).toBeVisible();

  // 21b. The subsection at the foot of the Companions card: heading, help, the two
  // Add buttons, and the empty-state line. Shot as the card rather than the page —
  // the Settings page above it is four cards of unrelated settings.
  const group = companions.locator('.hk-companion-group-decl');
  await expect(group).toBeVisible();
  await centre(group);
  await page.mouse.move(0, 0);
  await page.waitForTimeout(500);
  await companions.screenshot({ path: `${OUT}/21b-panel-declarative-companions-empty.png` });

  // 21c. The preset picker: one card per bundled recipe. Device Pulse is greyed out
  // and says which integration it needs, because the e2e container does not have it.
  await panel.locator('.hk-decl-preset').click();
  const picker = panel.locator('ha-dialog.hk-decl-picker');
  await expect(picker).toBeVisible();
  await expect(picker.locator('.hk-decl-preset-card')).toHaveCount(3);
  await expect(picker.locator('.hk-decl-preset-card.hk-decl-preset-disabled')).toHaveCount(1);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/21c-panel-declarative-preset-picker.png` });

  // 21d. The add dialog, seeded from Low battery (the one preset that needs no
  // upstream integration). The preview under the form counts the entities the recipe
  // would turn into tasks, so wait for its header rather than for a fixed delay.
  await picker.locator('.hk-decl-preset-card', { hasText: 'Low battery' }).click();
  const addDialog = panel.locator('ha-dialog.hk-decl-dialog');
  await expect(addDialog).toBeVisible();
  await expect(addDialog.locator('.hk-decl-preview')).toBeVisible();
  await expect(addDialog.locator('.hk-decl-preview-header')).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/21d-panel-declarative-add-dialog.png` });

  // Cancelled, not saved: the capture must leave the seeded store as it found it.
  await addDialog.locator('.hk-decl-cancel').click();
  await expect(panel.locator('ha-dialog[open]')).toHaveCount(0);
});
