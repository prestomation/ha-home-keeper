/**
 * One-off screenshot capture for counted wear items (issue #306) — not part of the
 * e2e suite (the filename is not *.spec.ts). Run:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-counted.capture.ts \
 *     --config=screenshots-counted.config.ts
 *
 * Covers the 3 changed surfaces, desktop and phone:
 *  61 / 61c.  The Tasks list Counted section, and its scope pill. A use task has no
 *             due date, so the "17 of 25 wears" chip is the only thing on the row.
 *  62 / 62c.  The part editor with the unit set to uses, which is what reveals the
 *             counting fields below it.
 *  63 / 63c.  The appliance page's part row, with the live count and its meter.
 *
 * Its own file rather than steps inside `screenshots.capture.ts` for the reason the
 * NFC and card captures have theirs: that walk photographs ~60 surfaces in one
 * sequence, so a shot near the end costs a 15-minute run to re-take and inherits
 * every state change the steps before it made.
 */
import { expect, test } from '@playwright/test';
import { ASSET, TASK } from './fixture-ids';
import { PHONE } from './viewports';
import { openPanel } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

/** Open an appliance's edit drawer, expanded on its parts. */
async function openPartEditor(page: import('@playwright/test').Page) {
  await page.goto(`/home-keeper/appliances/${ASSET.rainJacket}`, {
    waitUntil: 'domcontentloaded',
  });
  const panel = page.locator('home-keeper-panel').first();
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  await expect(panel.locator('.hk-detail-pane')).toBeVisible();
  await panel.locator('.d-edit').click();
  const form = panel.locator('#hk-asset-form');
  await expect(form).toBeVisible();
  // Opened only if it is shut. An appliance with a single part opens this section
  // itself, so an unconditional click *collapses* it — which is how the first version
  // of shot 62 came back showing a drawer scrolled past a closed section.
  const section = form
    .locator('details.hk-collapsible')
    .filter({ hasText: 'Parts & wear items' })
    .first();
  if ((await section.getAttribute('open')) === null) {
    await section.locator('summary').first().click();
  }
  await expect(section).toHaveAttribute('open', '');
  return { panel, form };
}

test('capture counted wear items', async ({ page }) => {
  // ── 61. The Counted section and its pill ────────────────────────────────────
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  // Dismiss the first-run banner if it is up. Dismissal persists per user, so on a
  // fresh container it is there and on a re-run it is not — hence the count check
  // rather than a wait. Left standing it fills a phone viewport and pushes the row
  // this capture is about down under the floating Add button.
  const intro = panel.locator('ha-button.hk-intro-dismiss');
  if ((await intro.count()) > 0) {
    await intro.click();
    await expect(panel.locator('.hk-intro')).toHaveCount(0);
  }
  await panel
    .locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="counted"]')
    .click();
  const row = panel.locator(`ha-card.hk-card[data-id="${TASK.wearJacket}"]`);
  await expect(row).toBeVisible();
  await expect(row).toContainText('of 25 wears');
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/61-panel-counted-tasks.png`, fullPage: true });

  // ── 62. The part editor, with the counting fields revealed ──────────────────
  {
    const { form } = await openPartEditor(page);
    const part = form.locator('.hk-part').first();
    // Frame on a counting field, not on the part row: the fields are what the shot
    // documents, and a shot taken before they render documents nothing.
    // No `scrollIntoViewIfNeeded` on the field itself: the dependent form re-renders
    // as it settles and detaches the matched node between resolving it and acting on
    // it. Scroll the part row, which is stable, and wait for the field to be visible.
    const noun = part.getByText('Count uses as', { exact: true }).filter({ visible: true }).first();
    await expect(noun).toBeVisible();
    await part.scrollIntoViewIfNeeded();
    await page.waitForTimeout(800);
    // A nudge further down the drawer, so the Time limit switch is in frame with the
    // rest. The drawer scrolls its own content, so this is a wheel over it rather
    // than a scroll on an element — and it is the last of the 3 counting controls,
    // which the README names alongside the other 2.
    await page.mouse.move(1040, 500);
    await page.mouse.wheel(0, 240);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/62-panel-counted-part-editor.png` });
    await page.keyboard.press('Escape');
  }

  // ── 63. The appliance part row: the count and its meter ─────────────────────
  await page.goto(`/home-keeper/appliances/${ASSET.rainJacket}`, {
    waitUntil: 'domcontentloaded',
  });
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  await panel.locator('.hk-subtab[data-tab="parts"]').click();
  await expect(panel.locator('.hk-use-meter').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/63-panel-counted-part-row.png`, fullPage: true });

  // ── The phone layout, which is a different layout and not a narrower one ─────
  await page.setViewportSize(PHONE);

  // 61c. Below 700px the scope pills come apart into wrapping chips, so Counted sits
  // on a row of its own, and the count chip shares a much narrower row with the name.
  await openPanel(page);
  if ((await intro.count()) > 0) {
    await intro.click();
    await expect(panel.locator('.hk-intro')).toHaveCount(0);
  }
  await panel
    .locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="counted"]')
    .click();
  await expect(row).toBeVisible();
  await expect(row).toContainText('of 25 wears');
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/61c-panel-mobile-counted-tasks.png` });

  // 62c. The part editor on a phone, where the field grids stack to one column.
  {
    const { form } = await openPartEditor(page);
    const part = form.locator('.hk-part').first();
    const noun = part.getByText('Count uses as', { exact: true }).filter({ visible: true }).first();
    await expect(noun).toBeVisible();
    await part.scrollIntoViewIfNeeded();
    await page.waitForTimeout(800);
    // Same nudge as the desktop shot, further because the fields stack to one column
    // here: without it the frame spends its top third on the stock fields above.
    await page.mouse.move(195, 500);
    await page.mouse.wheel(0, 430);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/62c-panel-mobile-counted-part-editor.png` });
    await page.keyboard.press('Escape');
  }

  // 63c. The part row on a phone, where the row stacks and the meter has to keep its
  // width without pushing the chips off the edge.
  await page.goto(`/home-keeper/appliances/${ASSET.rainJacket}`, {
    waitUntil: 'domcontentloaded',
  });
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  await panel.locator('.hk-subtab[data-tab="parts"]').click();
  await expect(panel.locator('.hk-use-meter').first()).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/63c-panel-mobile-counted-part-row.png` });
});
