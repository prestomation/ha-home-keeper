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
  await companions.screenshot({ path: `${OUT}/21b-panel-declarative-empty.png` });

  // 21c. The preset picker: one card per bundled recipe. Device Pulse is greyed out
  // and says which integration it needs, because the e2e container does not have it.
  await panel.locator('.hk-decl-preset').click();
  const picker = panel.locator('ha-dialog.hk-decl-picker');
  // `ha-dialog` portals its surface, so the host itself never reports visible —
  // wait on a node inside it, the way the specs do.
  await expect(picker.locator('.hk-decl-preset-card').first()).toBeVisible({ timeout: 20_000 });
  await expect(picker.locator('.hk-decl-preset-card')).toHaveCount(3);
  await expect(picker.locator('.hk-decl-preset-card.hk-decl-preset-disabled')).toHaveCount(1);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/21c-panel-declarative-preset-picker.png` });

  // 21d. The add dialog, seeded from Low battery (the one preset that needs no
  // upstream integration).
  //
  // `ha-dialog` caps its own height at the viewport, so at the default 720px the
  // four sections scroll inside the dialog and the preview — the whole point of the
  // shot — sits below that internal fold. Give the page enough room for the dialog
  // to lay out in full, then photograph the dialog surface rather than the page: at
  // this height a viewport shot would be mostly empty settings page.
  await page.setViewportSize({ width: 1280, height: 1800 });
  await picker.locator('.hk-decl-preset-card', { hasText: 'Low battery' }).click();
  const addDialog = panel.locator('ha-dialog.hk-decl-dialog');
  await expect(addDialog.locator('[data-decl-section="identity"]')).toBeVisible({
    timeout: 20_000,
  });
  // The count line replaces "Loading preview…" only once the backend has answered,
  // so wait for the text itself — a visible `.hk-decl-preview` is still the
  // placeholder.
  await expect(addDialog.locator('.hk-decl-preview-header')).toHaveText(/Showing \d+ of \d+/, {
    timeout: 20_000,
  });
  await page.waitForTimeout(600);
  // The native `<dialog>` inside `ha-dialog`'s (open) shadow root is the surface;
  // the `ha-dialog` host itself has no box of its own. Clip around that box rather
  // than screenshotting the element: `ha-form` lays its rows out a few pixels wider
  // than the dialog, so an element shot cuts the right edge off every toggle.
  const surface = await addDialog.locator('dialog').first().boundingBox();
  if (!surface) throw new Error('the add dialog has no rendered surface to photograph');
  const pad = 16;
  await page.screenshot({
    path: `${OUT}/21d-panel-declarative-add-dialog.png`,
    clip: {
      x: Math.max(0, surface.x - pad),
      y: Math.max(0, surface.y - pad),
      width: surface.width + pad * 2,
      height: surface.height + pad * 2,
    },
  });

  // Cancelled, not saved: the capture must leave the seeded store as it found it.
  await addDialog.locator('.hk-decl-cancel').click();
  await expect(panel.locator('ha-dialog[open]')).toHaveCount(0);
});
