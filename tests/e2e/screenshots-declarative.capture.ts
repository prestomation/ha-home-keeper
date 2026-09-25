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
import { PHONE } from './viewports';

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

  // 21c. The preset picker: one card per bundled preset. Device Pulse is greyed out
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
 * The page of a task a declarative companion built (issue #231).
 *
 * Its own test, and its own companion, because it needs a *materialized* task and the
 * capture above deliberately saves nothing. The companion is added over the service,
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
      // The companion's name is the user's own label; this is the one the issue reports.
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
    await expect(actions.locator('.d-edit-companion')).toBeVisible();
    await expect(actions.locator('.d-edit-companion')).toHaveText('Edit companion');
    await expect(actions.locator('.d-open-in')).toHaveCount(0);
    await expect(actions.locator('.d-done')).toHaveCount(0);
    // The companion owns name, device, area and the binding. The task's own Edit
    // stays for the fields it leaves free, Delete is gone and Duplicate is greyed.
    await expect(actions.locator('.d-edit')).toHaveCount(1);
    await expect(actions.locator('.d-del')).toHaveCount(0);
    await expect(panel.locator('.hk-detail-card').first()).toContainText('Monitored');

    await page.mouse.move(0, 0);
    await page.waitForTimeout(400);
    await page.screenshot({
      path: `${OUT}/21e-panel-declarative-task-detail.png`,
      fullPage: true,
    });

    // 21g. The same task once the watcher arms it. This is the state the Monitored
    // shot cannot show: Done is greyed rather than absent, because the companion
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

    // 21f. Edit companion opens the companion itself, over the task page. The dialog
    // is tall, so give it room and photograph its own surface (same treatment as 21d).
    // The companion has a device class, so More filters opens and the dialog grows by
    // the filter and exclusion pickers (#373).
    await page.setViewportSize({ width: 1280, height: 2600 });
    await actions.locator('.d-edit-companion').click();
    const dialog = panel.locator('ha-dialog.hk-decl-dialog');
    await expect(dialog.locator('[data-decl-section="identity"]')).toBeVisible({
      timeout: 20_000,
    });
    await expect(dialog.locator('.hk-decl-preview-header')).toHaveText(/Showing \d+ of \d+/, {
      timeout: 20_000,
    });
    await page.waitForTimeout(600);
    const surface = await dialog.locator('dialog').first().boundingBox();
    if (!surface) throw new Error('the companion dialog has no rendered surface to photograph');
    const pad = 16;
    await page.screenshot({
      path: `${OUT}/21f-panel-declarative-companion-dialog.png`,
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
 * The declarative companion row in Settings → Companions, at both widths (the
 * phone-layout fix).
 *
 * The row is the surface the maintainer reported: below 700px it kept the desktop's
 * single-line layout, the status and preset chips came out of their box over the Edit
 * button, and Delete went past the right edge with nothing to scroll. Seeded from a
 * *preset* on purpose — `preset_id` is what puts the long "Preset: device_pulse"
 * badge on the name line, which is the chip that did the covering.
 *
 * Both shots come from here rather than the main capture because only this file
 * creates a companion, and it deletes it again so the container is left as it was found.
 * `tests/responsive-layout.spec.ts` asserts the layout; these only photograph it.
 */
test('capture the declarative companion row at both widths', async ({ page }) => {
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
    await page.setViewportSize(PHONE);
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
    await page.screenshot({ path: `${OUT}/21i-panel-mobile-declarative-row.png` });
    await page.setViewportSize({ width: 1280, height: 720 });
  } finally {
    await callService('home_keeper', 'delete_declarative_companion', { id: specId });
  }
});

/**
 * The declarative companion dialog's More filters block and the preview's Exclude
 * button (#373), at both widths.
 *
 * The companion watches every demo binary sensor, so the preview has several rows. One
 * row is excluded with its own Exclude button, which is the flow the shots document:
 * the entity leaves the matches, shows under them with Include, and lands in the
 * Excluded entities picker above. The companion is added over the service and deleted
 * again, so the container is left as it was found.
 */
test('capture the companion filters and exclusions at both widths', async ({ page }) => {
  const created = await callService(
    'home_keeper',
    'add_declarative_companion',
    {
      name: 'Low battery',
      selection: { domain: 'binary_sensor', entity_regex: 'binary_sensor\\.hk_demo_.*' },
      trigger: { mode: 'state', state: 'on', clear_on_recover: true },
      task_template: { name_template: 'Check {{ friendly_name }}' },
    },
    true,
  );
  const specId = created.companion.id as string;

  const openCompanion = async () => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await openSettingsSection(panel, 'companions');
    await panel.locator(`.hk-decl-row[data-spec-id="${specId}"] .hk-decl-edit`).click();
    const dialog = panel.locator('ha-dialog.hk-decl-dialog');
    await expect(dialog.locator('[data-decl-section="identity"]')).toBeVisible({
      timeout: 20_000,
    });
    await expect(dialog.locator('.hk-decl-preview-header')).toHaveText(/Showing \d+ of \d+/, {
      timeout: 20_000,
    });
    // The regex is under More filters, so the row is open on this companion.
    await expect(dialog.locator('.hk-decl-more')).toHaveAttribute('aria-expanded', 'true');
    await dialog.locator('.hk-decl-exclude').first().click();
    await expect(dialog.locator('.hk-decl-excluded-head')).toHaveText('1 entity excluded', {
      timeout: 20_000,
    });
    return dialog;
  };

  try {
    // 21j. Desktop. Tall enough for the whole dialog to lay out, then clipped to the
    // dialog surface, the same way 21d is.
    await page.setViewportSize({ width: 1280, height: 2600 });
    const dialog = await openCompanion();
    await page.mouse.move(0, 0);
    await page.waitForTimeout(600);
    const surface = await dialog.locator('dialog').first().boundingBox();
    if (!surface) throw new Error('the companion dialog has no rendered surface to photograph');
    const pad = 16;
    await page.screenshot({
      path: `${OUT}/21j-panel-declarative-filters.png`,
      clip: {
        x: Math.max(0, surface.x - pad),
        y: Math.max(0, surface.y - pad),
        width: surface.width + pad * 2,
        height: surface.height + pad * 2,
      },
    });
    await dialog.locator('.hk-decl-cancel').click();

    // 21k. A phone. The dialog fills the screen and scrolls; scroll to the preview,
    // where each row has an icon-only Exclude button and the excluded entity is listed
    // with Include.
    await page.setViewportSize(PHONE);
    const phoneDialog = await openCompanion();
    await phoneDialog.locator('.hk-decl-preview').scrollIntoViewIfNeeded();
    // The click leaves the pointer over the next row's button; move it off, so the
    // shot shows the buttons at rest rather than one in its hover state.
    await page.mouse.move(0, 0);
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/21k-panel-mobile-declarative-filters.png` });
    await phoneDialog.locator('.hk-decl-cancel').click();
    await page.setViewportSize({ width: 1280, height: 720 });
  } finally {
    await callService('home_keeper', 'delete_declarative_companion', { id: specId });
  }
});

/**
 * The template trigger mode, at both widths and in both of its states (issue #346).
 *
 * The verdict chips are the whole point of the shots. A template is the one condition
 * a user cannot check by reading it — `{{ state > 24 }}` against a string state
 * renders false forever and opens nothing — so the preview renders it per sampled
 * entity and each row says what it got. A shot of the box alone would document none
 * of that.
 *
 * Seeded over the service and deleted again, like the captures above: a companion saved
 * by the dialog would leave tasks behind in the container the other specs read.
 */
test('capture the template trigger at both widths', async ({ page }) => {
  // Two seeded entities that land on opposite sides of the template, so the preview
  // carries both chips rather than a column of one. A single-verdict shot documents
  // half of what the chips are for.
  const created = await callService(
    'home_keeper',
    'add_declarative_companion',
    {
      name: 'Service hours',
      selection: {
        domain: 'sensor',
        entity_regex: 'sensor\\.(demo_printer_hours|e2e_battery_device_battery)',
      },
      trigger: {
        mode: 'template',
        template: '{{ state | float(0) >= 500 }}',
        clear_on_recover: true,
      },
      task_template: { name_template: 'Service {{ device_name or friendly_name }}' },
    },
    true,
  );
  const specId = created.companion.id as string;

  try {
    const panel = page.locator('home-keeper-panel').first();
    // Room for the dialog to lay out in full: `ha-dialog` caps itself at the viewport,
    // and at 720px the preview — the point of the shot — falls below its inner fold.
    await page.setViewportSize({ width: 1280, height: 2600 });
    await openPanel(page);
    await openSettingsSection(panel, 'companions');
    const companions = panel.locator('#hk-companions');
    await expect(companions).toBeVisible();
    await companions.locator('.hk-decl-row').first().locator('.hk-decl-edit').click();

    const dialog = panel.locator('ha-dialog.hk-decl-dialog');
    await expect(dialog.locator('[data-decl-section="trigger"]')).toBeVisible({
      timeout: 20_000,
    });
    // The verdict summary replaces the plain one only once the backend has rendered
    // the template, so wait on the "N are due now" wording rather than on the box.
    await expect(dialog.locator('.hk-decl-preview-header')).toHaveText(/1 of these are due now/, {
      timeout: 20_000,
    });
    // Asserted before the shot, so a screenshot of the wrong state cannot be
    // committed: one row each way, and no error.
    await expect(dialog.locator('.hk-decl-preview-row')).toHaveCount(2);
    await expect(dialog.locator('.hk-decl-chip.due')).toHaveCount(1);
    await expect(dialog.locator('.hk-decl-chip.quiet')).toHaveCount(1);
    await expect(dialog.locator('.hk-decl-template-error')).toHaveCount(0);

    await page.mouse.move(0, 0);
    await page.waitForTimeout(600);
    const shoot = async (name: string): Promise<void> => {
      const surface = await dialog.locator('dialog').first().boundingBox();
      if (!surface) throw new Error('the companion dialog has no rendered surface');
      const pad = 16;
      await page.screenshot({
        path: `${OUT}/${name}`,
        clip: {
          x: Math.max(0, surface.x - pad),
          y: Math.max(0, surface.y - pad),
          width: surface.width + pad * 2,
          height: surface.height + pad * 2,
        },
      });
    };
    await shoot('21j-panel-template-trigger.png');

    // 21k. The same dialog with a template that cannot render. This is the state the
    // shot above cannot show, and the reason the chips exist: one alert carrying the
    // Jinja message, and an Error chip on every row.
    const box = dialog.locator('[data-decl-section="trigger"] textarea').first();
    await box.fill('{{ stat | float(0) >= 500 }}');
    await box.blur();
    await expect(dialog.locator('.hk-decl-template-error')).toBeVisible({ timeout: 20_000 });
    await expect(dialog.locator('.hk-decl-chip.bad')).toHaveCount(2);
    await page.mouse.move(0, 0);
    await page.waitForTimeout(600);
    await shoot('21k-panel-template-trigger-error.png');

    // Put the working template back, so the phone shot below photographs the state a
    // reader is meant to learn from.
    await box.fill('{{ state | float(0) >= 500 }}');
    await box.blur();
    await expect(dialog.locator('.hk-decl-chip.due')).toHaveCount(1, { timeout: 20_000 });

    // The phone layout, in two shots. The dialog is far taller than a phone, and the
    // change has two halves that cannot share a screen: the Jinja box near the top and
    // the verdict chips at the bottom. One shot would document whichever half it
    // happened to frame.
    await page.setViewportSize(PHONE);
    await page.waitForTimeout(400);

    // 21l. The chips, where the layout actually differs: the chip keeps its own column
    // and the task name wraps under itself rather than pushing the chip off the edge.
    await dialog.locator('.hk-decl-preview').scrollIntoViewIfNeeded();
    await expect(dialog.locator('.hk-decl-chip').first()).toBeVisible();
    await page.mouse.move(0, 0);
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/21l-panel-mobile-template-trigger.png` });

    // 21m. The trigger section itself: the Template mode, the Jinja box, and the
    // helper line naming what a template can read.
    await dialog.locator('[data-decl-section="trigger"]').scrollIntoViewIfNeeded();
    await expect(box).toBeVisible();
    await page.mouse.move(0, 0);
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/21m-panel-mobile-template-field.png` });

    // 21n / 21o. The box a user has not written yet, at both widths. This is the first
    // thing anyone picking Template mode sees, and it used to be a red
    // `sensor.template is required` with no match list under it. The match list is the
    // point of the shot: the preview says what the companion covers before the template
    // decides anything.
    await box.fill('');
    await box.blur();
    await expect(dialog.locator('.hk-decl-template-hint')).toBeVisible({ timeout: 20_000 });
    await expect(dialog.locator('.hk-decl-template-error')).toHaveCount(0);
    await expect(dialog.locator('.hk-decl-preview-row')).toHaveCount(2);
    await dialog.locator('.hk-decl-preview').scrollIntoViewIfNeeded();
    await page.mouse.move(0, 0);
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/21o-panel-mobile-template-empty.png` });

    await page.setViewportSize({ width: 1280, height: 2600 });
    await page.waitForTimeout(600);
    await shoot('21n-panel-template-empty.png');

    // `click` scrolls the button into view and retries while the preview re-renders
    // the dialog, where a separate scroll can land on a node that is already gone.
    await dialog.locator('.hk-decl-cancel').click();
    await page.setViewportSize({ width: 1280, height: 720 });
  } finally {
    await callService('home_keeper', 'delete_declarative_companion', { id: specId });
  }
});

/**
 * A plain template-mode sensor task's own page, at both widths.
 *
 * The surface three separate mode allowlists forgot. `EDGE_SENSOR_MODES` left the task
 * with a live **Done** button while its own chip said Monitored — #231 exactly, and
 * pressing it recorded a completion that moved nothing. `recurrenceText` and
 * `sensorProgress` both fell through to the usage meter, so the page read "Every of
 * use" and "Target 0 (sensor.…)" for a task whose whole condition is one Jinja
 * expression that appeared nowhere on it.
 *
 * Deliberately a **dormant** task: armed, the Done button is expected, and the shot
 * would prove nothing.
 */
test('capture a template-mode sensor task page at both widths', async ({ page }) => {
  const created = await callService(
    'home_keeper',
    'add_task',
    {
      name: 'Service the printer',
      recurrence_type: 'sensor',
      sensor: {
        entity_id: 'sensor.demo_printer_hours',
        mode: 'template',
        template: '{{ state | float(0) >= 5000 }}',
        clear_on_recover: true,
      },
    },
    true,
  );
  const taskId = created.task_id as string;
  try {
    const panel = page.locator('home-keeper-panel').first();
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
    const card = panel.locator('.hk-detail-card').first();
    await expect(card).toBeVisible({ timeout: 45_000 });
    // The Schedule rows are a card of their own, below the header card the actions
    // live in, so the assertions below read the page rather than one card.
    const page$ = panel.locator('.hk-detail-card');
    await expect(page$.filter({ hasText: 'Recurrence' })).toBeVisible({ timeout: 20_000 });

    // Asserted before the shot, so a screenshot of the wrong state cannot be committed.
    await expect(card).toContainText('Monitored');
    await expect(page$.first().locator('..')).toContainText('{{ state | float(0) >= 5000 }}');
    await expect(panel).not.toContainText('of use');
    await expect(panel).not.toContainText('Target 0');
    await expect(panel.locator('.hk-detail-actions .d-done')).toHaveCount(0);

    await page.mouse.move(0, 0);
    await page.waitForTimeout(400);
    await page.screenshot({
      path: `${OUT}/21p-panel-template-task-detail.png`,
      fullPage: true,
    });

    await page.setViewportSize(PHONE);
    await page.waitForTimeout(600);
    await expect(card).toBeVisible();
    await page.mouse.move(0, 0);
    await page.waitForTimeout(600);
    await page.screenshot({
      path: `${OUT}/21q-panel-mobile-template-task-detail.png`,
      fullPage: true,
    });
    await page.setViewportSize({ width: 1280, height: 720 });
  } finally {
    await callService('home_keeper', 'delete_task', { task_id: taskId });
  }
});

/**
 * Task labels on a declarative companion, and the task's own Edit form, at both
 * widths (#378).
 *
 * Two real Home Assistant labels are made for the shot, so the pickers draw them as
 * the coloured chips a user sees, and removed again with the companion. The companion
 * watches the demo moisture sensor, the leak case the issue asks for. Its notes
 * template is empty, so the Edit form offers the notes too.
 */
test('capture task labels and the task Edit form at both widths', async ({ page }) => {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  const ws = (msg: Record<string, unknown>): Promise<Record<string, any>> =>
    panel.evaluate((el, m) => (el as any).hass.callWS(m), msg);
  const leak = await ws({ type: 'config/label_registry/create', name: 'Leak', color: 'red' });
  const urgent = await ws({
    type: 'config/label_registry/create',
    name: 'Urgent',
    color: 'orange',
  });
  const created = await callService(
    'home_keeper',
    'add_declarative_companion',
    {
      name: 'Leak sensors',
      selection: { domain: 'binary_sensor', device_class: 'moisture' },
      trigger: { mode: 'state', state: 'on', clear_on_recover: true },
      task_template: {
        name_template: 'Check {{ friendly_name }}',
        notes_template: '',
        labels: [leak.label_id, urgent.label_id],
      },
    },
    true,
  );
  const specId = created.companion.id as string;

  try {
    const mine = async (): Promise<Array<Record<string, any>>> =>
      (await listTasks()).filter((t) => t.source?.declarative_companion?.spec_id === specId);
    await expect.poll(async () => (await mine()).length, { timeout: 30_000 }).toBe(1);
    const task = (await mine())[0];
    // The labels reached the task the companion made.
    expect(task.labels).toEqual([leak.label_id, urgent.label_id]);
    const taskId = task.id as string;

    // 21s. The Task template section of the dialog, with the two labels picked.
    await page.setViewportSize({ width: 1280, height: 2600 });
    await openSettingsSection(panel, 'companions');
    await panel.locator(`.hk-decl-row[data-spec-id="${specId}"] .hk-decl-edit`).click();
    const dialog = panel.locator('ha-dialog.hk-decl-dialog');
    const template = dialog.locator('[data-decl-section="template"]');
    await expect(template).toBeVisible({ timeout: 20_000 });
    await expect(template).toContainText('Task labels');
    await expect(dialog.locator('.hk-decl-preview-header')).toHaveText(/Showing \d+ of \d+/, {
      timeout: 20_000,
    });
    await page.waitForTimeout(800);
    const surface = await dialog.locator('dialog').first().boundingBox();
    if (!surface) throw new Error('the companion dialog has no rendered surface to photograph');
    const pad = 16;
    await page.screenshot({
      path: `${OUT}/21s-panel-declarative-task-labels.png`,
      clip: {
        x: Math.max(0, surface.x - pad),
        y: Math.max(0, surface.y - pad),
        width: surface.width + pad * 2,
        height: surface.height + pad * 2,
      },
    });
    await dialog.locator('.hk-decl-cancel').click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0);

    // 21t. The task's own Edit form: only the fields the companion leaves free.
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
    const actions = panel.locator('.hk-detail-actions').first();
    await expect(actions.locator('.d-edit')).toBeVisible({ timeout: 45_000 });
    await actions.locator('.d-edit').click();
    const form = panel.locator('#hk-form');
    await expect(form).toBeVisible({ timeout: 20_000 });
    await expect(form).toContainText('Labels');
    await expect(panel.locator('.hk-drawer-delete')).toHaveCount(0);
    await page.mouse.move(0, 0);
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/21t-panel-declarative-task-edit.png` });

    // The phone layout: the task page, the Edit form, and the Task template section.
    await page.setViewportSize(PHONE);
    await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
    const phoneActions = panel.locator('.hk-detail-actions').first();
    await expect(phoneActions.locator('.d-edit-companion')).toBeVisible({ timeout: 45_000 });
    await page.mouse.move(0, 0);
    await page.waitForTimeout(600);
    await page.screenshot({
      path: `${OUT}/21e-mobile-companion-task.png`,
      fullPage: true,
    });

    await phoneActions.locator('.d-edit').click();
    await expect(panel.locator('#hk-form')).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/21t-mobile-companion-task-edit.png` });

    await openPanel(page);
    await openSettingsSection(panel, 'companions');
    await panel.locator(`.hk-decl-row[data-spec-id="${specId}"] .hk-decl-edit`).click();
    const phoneTemplate = panel.locator('ha-dialog.hk-decl-dialog [data-decl-section="template"]');
    await expect(phoneTemplate).toBeVisible({ timeout: 20_000 });
    await phoneTemplate.scrollIntoViewIfNeeded();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/21s-mobile-task-labels.png` });
    await panel.locator('ha-dialog.hk-decl-dialog .hk-decl-cancel').click();
    await page.setViewportSize({ width: 1280, height: 720 });
  } finally {
    await callService('home_keeper', 'delete_declarative_companion', { id: specId });
    for (const label of [leak, urgent]) {
      await ws({ type: 'config/label_registry/delete', label_id: label.label_id });
    }
  }
});
