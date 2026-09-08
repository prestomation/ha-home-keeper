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
import { callService, listTasks, openPanel, openSettingsSection } from './tests/helpers';
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
  await companions.screenshot({ path: `${OUT}/21-panel-companions.png` });

  // 21c. The preset picker: one card per bundled recipe. Device Pulse is greyed out
  // and says which integration it needs, because the e2e container does not have it.
  await panel.locator('.hk-decl-preset').click();
  const picker = panel.locator('ha-dialog.hk-decl-picker');
  // `ha-dialog` portals its surface, so the host itself never reports visible —
  // wait on a node inside it, the way the specs do.
  await expect(picker.locator('.hk-decl-preset-card').first()).toBeVisible({ timeout: 20_000 });
  await expect(picker.locator('.hk-decl-preset-card')).toHaveCount(2);
  await expect(picker.locator('.hk-decl-preset-card.hk-decl-preset-disabled')).toHaveCount(1);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/21c-panel-declarative-preset-picker.png` });

  // 21d. The add dialog, seeded from Firmware update available (the one preset that
  // needs no upstream integration).
  //
  // `ha-dialog` caps its own height at the viewport, so at the default 720px the
  // four sections scroll inside the dialog and the preview — the whole point of the
  // shot — sits below that internal fold. Give the page enough room for the dialog
  // to lay out in full, then photograph the dialog surface rather than the page: at
  // this height a viewport shot would be mostly empty settings page.
  await page.setViewportSize({ width: 1280, height: 1800 });
  await picker.locator('.hk-decl-preset-card', { hasText: 'Firmware update available' }).click();
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

/**
 * The page of a task a recipe built (issue #231).
 *
 * Its own test, and its own recipe, because it needs a *materialized* task and the
 * capture above deliberately saves nothing. The recipe is added over the service,
 * photographed, then deleted — which takes its task with it — so the container is
 * left exactly as it was found.
 *
 * `availability` on the always-present battery flag is the reporter's own case: the
 * entity is healthy, so the task stays dormant and the page reads Monitored. That is
 * the state that used to carry a Done button which recorded a completion and moved
 * nothing.
 */
test('capture a declarative-companion task page', async ({ page }) => {
  const created = await callService(
    'home_keeper',
    'add_declarative_companion',
    {
      // The recipe's name is the user's own label; this is the one the issue reports.
      name: 'Device Pulse',
      selection: { domain: 'binary_sensor', device_class: 'battery' },
      trigger: { mode: 'availability', for_seconds: 3600, clear_on_recover: true },
      task_template: { name_template: 'Check on {{ device_name or friendly_name }}' },
    },
    true,
  );
  const specId = created.companion.id as string;

  try {
    // The reconciler runs off a dispatched signal, so the task lands shortly after.
    const mine = async (): Promise<Array<Record<string, any>>> =>
      (await listTasks()).filter((t) => t.source?.declarative_companion?.spec_id === specId);
    await expect.poll(async () => (await mine()).length, { timeout: 30_000 }).toBe(1);
    const taskId = (await mine())[0].id as string;

    await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    // The notes editor carries the same class, so take the task card's own row.
    const actions = panel.locator('.hk-detail-actions').first();
    await expect(actions).toBeVisible({ timeout: 45_000 });

    // Everything the fix changed, asserted before the shot so a screenshot of the
    // wrong state cannot be committed. On a *materialized* task rather than a
    // hand-built fixture: the unit tests build `source.declarative_companion`
    // themselves, so only this one proves the reconciler writes the shape
    // `sourceOwnedTask` reads.
    await expect(actions.locator('.d-edit-recipe')).toBeVisible();
    await expect(actions.locator('.d-open-in')).toHaveCount(0);
    await expect(actions.locator('.d-done')).toHaveCount(0);
    // The recipe owns name, device, area and the binding, so the task's own Edit
    // and Delete are gone and Duplicate is greyed.
    await expect(actions.locator('.d-edit')).toHaveCount(0);
    await expect(actions.locator('.d-del')).toHaveCount(0);
    await expect(panel.locator('.hk-detail-card').first()).toContainText('Monitored');

    await page.mouse.move(0, 0);
    await page.waitForTimeout(400);
    await page.screenshot({
      path: `${OUT}/21e-panel-declarative-task-detail.png`,
      fullPage: true,
    });

    // 21g. The same task once the watcher arms it. This is the state the Monitored
    // shot cannot show: Done is greyed rather than absent, because the recipe
    // auto-clears and a hand-pressed Done would dismiss a condition that still
    // stands. It has to sit flush against the snooze caret — the blocked Done is a
    // wrapped button, and the split pill's rules only reached a bare one, so the
    // pair rendered as two controls with a seam between them.
    await callService('home_keeper', 'trigger_task', { task_id: taskId });
    await page.reload({ waitUntil: 'domcontentloaded' });
    const armed = panel.locator('.hk-detail-actions').first();
    await expect(armed.locator('.d-done-blocked-wrap')).toBeVisible({ timeout: 45_000 });
    await expect(armed.locator('.hk-split-caret')).toBeVisible();
    await expect(armed.locator('.d-done')).toHaveCount(0);
    // Both halves of the pill report the same height and share an edge.
    const pill = armed.locator('.hk-split-pill');
    const geom = await pill.evaluate((el) => {
      const done = el.querySelector('.hk-blocked-wrap ha-button') as HTMLElement;
      const caret = el.querySelector('.hk-split-caret') as HTMLElement;
      const a = done.getBoundingClientRect();
      const b = caret.getBoundingClientRect();
      return { dh: a.height, ch: b.height, gap: b.left - a.right };
    });
    expect(Math.abs(geom.dh - geom.ch), 'the two halves must be the same height').toBeLessThan(2);
    expect(Math.abs(geom.gap), 'the two halves must share an edge').toBeLessThan(2);
    await page.mouse.move(0, 0);
    await page.waitForTimeout(400);
    await page.screenshot({
      path: `${OUT}/21g-panel-declarative-task-armed.png`,
      fullPage: true,
    });

    // 21f. Edit recipe opens the recipe itself, over the task page. The dialog is
    // tall, so give it room and photograph its own surface (same treatment as 21d).
    await page.setViewportSize({ width: 1280, height: 1800 });
    await actions.locator('.d-edit-recipe').click();
    const dialog = panel.locator('ha-dialog.hk-decl-dialog');
    await expect(dialog.locator('[data-decl-section="identity"]')).toBeVisible({
      timeout: 20_000,
    });
    await expect(dialog.locator('.hk-decl-preview-header')).toHaveText(/Showing \d+ of \d+/, {
      timeout: 20_000,
    });
    await page.waitForTimeout(600);
    const surface = await dialog.locator('dialog').first().boundingBox();
    if (!surface) throw new Error('the recipe dialog has no rendered surface to photograph');
    const pad = 16;
    await page.screenshot({
      path: `${OUT}/21f-panel-declarative-recipe-dialog.png`,
      clip: {
        x: Math.max(0, surface.x - pad),
        y: Math.max(0, surface.y - pad),
        width: surface.width + pad * 2,
        height: surface.height + pad * 2,
      },
    });
    await dialog.locator('.hk-decl-cancel').click();
  } finally {
    await callService('home_keeper', 'delete_declarative_companion', { id: specId });
  }
});

/**
 * The recipe row in Settings → Companions, at both widths (the phone-layout fix).
 *
 * The row is the surface the maintainer reported: below 700px it kept the desktop's
 * single-line layout, the status and preset chips came out of their box over the Edit
 * button, and Delete went past the right edge with nothing to scroll. Seeded from a
 * *preset* on purpose — `preset_id` is what puts the long "Preset: device_pulse"
 * badge on the name line, which is the chip that did the covering.
 *
 * Both shots come from here rather than the main capture because only this file
 * creates a recipe, and it deletes it again so the container is left as it was found.
 * `tests/responsive-layout.spec.ts` asserts the layout; these only photograph it.
 */
test('capture the declarative recipe row at both widths', async ({ page }) => {
  const created = await callService(
    'home_keeper',
    'add_declarative_companion',
    {
      name: 'Device Pulse',
      preset_id: 'device_pulse',
      selection: { domain: 'binary_sensor', device_class: 'battery' },
      trigger: { mode: 'availability', for_seconds: 3600, clear_on_recover: true },
      task_template: { name_template: 'Check on {{ device_name or friendly_name }}' },
    },
    true,
  );
  const specId = created.companion.id as string;

  try {
    const panel = page.locator('home-keeper-panel').first();

    // 21h. The desktop row, where Edit and Delete sit beside the text. Shot as the
    // Companions card: the Settings page around it is four cards of other settings.
    await openPanel(page);
    await openSettingsSection(panel, 'companions');
    const companions = panel.locator('#hk-companions');
    await expect(companions).toBeVisible();
    const row = companions.locator('.hk-decl-row').first();
    await expect(row).toBeVisible();
    await expect(row.locator('.hk-decl-preset-chip')).toBeVisible();
    await expect(row.locator('.hk-decl-edit')).toBeVisible();
    await expect(row.locator('.hk-decl-delete')).toBeVisible();
    await centre(row);
    await page.waitForTimeout(500);
    await companions.screenshot({ path: `${OUT}/21h-panel-declarative-row-actions.png` });

    // 21i. The same row on a phone. The buttons take a line of their own under the
    // name, and both are on the screen at a size a thumb can hit.
    await page.setViewportSize({ width: 390, height: 844 });
    await openPanel(page);
    await openSettingsSection(panel, 'companions');
    await expect(companions).toBeVisible();
    const phoneRow = companions.locator('.hk-decl-row').first();
    await expect(phoneRow.locator('.hk-decl-delete')).toBeVisible();
    // Scroll to the *buttons*, not the row: the row's own top is on screen while its
    // action line is still under the bottom tab bar, which is exactly the half of the
    // fix the shot exists to show.
    await phoneRow.locator('.hk-companion-actions').scrollIntoViewIfNeeded();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/21i-panel-mobile-recipe-row.png` });
    await page.setViewportSize({ width: 1280, height: 720 });
  } finally {
    await callService('home_keeper', 'delete_declarative_companion', { id: specId });
  }
});
