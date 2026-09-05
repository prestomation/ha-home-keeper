/**
 * One-off screenshot capture for PR documentation — not part of the e2e suite
 * (filename does not match *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots.capture.ts \
 *     --config=screenshots.config.ts
 *
 * The panel is built from Home Assistant components, so forms are `ha-form`s:
 * text fields live inside `ha-selector-text` (fill the inner input) and dropdowns
 * are `ha-select` built on `ha-dropdown` (open, then click the role="menuitem").
 */
import { test, expect, Locator, Page } from '@playwright/test';
import { openPanel, openDashboard } from './tests/helpers';
import {
  centre,
  expandGroup,
  openRow,
  settleToasts,
  shotVisible,
  shotWithDrawer,
} from './shots';
import { ASSET, PART, TASK } from './fixture-ids';
import { DESKTOP, PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';






/** Fill the input of the nth ha-form text selector within a scope. */
async function fillText(scope: Locator, nth: number, value: string): Promise<void> {
  await scope.locator('ha-selector-text').nth(nth).locator('input, textarea').fill(value);
}

/** Pick an option label from an HA ha-select (ha-dropdown) dropdown. */
async function chooseHaSelect(select: Locator, optionLabel: string | RegExp): Promise<void> {
  await select.click();
  await select.page().getByRole('menuitem', { name: optionLabel }).first().click();
}

/**
 * Put the usage form's "Also come due on a schedule" switch into a known state.
 *
 * Driven by its *effect* — the backstop adds a second number selector ("Or every")
 * next to Target — rather than by reading the switch widget's internals, which live
 * behind `ha-switch`'s shadow root and aren't a native checkbox. Reading the effect
 * also makes the helper idempotent and self-verifying: it clicks only when the form
 * isn't already in the wanted state, and waits for the schema to actually change.
 */
async function setBackstop(panel: Locator, on: boolean): Promise<void> {
  // Decide from the switch's own state, not from how many number fields are on
  // screen. Inferring it from the count silently stops working the moment the usage
  // form grows a field: adding "Starting reading" made the switched-*off* count equal
  // the old switched-on count, so this helper concluded it had nothing to do, never
  // clicked, and the assertion below passed on a form whose backstop was still off.
  const sw = panel.locator('#hk-task-form ha-selector-boolean ha-switch').first();
  const isOn = await sw.evaluate((el: HTMLElement & { checked?: boolean }) => !!el.checked);
  if (isOn !== on) {
    // Click the switch itself, not its `ha-selector-boolean` wrapper: the wrapper
    // spans the full row, so a centred click lands in the dead space between the
    // label and the control and toggles nothing.
    await sw.click();
  }
  // Settle on the revealed/hidden fields: target + starting reading, plus the
  // backstop interval when it's on.
  await expect(panel.locator('#hk-task-form ha-selector-number')).toHaveCount(on ? 3 : 2);
}

/** Fill the input of the nth ha-form number selector within a scope. */
async function fillNumber(scope: Locator, nth: number, value: string): Promise<void> {
  await scope.locator('ha-selector-number').nth(nth).locator('input').fill(value);
}

/**
 * Pick an entity in the nth ha-form entity selector within a scope.
 *
 * Home Assistant's entity picker is an `ha-picker-field` button that opens a search
 * overlay, not a plain text input, so the flow is click -> search -> pick the row.
 * The state mode's value control follows the bound entity (an on/off picker for a
 * binary sensor, free text otherwise), so a shot of that form has to really choose one.
 */
async function chooseEntity(
  scope: Locator,
  nth: number,
  query: string,
  label: RegExp,
): Promise<void> {
  const page = scope.page();
  await scope.locator('ha-selector-entity').nth(nth).locator('ha-picker-field').click();
  await page.locator('input[placeholder="Search"]:visible').first().fill(query);
  await page.locator('ha-combo-box-item:visible').filter({ hasText: label }).first().click();
}

test('capture Home Keeper panel + usage screenshots', async ({ page }) => {
  // 1. The admin sidebar panel — task list with floating + fixed + overdue tasks.
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.waitForTimeout(1200); // let the HA sidebar/layout settle (avoid ghosting)
  // Home Assistant raises a "Home Assistant has started!" toast on a cold boot, and
  // the capture always runs against a freshly-started container — so it lands across
  // the bottom of whichever early shots the run happens to reach first. It was over
  // the task detail's history when this was found.
  await settleToasts(page);

  // 0. First-run orientation banner — shown above the list until dismissed. Capture
  // it, then dismiss so the remaining task-list shots keep their established framing.
  await expect(panel.locator('.hk-intro')).toBeVisible();
  await page.screenshot({ path: `${OUT}/0-panel-first-run-intro.png`, fullPage: true });
  await panel.locator('ha-button.hk-intro-dismiss').click();
  await expect(panel.locator('.hk-intro')).toHaveCount(0);

  await page.screenshot({ path: `${OUT}/1-panel-task-list.png`, fullPage: true });

  // (The Shopping-filter shot lives further down, after the step that actually puts a
  // buy reminder in the store — taken here it only ever captured "No tasks match this
  // filter", which is a picture of nothing.)

  // 1a2. Completion-details dialog — a task whose capture mode is "optional" or
  // "required" opens this dialog on Done so you can record a note, cost, who and a
  // photo. The seeded "Replace fridge filter" task is set to optional capture.
  await panel.locator(`.done-btn[data-id="${TASK.fridgeFilter}"]`).click();
  // ha-dialog portals its surface, so wait on an inner field rather than the host.
  const noteField = panel
    .locator('ha-dialog[open] ha-selector-text textarea, ha-dialog[open] ha-selector-text input')
    .first();
  await noteField.waitFor({ state: 'visible', timeout: 15_000 });
  await noteField.fill('Replaced cartridge; rinsed housing');
  await panel.locator('ha-dialog[open] ha-selector-number input').first().fill('42.50');
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/11-panel-completion-dialog.png`, fullPage: true });
  // Dismiss via Escape (closes ha-dialog) so the capture records no extra completion.
  await page.keyboard.press('Escape');
  await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });

  // 1b. Task detail page — click a task to see its full schedule, notes and the
  // completion history of every time it was done (now annotated with the per-
  // completion note and cost recorded at Done time).
  await panel.locator(`.detail-open[data-detail-id="${TASK.fridgeFilter}"]`).click();
  await expect(panel.locator('.hk-hist-list li').first()).toBeVisible();
  // The note is Markdown (issue #163). Assert it actually rendered — `ha-markdown`
  // is one of HA's lazily-loaded elements, so a regression here silently degrades to
  // escaped plain text rather than failing loudly.
  await expect(panel.locator('.hk-detail-inner ha-markdown strong').first()).toBeVisible({
    timeout: 15_000,
  });
  await expect(panel.locator('.hk-detail-inner ha-markdown ol li').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/7-panel-task-detail.png`, fullPage: true });

  // 1a1. Editing beside the page. Edit opens the form in the drawer next to the task's
  // own page rather than throwing it away for the list, so the schedule, the notes and
  // the completion history stay readable while the values that produced them are being
  // changed.
  await panel.locator('.d-edit').click();
  await expect(panel.locator('#hk-task-form')).toBeVisible();
  await page.waitForTimeout(400);
  await shotWithDrawer(page, `${OUT}/54-panel-task-detail-edit.png`);
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });
  await expect(panel.locator('.d-edit')).toBeVisible();

  // 56. Duplicate. The button opens the *create* form already filled in with a copy of
  // this task — the answer to a row of near-identical tasks that differ by a sensor and
  // a name (#279). Nothing is saved until Create, so cancelling below leaves the seeded
  // fixture exactly as every later shot expects it.
  await panel.locator('.d-dup').click();
  await expect(panel.locator('#hk-task-form')).toBeVisible();
  await expect(panel.locator('#f-save')).toHaveText(/Create/);
  await expect(panel.locator('#hk-task-form ha-selector-text input').first()).toHaveValue(
    /\(copy\)$/,
  );
  await page.waitForTimeout(400);
  await shotWithDrawer(page, `${OUT}/56-panel-task-duplicate-drawer.png`);
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });

  // 1b1. The inline notes editor, open, with its live Markdown preview. Every task
  // gets this now (it used to be problem-sensor tasks only) — notes are prose, so
  // they're authored in a full-width box that previews as you type.
  await panel.locator('.d-note-edit').click();
  const taskNote = panel.locator('.d-note-input');
  await expect(taskNote).toBeVisible();
  await taskNote.fill(
    '## Next time\n\n- Order **two** cartridges (`ULTRAWF`)\n- Check the door gasket while the panel is off\n',
  );
  // The preview is debounced, so wait for the rendered output rather than a timeout.
  await expect(panel.locator('.hk-md-preview ha-markdown h2')).toBeVisible({ timeout: 15_000 });
  await page.screenshot({ path: `${OUT}/41-panel-note-editor-preview.png`, fullPage: true });
  // Cancel so the capture leaves the seeded note untouched for later shots.
  await panel.locator('.d-note-cancel').click();
  await expect(panel.locator('.d-note-edit')).toBeVisible();

  // 1b2. "Move date" dialog — corrects an already-recorded completion's timestamp
  // from the history list, distinct from the pencil (edit-metadata) button next to it.
  await panel.locator('.hk-hist-move').first().click();
  const moveDateField = panel
    .locator('ha-dialog[open] ha-selector-datetime')
    .first();
  await moveDateField.waitFor({ state: 'visible', timeout: 15_000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/40-panel-history-move-date.png`, fullPage: true });
  // Dismiss via Escape so the capture records no actual move.
  await page.keyboard.press('Escape');
  await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });

  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 1c. Managed-task detail page — a task owned by another integration
  // (Pawsistant). Shows the "Managed by Pawsistant" chip, the completion prompt,
  // and deletion guidance in place of a Delete button.
  await panel.locator(`.detail-open[data-detail-id="${TASK.buddyMedicine}"]`).click();
  await expect(panel.locator('ha-assist-chip.hk-managed').first()).toBeVisible();
  await expect(panel.locator('.hk-managed-prompt')).toBeVisible();
  // A managed task is editable but not copyable, so it keeps a greyed Duplicate beside
  // its live Edit — this shot documents that pairing, so assert it rather than trust it.
  await expect(panel.locator('.d-dup-blocked')).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/9-panel-managed-detail.png`, fullPage: true });

  // 1d. Edit form of a managed task — the integration-locked fields (name and
  // attach-to-device) are omitted; only the unlocked fields are editable.
  await panel.locator('.d-edit').click();
  await expect(panel.locator('#hk-task-form')).toBeVisible();
  await page.waitForTimeout(300);
  await shotWithDrawer(page, `${OUT}/10-panel-managed-edit-locked.png`);
  // The form opens beside the page it was pressed on, so Cancel lands back on that
  // page (see `_openEdit`) — the way to the list is the page's own Back.
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 1e. Tasks grouped by managing integration — managed tasks bucket under their
  // integration; everything else falls under "Your tasks".
  await panel.locator('select[data-seg-select="group"]').selectOption('integration');
  await expect(panel.locator('details.hk-group').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/11-panel-grouped-by-integration.png`, fullPage: true });
  // Reset grouping so later list shots are unaffected.
  await panel.locator('select[data-seg-select="group"]').selectOption('status');
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 1f. Orphan cleanup — when a managing integration is uninstalled, its tasks are
  // no longer protected: a warning banner offers a one-click "Remove orphaned tasks",
  // and each orphaned task shows the "Integration offline" chip.
  await expect(panel.locator('.hk-orphan-banner')).toBeVisible();
  await expect(panel.locator('ha-assist-chip.hk-orphaned').first()).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/12-panel-orphan-cleanup.png`, fullPage: true });

  // 1g. Orphaned task detail — the Delete button returns (protection lifts) with an
  // explanation that the owning integration is gone.
  await panel.locator(`.detail-open[data-detail-id="${TASK.rexVet}"]`).click();
  await expect(panel.locator('ha-assist-chip.hk-orphaned').first()).toBeVisible();
  await expect(panel.locator('.d-del')).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/13-panel-orphan-detail.png`, fullPage: true });
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 1h. Condition-driven (triggered) battery task detail. An active one (battery
  // low) reads as due-now with the "Managed by Battery Notes" chip and shows the
  // full replacement cadence — every time the battery was changed. The battery-type
  // chip (e.g. "2× AAA") is shown alongside the managed chip.
  await panel.locator(`.detail-open[data-detail-id="${TASK.doorBattery}"]`).click();
  await expect(panel.locator('ha-assist-chip.hk-managed').first()).toBeVisible();
  await expect(panel.locator('.hk-hist-list li').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/14-panel-battery-detail.png`, fullPage: true });
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 1h3. Usage-meter task detail with a time backstop. The seeded "Replace printer
  // nozzle" task meters `sensor.demo_printer_hours` (a fixed 780 h) against a
  // baseline of 660 with a 300 h target, so it renders a deterministic "120 of 300 h
  // used" with the progress bar, the "180 h to go" line, and the "also due every 6
  // months" backstop note.
  // It's dormant (the meter hasn't reached its target), so it lives in the collapsed
  // Monitored group — expand that before clicking through.
  const monitoredForUsage = panel.locator(
    'details.hk-group[data-group-key="status:monitored"]',
  );
  await expandGroup(monitoredForUsage);

  // 1h2b. The overview reads a dormant usage/meter task as a live countdown — "in 180
  // h" for the nozzle task (300 h target, 120 h used) — the meter analogue of the "in
  // 3 days" a time-based task shows, rather than a bare "Monitored" (#235). The group
  // still buckets it under Monitored; it's the card's own due chip that counts down.
  // Assert the chip as well as photographing it (capture != coverage, #221).
  // The due/overdue chip sits at the end of the row now, next to the action it
  // argues for, rather than among the chips that describe the task.
  const nozzleDueChip = panel
    .locator(`ha-card.hk-card[data-id="${TASK.nozzleUsage}"] .hk-status ha-assist-chip`)
    .first();
  await expect(nozzleDueChip).toHaveAttribute('label', 'in 180 h');
  await nozzleDueChip.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/1c-panel-usage-countdown.png`, fullPage: true });

  await openRow(page, panel, `.detail-open[data-detail-id="${TASK.nozzleUsage}"]`);
  await expect(panel.locator('.hk-meter').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/14b-panel-usage-progress.png`, fullPage: true });

  // 48. The same page's history, now carrying the meter reading each completion was
  // logged at (#235) — the number a mileage- or hours-based service actually turns
  // on. Assert the chip as well as photographing it: #221 sat in plain sight in a
  // committed screenshot for months because nothing tested what the picture showed.
  const usageHistoryRow = panel.locator('.hk-hist-list li').first();
  await expect(usageHistoryRow.locator('.hk-hist-chips')).toContainText('at 660 h');
  await usageHistoryRow.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.screenshot({
    path: `${OUT}/48-panel-history-meter-reading.png`,
    fullPage: true,
  });

  // 48b. Editing that reading. The pencil opens the same dialog that edits a note or
  // cost, with the reading seeded from the completion — and on a usage task, saving a
  // corrected value on the latest completion re-anchors the meter to match, so the
  // progress bar can't contradict the log.
  //
  // Re-resolve the row and scroll it back into view first: the `fullPage` capture
  // above resizes the viewport to stitch the page, and clicking straight afterwards
  // can land before the layout has settled back.
  await panel.locator('.hk-hist-list li').first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await panel.locator('.hk-hist-list li').first().locator('.hk-hist-edit').click();
  const readingDialog = panel.locator('ha-dialog[open]');
  await expect(readingDialog).toHaveCount(1);
  // Two number fields: the cost every completion has, and the meter reading this one
  // has because its task is bound to a numeric sensor. A non-sensor task shows one.
  await expect(readingDialog.locator('ha-selector-number')).toHaveCount(2);
  await page.waitForTimeout(500);
  await page.screenshot({
    path: `${OUT}/48b-panel-history-edit-reading.png`,
    fullPage: true,
  });
  await page.keyboard.press('Escape');
  await expect(panel.locator('ha-dialog[open]')).toHaveCount(0);

  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 37. Battery type chip on the task list — the active battery task shows its
  // "2× AAA" chip (set by the Battery Notes glue as task_chips) right in the card row.
  const batteryCard = panel.locator(`.hk-card[data-id="${TASK.doorBattery}"]`);
  await expect(batteryCard).toBeVisible();
  await page.waitForTimeout(300);
  await batteryCard.screenshot({ path: `${OUT}/37-panel-battery-chip-row.png` });

  // 37b. Battery task detail with chip visible in header chips row.
  await panel.locator(`.detail-open[data-detail-id="${TASK.doorBattery}"]`).click();
  await expect(panel.locator('ha-assist-chip.hk-managed').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/37b-panel-battery-chip-detail.png`, fullPage: true });
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 1h2. A synced "problem" binary-sensor task. Home Keeper mirrors every
  // device_class: problem sensor as a task that's armed while the problem is active
  // (created at runtime by the sync, so locate it by name rather than a fixed id).
  // It can't be completed here — the originating integration clears it — so the Done
  // action is shown *disabled*; clicking it pops up the reason. The completion prompt
  // also explains how it resolves.
  await panel.locator('.hk-card', { hasText: 'Sump pump problem' }).locator('.detail-open').first().click();
  await expect(panel.locator('.hk-managed-prompt')).toBeVisible();
  await expect(panel.locator('.d-done-blocked-wrap')).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/16-panel-problem-sensor-detail.png`, fullPage: true });
  // 18b. A durable note on the synced problem task. There's no device to model here,
  // so the note is the place to jot what to remember next time this problem fires; it
  // persists across the mirror clearing/re-arming (and even being recreated). Open the
  // inline editor and seed a note for the shot.
  //
  // This runs *before* the blocked-Done toast below: the editor's Markdown preview
  // sits between the textarea and the Save/Cancel row, which puts those buttons right
  // where HA parks its toast — capturing them while one is up hides the buttons.
  await panel.locator('.d-note-edit').click();
  const noteInput = panel.locator('.d-note-input');
  await expect(noteInput).toBeVisible();
  await noteInput.fill(
    'Reset the pump breaker in the garage panel, then prime it. Spare float switch: part #SFS-200 in the utility drawer.',
  );
  await page.waitForTimeout(400); // the preview is debounced
  await page.screenshot({ path: `${OUT}/18-panel-problem-sensor-note.png`, fullPage: true });
  await panel.locator('.d-note-save').click();
  await expect(panel.locator('.d-note-edit')).toBeVisible();

  // Tapping the disabled Done surfaces a toast explaining why it can't be completed
  // here (best-effort capture — the toast is transient).
  await panel.locator('.d-done-blocked-wrap').click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/16b-panel-problem-sensor-blocked-toast.png`, fullPage: true });

  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 18. A completion-blocked task on a Tasks-*list* card row shows a muted "Clears
  // automatically" caption instead of a dead Done button; tapping it pops the same
  // reason as the detail page.
  const sumpCard = panel.locator('.hk-card', { hasText: 'Sump pump problem' });
  await expect(sumpCard.locator('.hk-auto-clear')).toHaveCount(1);
  await sumpCard.locator('.hk-auto-clear').click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/18-panel-tasks-blocked-done.png`, fullPage: true });
  // (healthy batteries) — collapsed by default to stay out of the way, one click
  // to browse. Expand it for the shot — guarded, because step 14b above already
  // expands this same group to reach the usage task and a blind click would close
  // it again (a `<details>` toggle is not idempotent).
  const monitored = panel.locator('details.hk-group[data-group-key="status:monitored"]');
  await expandGroup(monitored);
  await expect(monitored.locator('.hk-card').first()).toBeVisible();
  // The blocked-Done toast the step above raised outlives it and would sit across
  // the section this shot is about — two of them stacked, since it was clicked twice.
  await settleToasts(page);
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/15-panel-monitored-section.png`, fullPage: true });

  // 19. The Completed section — a one-off (do-once) task drops here once it's done,
  // leaving the active list but keeping its completion history. Collapsed by default
  // (like Monitored); expand it for the shot.
  const completed = panel.locator('details.hk-group[data-group-key="status:completed"]');
  await expandGroup(completed);
  await expect(completed.locator('.hk-card').first()).toBeVisible();
  await settleToasts(page);
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/19-panel-completed-section.png`, fullPage: true });

  // 42. Placing a task in a room (issue #204). `area_id` has always been a task field
  // in the store and the services, and the panel groups and filters on it — but the
  // form offered no control, so a task with no device could never be put in a room
  // from the UI. Seed an area, assign it to a *device-less* task (the case that had
  // no path at all), and capture both halves: the picker in the form, and the area
  // named on the detail page.
  await page.evaluate(async (IDS) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    // HA's onboarding seeds a handful of areas; reuse one rather than creating a
    // duplicate (the registry rejects a repeated name, failing the whole capture).
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const areas: any[] = await hass.callWS({ type: 'config/area_registry/list' });
    const area =
      areas.find((a) => a.area_id === 'living_room') ??
      areas[0] ??
      (await hass.callWS({ type: 'config/area_registry/create', name: 'Living Room' }));
    await hass.callService('home_keeper', 'update_task', {
      task_id: IDS.TASK.medicine,
      area_id: area.area_id,
    });
  }, { TASK });
  await openPanel(page);
  await expect(panel.locator('.hk-name').first()).toBeVisible();

  // The detail page names the task's area beside its status chip, so the save is
  // visible without changing the grouping.
  await panel.locator(`.detail-open[data-detail-id="${TASK.medicine}"]`).click();
  await expect(panel.locator('.hk-chips ha-assist-chip[label="Living Room"]')).toBeVisible({
    timeout: 10_000,
  });
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/42-panel-task-area-detail.png`, fullPage: true });

  // The Area picker in the task's edit form, holding the saved room. The form opens
  // in the drawer beside the task's own page.
  await panel.locator('.d-edit').click();
  await expect(panel.locator('#hk-task-form')).toBeVisible();
  await expect(panel.locator('#hk-task-form ha-selector-area')).toBeVisible({ timeout: 10_000 });
  // The drawer scrolls its own content and the Area picker is well down the form, so
  // bring it into frame — `toBeVisible` only means it is in the DOM and painted.
  await centre(panel.locator('#hk-task-form ha-selector-area'));
  await page.waitForTimeout(600);
  await shotWithDrawer(page, `${OUT}/42b-panel-task-area-form.png`);
  // The task form is an inline card, not an `ha-dialog` — Escape leaves it open and
  // it would then sit on top of the grouped-list shot below. Close it properly, then
  // leave the task's page: the grouping control below belongs to the list.
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 42c. Grouped by Area — what the picker buys you: the task now sorts into its room
  // instead of the "Unassigned" bucket it was stuck in.
  await panel.locator('select[data-seg-select="group"]').selectOption('area');
  await expect(panel.locator('details.hk-group[data-group-key^="area:"]').first()).toBeVisible({
    timeout: 10_000,
  });
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/42c-panel-tasks-grouped-by-area.png`, fullPage: true });
  // Reset grouping so later list shots are unaffected.
  await panel.locator('select[data-seg-select="group"]').selectOption('status');

  // 2. Create form — floating recurrence + device picker.
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-form')).toBeVisible();
  await fillText(panel.locator('#hk-task-form'), 0, 'Replace dishwasher filter');
  await shotWithDrawer(page, `${OUT}/2-panel-create-floating.png`);

  // 3. Create form switched to a fixed (anchored) schedule.
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').first(), /fixed schedule/i);
  await expect(panel.locator('#hk-task-form ha-selector-datetime').first()).toBeVisible();
  await shotWithDrawer(page, `${OUT}/3-panel-create-fixed.png`);

  // 3b. Active season on the floating task form — the season holds a repeating task
  // to the part of the year it belongs in. Switch back to floating, turn the season
  // on, then add a second window so the shot shows the list a task can carry rather
  // than a single date range.
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').first(), /after each completion/i);
  const seasonSwitch = panel
    .locator('#hk-task-form-season ha-switch')
    .first();
  if (!(await seasonSwitch.evaluate((el: HTMLInputElement) => el.checked))) {
    await seasonSwitch.click();
  }
  await expect(panel.locator('#hk-task-form-season-1')).toBeVisible();
  await panel.locator('#hk-season-add').click();
  await expect(panel.locator('#hk-task-form-season-2')).toBeVisible();
  // The windows sit near the bottom of a drawer that scrolls inside a 100vh column,
  // so scroll the first one to the top of the drawer: the shot then frames the season
  // from its switch down to Add another season, which is what someone editing it sees.
  await panel
    .locator('#hk-task-form-season')
    .evaluate((node: Element) => node.scrollIntoView({ block: 'start' }));
  await page.evaluate(() => document.scrollingElement?.scrollTo({ top: 0, left: 0 }));
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/3b-panel-create-season.png` });

  // Turn season off for the next shot.
  if (await seasonSwitch.evaluate((el: HTMLInputElement) => el.checked)) {
    await seasonSwitch.click();
  }
  await expect(panel.locator('#hk-task-form-season-1')).toHaveCount(0);

  // 20. Create form switched to a one-off (do-once) task — no cadence, just a single
  // Due date picker. Completing it later sends it to the Completed section.
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').first(), /Just once/);
  await expect(panel.locator('#hk-task-form ha-selector-datetime').first()).toBeVisible();
  await shotWithDrawer(page, `${OUT}/20-panel-create-one-off.png`);

  // 30. Create form switched to a sensor-based task (usage / meter) — an entity
  // picker, a mode toggle, and a target replace the clock cadence. Home Keeper arms
  // the task once the bound meter advances by the target since the last completion.
  // Reopen the panel fresh first so no transient tooltip/toast from the blocked-done
  // steps above lingers over the form.
  await openPanel(page);
  await expect(panel.locator('#add-btn')).toBeVisible();
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-form')).toBeVisible();
  await fillText(panel.locator('#hk-task-form'), 0, 'Service generator (runtime hours)');
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').first(), /Based on a sensor/);
  await expect(panel.locator('#hk-task-form ha-selector-entity').first()).toBeVisible();
  // Enter a target so the live hint renders and spells out the baseline model — "due
  // once the sensor climbs 100 above its reading when you create the task, then every
  // 100 after each completion." (The per-field Target helper adds the concrete
  // 660 -> 760 example.)
  await fillNumber(panel.locator('#hk-task-form'), 0, '100');
  await expect(panel.locator('#hk-sensor-hint')).toBeVisible();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await shotWithDrawer(page, `${OUT}/30-panel-create-sensor-task.png`);


  // 30b. The same usage form with a **time backstop** — "every 100 h, or every 6
  // months, whichever comes first", which is how manufacturers actually write a
  // service interval. It lives behind the "Also come due on a schedule" switch, which
  // reveals the interval, its unit and the combinator; switching it on seeds a usable
  // interval so the revealed fields describe a real rule straight away.
  await setBackstop(panel, true);
  // Third number field now: target, starting reading, then the backstop interval.
  await fillNumber(panel.locator('#hk-task-form'), 2, '6');
  await expect(panel.locator('#hk-sensor-hint')).toBeVisible();
  // The summary strip above the submit button states the assembled rule in one
  // sentence. Several fields add up to it and none of them says it, so this is the
  // shot that has to prove the wording — assert it, don't just photograph it.
  await expect(panel.locator('#hk-form-summary-value')).toHaveText(
    'Every 100 of use, or every 6 months',
  );
  // Viewport, not full page — same reason as shot 31. Centre the backstop interval,
  // the third and last number field, so the switch that reveals it and the fields it
  // brings with it are all in frame. (The summary strip this rule adds up to sits at
  // the far end of a long form; the assertion above is what guards its wording.)
  await centre(panel.locator('#hk-task-form ha-selector-number').nth(2));
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/30b-panel-sensor-backstop.png` });
  // Put it back to a pure meter so the threshold shot below starts from a clean form.
  await setBackstop(panel, false);

  // 31. The same form switched to threshold mode — a comparison + value, plus an
  // optional hold (seconds) to debounce. The task arms on the crossing. (The sensor
  // mode select is the 2nd ha-select in the form, after recurrence type.)
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').nth(1), /Threshold/);
  await expect(panel.locator('#hk-task-form ha-selector-number').first()).toBeVisible();
  // A threshold value so the live hint reads "becomes due when the sensor is ≥ 90 h".
  await fillNumber(panel.locator('#hk-task-form'), 0, '90');
  await expect(panel.locator('#hk-sensor-hint')).toBeVisible();
  // Photograph the viewport, not the page: the drawer is sticky and scrolls its own
  // content, so once a field this far down is in view a full-page capture renders the
  // drawer as a band at the page's scroll offset with blank paper above it. Centre the
  // live hint so the fields it explains sit in the frame with it.
  await centre(panel.locator('#hk-sensor-hint'));
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/31-panel-create-sensor-threshold.png` });

  // 43. The same form in **state** mode — the binary-sensor case. A robot vacuum's
  // "water tank low" or a device's battery_almost_empty reports on/off and has no
  // number to compare, so the numeric modes can't see it at all. Bind a real
  // binary_sensor and Home Keeper offers On/Off directly instead of free text.
  await openPanel(page);
  await expect(panel.locator('#add-btn')).toBeVisible();
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-form')).toBeVisible();
  await fillText(panel.locator('#hk-task-form'), 0, 'Fill the vacuum water tank');
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').first(), /Based on a sensor/);
  await expect(panel.locator('#hk-task-form ha-selector-entity').first()).toBeVisible();
  await chooseEntity(
    panel.locator('#hk-task-form'),
    0,
    'hk_demo_water_tank',
    /HK demo water tank low/,
  );
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').nth(1), /^State$/);
  // Assert the wording rather than only photographing it: the entity, the mode and
  // the state add up to one rule and no single field states it. Both lines also prove
  // the state defaulted to `on` through the binary-sensor picker rather than staying
  // an empty free-text box.
  await expect(panel.locator('#hk-form-summary-value')).toHaveText('When it changes to on');
  await expect(panel.locator('#hk-sensor-hint')).toHaveText(
    'The task becomes due when the sensor changes to on.',
  );
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await shotWithDrawer(page, `${OUT}/43-panel-create-sensor-state.png`);

  // 47. A usage form with a **starting reading** (#235). Anchoring at "now" starts a
  // task for an already-serviced machine a whole interval late, so this field says
  // where the last service happened and the live hint re-does its arithmetic from
  // there. On its own fresh form: it binds an entity and the shots above deliberately
  // don't, and threading that through them coupled steps that have no business
  // depending on each other. Assert the sentence rather than only photographing it —
  // the numbers *are* the feature, and a picture can't prove they're right.
  await openPanel(page);
  await expect(panel.locator('#add-btn')).toBeVisible();
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-form')).toBeVisible();
  await fillText(panel.locator('#hk-task-form'), 0, 'Service generator (runtime hours)');
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').first(), /Based on a sensor/);
  await expect(panel.locator('#hk-task-form ha-selector-entity').first()).toBeVisible();
  // Target first, then the entity. Picking an entity re-emits the whole form value,
  // so anything typed in the same tick is overwritten — fill each field only once the
  // previous change has visibly landed. Bind the demo run-hours sensor (a constant
  // 780 h) so the hint has a live value to work against: counting from 700 leaves
  // 80 h of the 100 h target already spent.
  await fillNumber(panel.locator('#hk-task-form'), 0, '100');
  await expect(panel.locator('#hk-sensor-hint')).toBeVisible();
  await chooseEntity(
    panel.locator('#hk-task-form'),
    0,
    'demo_printer_hours',
    /Demo printer hours/,
  );
  await expect(panel.locator('#hk-sensor-hint')).toContainText('This sensor reads 780 h now');
  await fillNumber(panel.locator('#hk-task-form'), 1, '700');
  await expect(panel.locator('#hk-sensor-hint')).toContainText(
    'Counting from 700 h, so 80 h of 100 h is already used and the task becomes due at 800 h.',
  );
  // Viewport, not full page, centred on the hint — same reason as shot 31.
  await centre(panel.locator('#hk-sensor-hint'));
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/47-panel-sensor-starting-reading.png` });

  // 33 + 34. Linked consumable (sensor-driven reorder). Attach a task to an appliance,
  // then its "Linked consumable" picker is scoped to that appliance's consumables;
  // completing the task draws down a spare and fires a low-stock event for a reorder.
  await openPanel(page);
  await expect(panel.locator('#add-btn')).toBeVisible();
  await page.evaluate(async (IDS) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { assets } = await hass.callWS({ type: 'home_keeper/get_assets' });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const wh = assets.find((a: any) => a.name === 'Garage water heater');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    // By id, not by type: the water heater also carries a consumable measured in
    // millilitres, and this shot is about the plain whole-spares case.
    const part = (wh.parts || []).find((p: any) => p.id === IDS.PART.sedimentFilter);
    // Attach the demo task to the appliance (so the picker scopes to it), then link it
    // to that appliance's spare.
    // The update_task *service* takes flat fields (task_id + device_id), unlike the
    // websocket's {task_id, updates}. Attaching a device reloads the entry, so settle
    // it before linking.
    await hass.callService('home_keeper', 'update_task', {
      task_id: IDS.TASK.waterFilter,
      device_id: wh.device_id,
    });
    await new Promise((r) => setTimeout(r, 1500));
    await hass.callService('home_keeper', 'set_task_consumable', {
      task_id: IDS.TASK.waterFilter,
      asset_id: wh.id,
      part_id: part.id,
    });
  }, { TASK, PART });
  // Reload so the panel re-reads the now-attached, linked task.
  await openPanel(page);
  await expect(panel.locator('#add-btn')).toBeVisible();
  // 33. The task detail shows the linked consumable and its current stock.
  await panel.locator(`.detail-open[data-detail-id="${TASK.waterFilter}"]`).click();
  await expect(
    panel.locator('.hk-detail-row', { hasText: 'Sediment pre-filter' }),
  ).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({
    path: `${OUT}/33-panel-linked-consumable-detail.png`,
    fullPage: true,
  });

  // 34. Editing the task: the "Linked consumable" picker is scoped to the consumables
  // of the appliance the task is attached to (not every appliance's spares).
  await panel.locator('.d-edit').click();
  await expect(panel.locator('#hk-task-form')).toBeVisible();
  await expect(panel.locator('#hk-task-form').getByText('Linked consumable')).toBeVisible();
  // The picker is well down a long form and the drawer scrolls its own content, so
  // bring it into frame — `toBeVisible` only means it is in the DOM and painted.
  await centre(panel.locator('#hk-task-form').getByText('Linked consumable'));
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await shotWithDrawer(page, `${OUT}/34-panel-create-linked-consumable.png`);

  // 36. The same edit form also offers "Links to show on card" — a multi-select of
  // the attached appliance's document/metadata links. The seeded task pins two, which
  // the dashboard card renders as openable chips on the task's row.
  await expect(
    panel.locator('#hk-task-form').getByText('Links to show on card'),
  ).toBeVisible();
  await centre(panel.locator('#hk-task-form').getByText('Links to show on card'));
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await shotWithDrawer(page, `${OUT}/36-panel-task-card-links.png`);
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 5. Appliances tab — the asset list with the seeded virtual device.
  await panel.locator('#tab-appliances').click();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/5-panel-appliances-list.png`, fullPage: true });

  // 5c. Tree view — toggle the View control from List to Tree so parent/child
  // indentation is visible (the seed nests the radio shade under the shades).
  await panel.locator('.hk-seg[data-seg="assetView"] .hk-seg-btn[data-seg-val="tree"]').click();
  await expect(panel.locator('.hk-tree-child').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/5c-panel-appliances-tree-view.png`, fullPage: true });
  // Switch back to flat so the rest of the capture script sees the default view.
  await panel.locator('.hk-seg[data-seg="assetView"] .hk-seg-btn[data-seg-val="flat"]').click();
  await expect(panel.locator('.hk-name').first()).toBeVisible();

  // 5b. Appliance detail page — its metadata, parts, related tasks and the
  // maintenance history (including the archived history of a task that was
  // deleted while still assigned to it).
  await panel.locator(`.detail-open[data-detail-id="${ASSET.waterHeater}"]`).click();
  // The appliance opens on Parts, beside the list it came from, with itself marked
  // in that list. Its per-part notes render as Markdown like any other note.
  await expect(panel.locator('ha-card.hk-card.hk-selected')).toBeVisible();
  await expect(panel.locator('.hk-part-notes ha-markdown strong').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/8-panel-appliance-detail.png`, fullPage: true });

  // 8a0. Editing beside the appliance. The form is a second column, not a third: the
  // list the appliance was opened from steps aside for as long as the form is up, so
  // the parts and documents being edited stay next to the fields editing them.
  await panel.locator('.d-edit').click();
  await expect(panel.locator('#hk-asset-form')).toBeVisible();
  await expect(panel.locator('.hk-master')).toBeHidden();
  await page.waitForTimeout(400);
  await shotWithDrawer(page, `${OUT}/55-panel-appliance-detail-edit.png`);
  await panel.locator('#a-cancel').click();
  await expect(panel.locator('#hk-asset-form')).toHaveCount(0, { timeout: 10_000 });
  await expect(panel.locator('.hk-master')).toBeVisible();

  // 8a. The other sub-tabs. Each is a URL of its own, so these are pages, not
  // panels — the appliance's own notes and identity live under Details, and the
  // retained history of a task deleted while still assigned to it under History.
  await panel.locator('.hk-subtab[data-tab="details"]').click();
  await expect(panel.locator('ha-markdown table').first()).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/8d-panel-appliance-details-tab.png`, fullPage: true });
  await panel.locator('.hk-subtab[data-tab="history"]').click();
  await expect(panel.locator('.hk-hist-group').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/8e-panel-appliance-history-tab.png`, fullPage: true });

  // 8b. Delete now asks for confirmation, and the confirm carries the one solid red
  // fill in the panel — `danger-primary`, the weight reserved for a surface whose
  // whole purpose is the deletion. (The old `destructive` attribute selected here
  // was never read by ha-button; see utils.ts BtnWeight.)
  // (issue #173) — no more one-click loss of an appliance's documents/parts/history.
  await panel.locator('.d-del').click();
  await expect(page.locator('.hk-confirm-scrim ha-button[data-hk-weight="danger-primary"]')).toBeAttached({
    timeout: 5_000,
  });
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/8b-panel-appliance-delete-confirm.png`, fullPage: false });
  // Dismiss via Escape so the seeded appliance survives for later shots.
  await page.keyboard.press('Escape');
  await expect(page.locator('.hk-confirm-scrim')).toHaveCount(0, { timeout: 5_000 });

  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 8c + 5b. Archive/restore — an appliance that was replaced can be archived instead
  // of deleted, keeping its documents/parts/history but tucking it out of the default
  // list. A throwaway appliance (not the seeded water heater other shots depend on)
  // demonstrates the flow.
  await page.evaluate(async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    await hass.callService('home_keeper', 'add_asset', { name: 'Old chest freezer' });
  });
  await openPanel(page);
  await panel.locator('#tab-appliances').click();
  await panel.locator('.detail-open', { hasText: 'Old chest freezer' }).click();
  await expect(panel.locator('.d-archive')).toBeVisible();
  await panel.locator('.d-archive').click();
  await expect(panel.locator('.d-restore')).toBeVisible({ timeout: 5_000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/8c-panel-appliance-archived-detail.png`, fullPage: true });
  await panel.locator('#back-btn').click();

  // The Active filter hides the archived appliance; switching to Archived shows it
  // with its "Archived" chip.
  await expect(panel.locator('.hk-seg[data-seg="assetFilter"]')).toBeVisible();
  await panel
    .locator('.hk-seg[data-seg="assetFilter"] button', { hasText: 'Archived' })
    .click();
  await expect(panel.locator('ha-assist-chip.hk-archived').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/5b-panel-appliances-archived-list.png`, fullPage: true });
  // Reset to Active so the remaining appliance shots see the normal list.
  await panel.locator('.hk-seg[data-seg="assetFilter"] button', { hasText: 'Active' }).click();

  // 6. Appliance create form — virtual device, metadata, parts and relationships.
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-asset-form')).toBeVisible();
  const assetForm = panel.locator('#hk-asset-form');
  await fillText(assetForm, 0, 'Garage water heater'); // name
  await fillText(assetForm, 1, 'Rheem'); // manufacturer
  // The advanced "Custom fields" and "Parts & wear items" sections collapse by
  // default on a fresh appliance — expand them before filling them in.
  const expandSection = async (title: string): Promise<void> => {
    const summary = assetForm
      .locator('details.hk-collapsible > summary')
      .filter({ hasText: title })
      .first();
    const details = assetForm
      .locator('details.hk-collapsible')
      .filter({ hasText: title })
      .first();
    if (!(await details.evaluate((d: HTMLDetailsElement) => d.open))) await summary.click();
  };
  await expandSection('Parts & wear items');
  await expandSection('Custom fields');
  // Add a wear part to show the parts editor + replacement interval.
  await panel.locator('#a-add-part').click();
  const part = panel.locator('.hk-part').first();
  await fillText(part, 0, 'Anode rod'); // part name
  await fillText(part, 1, 'AR-1'); // part number
  await chooseHaSelect(part.locator('ha-select').first(), 'wear item');
  // Number selectors in part order: cost #0, stock #1, reorder-at #2, and (after
  // switching to wear) replace-interval #3. Fill spare-inventory + interval so the
  // shot shows stock tracking alongside the maintenance cadence.
  const partNums = panel.locator('.hk-part').first().locator('ha-selector-number');
  await partNums.nth(1).locator('input').fill('2'); // stock
  await partNums.nth(2).locator('input').fill('1'); // reorder at
  await partNums.nth(3).locator('input').fill('12'); // replace interval
  // The wear part now exposes a "Last replaced" date field so the maintenance
  // schedule can start from the real date rather than "now".
  await expect(panel.locator('.hk-part').first().locator('ha-selector-date')).toBeVisible();
  // Custom fields: quick-add a text and a (trackable) date metadata entry so the
  // shot shows the flexible metadata editor — label/type/value rows plus the
  // one-click seed buttons for the common fields.
  await assetForm.locator('ha-button', { hasText: 'Serial number' }).click();
  await assetForm.locator('ha-button', { hasText: 'Warranty expiry' }).click();
  // The metadata seeds and the documents "add a document" area both use .hk-meta-seeds;
  // assert on the metadata one specifically (it carries the seed buttons we just used).
  await expect(assetForm.locator('.hk-meta-seeds').first()).toBeVisible();
  await shotWithDrawer(page, `${OUT}/6-panel-appliance-create.png`);

  // 6b. Appliance create form — existing device. Previously this only offered a
  // device picker; it now gets the same manufacturer/model/serial/icon fields a
  // virtual appliance does, and picking a device prefills any that are empty from
  // its own registry entry (issue #145). Points at the seeded "Radio shade
  // controller" device — its registry entry already carries a manufacturer/model,
  // the same way a device reported by any other integration would.
  await openPanel(page);
  await panel.locator('#tab-appliances').click();
  await panel.locator('#add-btn').click();
  const existingForm = panel.locator('#hk-asset-form');
  await expect(existingForm).toBeVisible();
  await chooseHaSelect(existingForm.locator('ha-select').first(), /Existing device/);
  await expect(existingForm.locator('ha-selector-icon')).toHaveCount(1);
  // The device picker is HA's modern searchable picker: a button that opens an
  // overlay with a search box and a results list (`#list-item-0` is the first hit).
  await existingForm.locator('ha-selector-device').first().locator('button').click();
  await page.getByPlaceholder('Search').fill('Radio shade controller');
  await page.locator('#list-item-0').click();
  // Manufacturer is the first field after name in the identity schema — confirms the
  // prefill actually landed before the shot is taken.
  await expect(existingForm.locator('ha-selector-text').nth(1).locator('input')).toHaveValue('Lutron');
  await shotWithDrawer(page, `${OUT}/6b-panel-appliance-create-existing.png`);

  // 21. Appliance documents (offline manuals) — editing a saved appliance shows the
  // "Manuals & documents" editor: each existing document is a card (name + details)
  // with Open / Edit / Remove actions (here a manual link migrated from the legacy
  // manual_url), separated from a clearly labelled "Add a document" area with add-link
  // and upload-file controls for attaching another link or a local PDF/image.
  await openPanel(page);
  await panel.locator('#tab-appliances').click();
  await panel.locator(`.detail-open[data-detail-id="${ASSET.waterHeater}"]`).click();
  await expect(panel.locator('.d-edit')).toBeVisible();
  await panel.locator('.d-edit').click();
  const docForm = panel.locator('#hk-asset-form');
  await expect(docForm).toBeVisible();
  await expect(docForm.getByText('Manuals & documents')).toBeVisible();
  await expect(docForm.locator('.hk-doc-card').first()).toBeVisible();
  await expect(docForm.getByText('Add a document')).toBeVisible();
  await expect(docForm.locator('ha-button', { hasText: 'Upload file' })).toBeVisible();
  // The documents editor sits well down the drawer, which scrolls its own content —
  // so bring it into view and photograph what is on screen rather than the whole
  // page, which would show the top of the form instead of the section this documents.
  await docForm.getByText('Manuals & documents').scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);
  await page.screenshot({
    path: `${OUT}/32-panel-appliance-documents.png`,
    fullPage: false,
  });

  // 32b. Upload rejected before it starts — picking a file over the 100 MB ceiling
  // fails instantly, and the error renders right under the Upload file button
  // instead of in the form-level banner far below the fold (issue #159).
  await docForm
    .locator('.hk-doc-add input[type="file"]')
    .evaluate((picker: HTMLInputElement) => {
      const file = new File([new Uint8Array(8)], 'water-heater-manual.pdf', {
        type: 'application/pdf',
      });
      Object.defineProperty(file, 'size', { value: 101 * 1024 * 1024 });
      const dt = new DataTransfer();
      dt.items.add(file);
      Object.defineProperty(picker, 'files', { value: dt.files, configurable: true });
      picker.dispatchEvent(new Event('change'));
    });
  const uploadError = docForm.locator('.hk-doc-add ha-alert[alert-type="error"]');
  await expect(uploadError).toBeVisible();
  await expect(uploadError).toContainText('100 MB');
  // Viewport-framed on the documents area: a fullPage shot of this very long form
  // shrinks the error to a few unreadable pixels.
  await docForm.locator('.hk-doc-add').scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/32b-panel-appliance-upload-error.png` });

  // 32c. Upload in progress — the bar, percentage/byte counter and Cancel upload.
  // Upload throughput is throttled via CDP and the file is ~2 MB, so the bar shows
  // real byte progress rather than a synthesized state (a loopback upload of a small
  // file completes before a single progress event lands).
  // Let the previous step's toast expire so it doesn't bleed into this shot.
  await page.waitForTimeout(6000);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', {
    offline: false,
    latency: 0,
    downloadThroughput: -1,
    uploadThroughput: 256 * 1024, // bytes/s
  });
  const uploadChooser = page.waitForEvent('filechooser');
  await docForm.locator('ha-button', { hasText: 'Upload file' }).click();
  await (await uploadChooser).setFiles({
    name: 'water-heater-manual.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.concat([
      Buffer.from('%PDF-1.7\n'),
      Buffer.alloc(2 * 1024 * 1024, 0x30),
      Buffer.from('\n%%EOF\n'),
    ]),
  });
  const uploadLabel = docForm.locator('.hk-upload-label');
  await expect(uploadLabel).toContainText('%', { timeout: 20_000 });
  await docForm.locator('.hk-doc-add').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${OUT}/32c-panel-appliance-upload-progress.png` });
  await cdp.send('Network.emulateNetworkConditions', {
    offline: false,
    latency: 0,
    downloadThroughput: -1,
    uploadThroughput: -1,
  });
  await expect(docForm.locator('#hk-upload')).toHaveCount(0, { timeout: 30_000 });

  // 35. Part delete confirmation dialog — clicking the trash icon on a part now
  // shows a confirmation dialog before removing it (previously the icon was
  // invisible and deletion was immediate). Navigate to the water heater edit form,
  // expand the Parts section, and click the delete button on the first part to
  // show the dialog.
  await openPanel(page);
  await panel.locator('#tab-appliances').click();
  await panel.locator(`.detail-open[data-detail-id="${ASSET.waterHeater}"]`).click();
  await expect(panel.locator('.d-edit')).toBeVisible();
  await panel.locator('.d-edit').click();
  const partEditForm = panel.locator('#hk-asset-form');
  await expect(partEditForm).toBeVisible();
  // Expand Parts section if collapsed.
  const partsDetails = partEditForm.locator('details').filter({ hasText: 'Parts & wear items' });
  if (await partsDetails.count() > 0) {
    const open = await partsDetails.first().evaluate((d: HTMLDetailsElement) => d.open);
    if (!open) await partsDetails.first().locator('summary').click();
  }
  await expect(partsDetails.locator('.hk-part').first()).toBeVisible();
  // Click the delete (trash) icon-button on the first PART (scoped to the Parts
  // section so the Custom Fields rows — which share the same class names — are
  // excluded).
  await partsDetails.locator('.hk-part').first().locator('ha-icon-button.part-del').click();
  // Scrim is appended to document.body (not shadow root) so use page.locator.
  await expect(
    page.locator('.hk-confirm-scrim ha-button[data-hk-weight="danger-primary"]'),
  ).toBeAttached({ timeout: 5_000 });
  await page.waitForTimeout(500);
  // Viewport screenshot — position:fixed overlays render correctly here.
  await page.screenshot({ path: `${OUT}/35-panel-part-delete-confirm.png`, fullPage: false });
  // Dismiss via Escape key (our keydown handler closes the overlay).
  await page.keyboard.press('Escape');
  await expect(page.locator('.hk-confirm-scrim')).toHaveCount(0, { timeout: 5_000 });

  // 38. A part's attached file: the Anode rod part (seeded with a file, and first in
  // the list) shows a card — icon, filename · size · type, Open / Remove — right in
  // its editor, below the part's own fields. (The part's name lives inside a form
  // input, not rendered text, so we select by position — same as the delete-icon
  // click above — rather than by name text.)
  await expect(partsDetails.locator('.hk-part').first().locator('.hk-doc-card')).toBeVisible();
  await centre(partsDetails.locator('.hk-part').first().locator('.hk-doc-card'));
  await page.waitForTimeout(400);
  await shotWithDrawer(page, `${OUT}/38-panel-part-file.png`);

  // 39. Auto-create buy task: a stock-tracked part with a reorder threshold can opt
  // into an auto-created "Buy {part}" reminder when it runs low. Enabling the toggle
  // reveals a Restock quantity (the spares added back to stock on completing the
  // reminder). The consumable "Sediment pre-filter" (last part, with a reorder
  // threshold) is the natural home for a buy reminder — flip it on, fill the quantity,
  // and capture just that part card.
  const buyPart = partsDetails.locator('.hk-part').last();
  await buyPart.scrollIntoViewIfNeeded();
  await buyPart.locator('ha-switch').first().click();
  await expect(buyPart.getByText('Restock quantity', { exact: false })).toBeVisible();
  const buyNumbers = await buyPart.locator('ha-selector-number').count();
  await buyPart.locator('ha-selector-number').nth(buyNumbers - 1).locator('input').fill('4');
  await page.waitForTimeout(400);
  await buyPart.scrollIntoViewIfNeeded();
  await shotVisible(page, buyPart, `${OUT}/39-panel-part-auto-buy.png`);

  // 47. Stock measured rather than counted (issue #220): the seeded "Descaling
  // solution" part (third, the only one with a unit) keeps its stock in millilitres
  // and uses 250 of them per completion, so its editor shows the Stock unit and
  // Used-per-completion fields alongside a decimal-capable Stock and Reorder at.
  const measuredPart = partsDetails.locator('.hk-part').nth(2);
  await measuredPart.scrollIntoViewIfNeeded();
  await expect(measuredPart.getByText('Stock unit', { exact: false })).toBeVisible();
  await expect(measuredPart.getByText('Used per completion', { exact: false })).toBeVisible();
  await page.waitForTimeout(400);
  await shotVisible(page, measuredPart, `${OUT}/47-panel-part-measured-stock.png`);

  // 47b. The same part in the appliance's read view: the unit rides with the amount
  // on both the on-hand chip and the per-completion chip.
  await openPanel(page);
  await panel.locator('#tab-appliances').click();
  await panel.locator(`.detail-open[data-detail-id="${ASSET.waterHeater}"]`).click();
  const measuredRow = panel.locator('.hk-part-row').filter({ hasText: 'Descaling solution' });
  await measuredRow.scrollIntoViewIfNeeded();
  await expect(measuredRow.getByText('In stock: 750 ml')).toBeVisible();
  await page.waitForTimeout(400);
  await measuredRow.screenshot({ path: `${OUT}/47b-panel-part-measured-chips.png` });

  // 17-pre. Point the buy-reminder mirror at the household shopping list and opt
  // the seeded anode rod (already sitting at its reorder point) into auto-buy, so
  // the Settings shots below show the picker holding a real list and the dashboard
  // shot at the end shows the "Buy …" line the shopper actually gets.
  await openPanel(page);
  await page.evaluate(async (IDS) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    await hass.callService('home_keeper', 'set_options', {
      shopping_list_entity: 'todo.shopping_list',
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { assets } = await hass.callWS({ type: 'home_keeper/get_assets' });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const heater = assets.find((a: any) => a.id === IDS.ASSET.waterHeater);
    // A part's attached file is upload-only, so the service schema rejects any
    // payload carrying file_* — echo back only the fields it accepts.
    const WRITABLE = [
      'id',
      'name',
      'part_number',
      'type',
      'vendor',
      'cost',
      'url',
      'notes',
      'replace_interval',
      'replace_unit',
      'last_replaced',
      'stock',
      'reorder_at',
      'stock_unit',
      'consume_quantity',
      'create_buy_task',
      'restock_quantity',
    ];
    await hass.callService('home_keeper', 'update_asset', {
      asset_id: heater.id,
      parts: heater.parts.map((p: Record<string, unknown>) => {
        const out: Record<string, unknown> = {};
        for (const key of WRITABLE) if (p[key] !== undefined && p[key] !== null) out[key] = p[key];
        if (p.id === IDS.PART.anode) {
          out.create_buy_task = true;
          out.restock_quantity = 4;
        }
        return out;
      }),
    });
    // Enabling auto-buy on a part that is *already* at its reorder point creates the
    // buy task but crosses no threshold, and the shopping-list mirror syncs on the
    // crossing. Nudge the stock up and back so the crossing actually happens — the
    // part ends on its seeded quantity either way. Without this the shot only worked
    // when an earlier suite run had happened to move the stock first.
    for (const delta of [1, -1]) {
      await hass.callService('home_keeper', 'adjust_part_stock', {
        asset_id: heater.id,
        part_id: IDS.PART.anode,
        delta,
      });
      await new Promise((r) => setTimeout(r, 1000));
    }
  }, { ASSET, PART });

  // 16b. The task list now that a part is low, which is the only moment these two
  // shots say anything. A buy reminder has no due date of its own, so it reads as
  // due immediately — it gets its own **Shopping** section rather than joining the
  // overdue pile, and a "Low stock" pill in place of the overdue one.
  await openPanel(page);
  await panel.locator('#tab-tasks').click();
  await expect(panel.locator('details.hk-group[data-bucket="shopping"]')).toBeVisible();
  await page.screenshot({ path: `${OUT}/45-panel-shopping-section.png`, fullPage: true });

  // 16c. …and the Shopping filter on its own, now that it has something to filter to.
  await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn', { hasText: 'Shopping' }).click();
  await expect(panel.locator('ha-card.hk-card')).not.toHaveCount(0);
  await page.screenshot({ path: `${OUT}/44-panel-shopping-filter.png`, fullPage: true });
  await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn', { hasText: 'All' }).click();

  // 17. The Settings tab — friendly forms mirroring the options flow: a General
  // card (one-off retention), a Shopping list card (where auto-buy reminders are
  // mirrored) and a Problem sensor sync card (toggle + entity / device / area /
  // label exclusions), each saved on change.
  await openPanel(page);
  await panel.locator('#tab-settings').click();
  await expect(panel.locator('#hk-settings')).toBeVisible();
  await expect(panel.locator('#hk-settings ha-form').first()).toBeVisible();
  await expect(panel.locator('#hk-settings-shopping ha-form')).toBeVisible();
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/17-panel-settings.png`, fullPage: true });

  // 17s. The Shopping list card on its own, for the README section about mirroring
  // buy reminders onto an existing to-do list.
  await panel.locator('#hk-settings-shopping').scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);
  await panel
    .locator('#hk-settings-shopping')
    .screenshot({ path: `${OUT}/45-panel-settings-shopping.png` });

  // 17a. Settings → Profiles + Notifications. A Profile is a standalone saved filter;
  // a Notification is a delivery binding that references one. Seed one of each via the
  // public set_options service so both editors render populated. "Upstairs" carries an
  // area exclusion so the shot shows the exclude_* rows holding a real value, not three
  // empty pickers; "My chores" stays unfiltered because the Tasks-tab shot below
  // filters the admin list by it.
  //
  // "My chores" also carries the `sync` block that syncs its tasks onto "Family
  // chores" — the seeded local_todo list standing in for a Todoist project. That is
  // where a to-do list sync lives now, so seeding it here is what gives the profile
  // shots below (and the synced-list shot at 48) something real to show: an
  // unconfigured Sync group is an empty picker, and an unsynced list is a blank card.
  await page.evaluate(async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const areas: any[] = await hass.callWS({ type: 'config/area_registry/list' });
    const downstairs = areas.find((a) => a.area_id === 'living_room') ?? areas[0];
    await hass.callService('home_keeper', 'set_options', {
      profiles: [
        {
          id: 'demo_me',
          name: 'My chores',
          filter: {
            status: 'overdue',
            labels: [],
            areas: [],
            devices: [],
            exclude_labels: [],
            exclude_areas: [],
            exclude_devices: [],
          },
          sync: {
            entity_id: 'todo.family_chores',
            two_way: true,
            vanish_as_completed: true,
          },
        },
        {
          id: 'demo_upstairs',
          name: 'Upstairs',
          filter: {
            status: 'due_soon',
            labels: [],
            areas: [],
            devices: [],
            exclude_labels: [],
            exclude_areas: downstairs ? [downstairs.area_id] : [],
            exclude_devices: [],
          },
        },
        {
          // A Profile no task can satisfy, so the notification below renders the
          // *other* state of the button beside Test. Without it the shot would only
          // ever document the enabled half of a control that has two.
          id: 'demo_empty',
          name: 'The boat',
          filter: {
            status: 'overdue',
            labels: [],
            areas: [],
            devices: ['demo_no_such_device'],
            exclude_labels: [],
            exclude_areas: [],
            exclude_devices: [],
          },
        },
      ],
      notifications: [
        {
          id: 'demo_walk',
          name: 'Walk my chores',
          profile_id: 'demo_me',
          targets: [],
          actions: ['complete', 'snooze', 'open'],
          snooze_hours: 24,
          style: 'walk',
          // Urgency is seeded so the shot shows the control holding a real value rather
          // than the default choice. The channel is left empty on purpose and typed in
          // below, which is what puts the card's autosave status in the shot.
          channel: '',
          urgency: 'high',
          auto: { overdue: true, due_soon: false },
        },
        {
          // Bound to the Profile that matches nothing, so its footer shows the greyed
          // "Test a task" beside a Test that can still deliver the all-clear.
          id: 'demo_boat',
          name: 'Boat jobs',
          profile_id: 'demo_empty',
          targets: [],
          actions: ['complete', 'open'],
          snooze_hours: 24,
          style: 'digest',
          channel: 'Boat',
          urgency: 'normal',
          auto: { overdue: false, due_soon: false },
        },
      ],
    });
  });
  await openPanel(page);
  await panel.locator('#tab-settings').click();
  // Settings → Profiles — the standalone saved-filter editor. Rows collapse by
  // default; expand each so its editor form shows in the shot. Only the *row*
  // headers are clicked: each row also holds a Sync group with a header of its own,
  // which opens itself when the profile has a list configured, so clicking those
  // would fold shut the one state worth showing.
  await expect(panel.locator('#hk-profiles')).toBeVisible();
  for (const h of await panel.locator('#hk-profiles .hk-item-card > .hk-item-header').all()) {
    await h.click();
  }
  await expect(panel.locator('#hk-profiles .hk-item-body ha-form').first()).toBeVisible();
  await page.waitForTimeout(700);
  await panel.locator('#hk-profiles').screenshot({ path: `${OUT}/profiles-card.png` });
  // Settings → Notifications — delivery bindings that each reference a Profile.
  // Scoped to the card rather than the page: Settings is long enough after the rail
  // redesign that a full-page shot renders this editor's fields too small to read,
  // and the card is what the README caption describes anyway.
  await expect(panel.locator('#hk-notifications')).toBeVisible();
  for (const h of await panel.locator('#hk-notifications .hk-item-header').all()) await h.click();
  await expect(panel.locator('#hk-notifications .hk-item-body ha-form').first()).toBeVisible();
  // Type the channel rather than seeding it, so the shot carries the autosave status
  // this card reports with. There is no Save button here, and the status beside the
  // section name is the only thing that says a change was written — a capture with an
  // empty header would document the card as it never actually looks in use.
  await panel
    .locator('#hk-notifications .hk-item-card')
    .first()
    .locator('ha-selector-text')
    .nth(1)
    .locator('input')
    .fill('Chores');
  await expect(panel.locator('#hk-notifications .hk-save-status')).toHaveText('Saved', {
    timeout: 15_000,
  });
  await page.waitForTimeout(300);
  await panel.locator('#hk-notifications').screenshot({ path: `${OUT}/22-panel-notifications.png` });

  // 17a2. The Tasks tab Profile dropdown — pick a saved Profile to filter the admin list.
  await openPanel(page);
  await expect(panel.locator('select[data-profile-filter]')).toBeVisible();
  // Open the native popup itself before selecting anything: its <option> list is
  // rendered by the browser, not the page, so the closed-control screenshot below
  // can't prove the popup is themed too.
  await panel.locator('select[data-profile-filter]').click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/23b-panel-profile-dropdown-open.png` });
  await page.keyboard.press('Escape');
  await panel.locator('select[data-profile-filter]').selectOption('demo_me');
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/23-panel-profile-filter.png`, fullPage: true });

  // 17b. Settings → Companions — integrations that work with Home Keeper. The e2e
  // container ships two stub companion integrations (tests/integration/stubs) that
  // are bind-mounted + installed via seeded config entries: Pawsistant self-registers
  // on setup (push), and the Battery Notes glue is detected from the catalog (pull).
  // So the section populates on its own — no in-test seeding needed.
  await openPanel(page);
  await panel.locator('#tab-settings').click();
  await expect(panel.locator('#hk-companions')).toBeVisible();
  await expect(panel.locator('.hk-comp-configure').first()).toBeVisible();
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/21-panel-companions.png`, fullPage: true });

  // 17c. Settings → Profiles → "My chores" → its **Sync to a to-do list** group: the
  // to-do list this profile's tasks are synced onto ("Family chores", the seeded
  // local_todo list standing in for a Todoist project), plus what a change over there
  // means here. The sync block was seeded onto the profile at 17a, so the picker is
  // holding a real list rather than sitting empty.
  //
  // The profile row is shot on its own, not the whole card: the group is *inside* one
  // profile, and that containment is the thing the shot has to show — there is no
  // separate sync record and no Delete button, because clearing the picker is both
  // the off switch and the delete.
  await openPanel(page);
  await panel.locator('#tab-settings').click();
  await expect(panel.locator('#hk-profiles')).toBeVisible();
  const syncedProfile = panel
    .locator('#hk-profiles .hk-item-card')
    .filter({ hasText: 'My chores' })
    .first();
  // Rows collapse by default; the Sync group inside opens itself because a list is
  // configured, so one click on the row header is the whole reveal. Home Assistant
  // replaces the custom-panel element a few seconds after a page settles, though, and
  // a fresh panel starts with every row folded — so the row is re-opened right before
  // the shutter rather than once, or the shot catches a collapsed header.
  const openSyncedProfile = async (): Promise<void> => {
    const header = syncedProfile.locator('> .hk-item-header');
    if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click();
    await expect(syncedProfile.locator('.hk-sync-group .hk-item-body ha-form')).toBeVisible();
  };
  await openSyncedProfile();
  await syncedProfile.scrollIntoViewIfNeeded();
  await page.waitForTimeout(700);
  await openSyncedProfile();
  await syncedProfile.screenshot({ path: `${OUT}/47-panel-profile-sync.png` });

  // 48. The payoff: the synced chores sitting on the family's own to-do list, each
  // with the due date that makes it actionable on somebody's phone.
  //
  // Taller viewport for this one shot: the card runs past the 720px default, and an
  // element screenshot of something that has to be scrolled to catches Home
  // Assistant's *sticky* top bar across its head — which ate the card's own "Family
  // chores" title, the one thing that says which list this is. Restored afterwards so
  // the closing dashboard shot keeps its established framing.
  await page.setViewportSize({ width: DESKTOP.width, height: 1280 });
  await openDashboard(page);
  const familyCard = page
    .locator('hui-todo-list-card, todo-list-card')
    .filter({ hasText: 'Family chores' })
    .first();
  await expect(
    familyCard.locator('ha-check-list-item, ha-md-list-item').first(),
  ).toBeVisible({ timeout: 40_000 });
  await page.waitForTimeout(600);
  await familyCard.screenshot({ path: `${OUT}/48-todo-sync-synced-task.png` });
  await page.setViewportSize(DESKTOP);

  // 46. The payoff: the buy reminder sitting on the household's own shopping list,
  // where a voice assistant or a phone widget will read it out.
  await openDashboard(page);
  const shoppingCard = page
    .locator('hui-todo-list-card, todo-list-card')
    .filter({ hasText: 'Shopping list' })
    .first();
  await expect(shoppingCard).toContainText('Buy Anode rod', { timeout: 30_000 });
  await page.waitForTimeout(600);
  await shoppingCard.screenshot({ path: `${OUT}/46-shopping-list-buy-reminder.png` });

  // 4. The usage surfaces — native to-do list + calendar on a dashboard.
  await openDashboard(page);
  await page.waitForTimeout(1500); // let cards settle
  await page.screenshot({ path: `${OUT}/4-usage-todo-and-calendar.png`, fullPage: true });

  // 50-53. The phone layout, which is different enough from the desktop one that the
  // shots above document none of it: the tabs are along the bottom, Add floats, and
  // Settings opens on an index rather than six expanded sections. Asserted in
  // tests/responsive-layout.spec.ts and tests/settings-narrow.spec.ts — these only
  // photograph it. Last in the file because it changes the viewport; restored below
  // so a shot appended after this one does not silently inherit a phone width.
  await page.setViewportSize(PHONE);

  await openPanel(page);
  // Shot 23 left a Profile selected, and a filtered list hides the scope pills —
  // which are the single most phone-specific thing on this screen, since they are
  // what comes apart into wrapping chips below 700px. Clear it first.
  await panel.locator('select[data-profile-filter]').selectOption('');
  await expect(panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn').first()).toBeVisible();
  await expect(panel.locator('#hk-list')).toBeVisible();
  await expect(panel.locator('.hk-bottombar')).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/52-panel-mobile-tasks.png` });

  await panel.locator('#mtab-appliances').click();
  await expect(panel.locator('#hk-list')).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/53-panel-mobile-appliances.png` });

  await panel.locator('#mtab-settings').click();
  await expect(panel.locator('.hk-index-row').first()).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/50-panel-mobile-settings-index.png` });

  await panel.locator('.hk-index-row[data-section="problem"]').click();
  await expect(panel.locator('#hk-settings')).toBeVisible();
  await expect(panel.locator('.hk-settings-backbar')).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/51-panel-mobile-settings-section.png` });

  await page.setViewportSize(DESKTOP);
});
