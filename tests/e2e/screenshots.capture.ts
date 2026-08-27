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
import { test, expect, Locator } from '@playwright/test';
import { openPanel, openDashboard } from './tests/helpers';
import { ASSET, PART, TASK } from './fixture-ids';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

/**
 * Expand a collapsed `<details>` group, leaving an already-open one alone.
 *
 * Toggling a `<details>` is not idempotent, and several steps below reach into the
 * same Monitored group: a blind `summary.click()` in a later step closes what an
 * earlier one opened, and the shot silently captures a collapsed group.
 */
async function expandGroup(group: Locator): Promise<void> {
  if (!(await group.evaluate((el: HTMLDetailsElement) => el.open))) {
    await group.locator('summary').click();
  }
}

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

  // 0. First-run orientation banner — shown above the list until dismissed. Capture
  // it, then dismiss so the remaining task-list shots keep their established framing.
  await expect(panel.locator('.hk-intro')).toBeVisible();
  await page.screenshot({ path: `${OUT}/0-panel-first-run-intro.png`, fullPage: true });
  await panel.locator('ha-button.hk-intro-dismiss').click();
  await expect(panel.locator('.hk-intro')).toHaveCount(0);

  await page.screenshot({ path: `${OUT}/1-panel-task-list.png`, fullPage: true });

  // 1a1. Shopping filter — click the Shopping segment to show only buy-task tasks.
  await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn', { hasText: 'Shopping' }).click();
  await page.screenshot({ path: `${OUT}/44-panel-shopping-filter.png`, fullPage: true });
  // Switch back to All so the remaining shots see the full list.
  await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn', { hasText: 'All' }).click();

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
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/9-panel-managed-detail.png`, fullPage: true });

  // 1d. Edit form of a managed task — the integration-locked fields (name and
  // attach-to-device) are omitted; only the unlocked fields are editable.
  await panel.locator('.d-edit').click();
  await expect(panel.locator('#hk-task-form')).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/10-panel-managed-edit-locked.png`, fullPage: true });
  // Opening the edit form from a detail page already navigates to the list with the
  // form floating on top (see _openEdit's "leave any open detail page"), so Cancel
  // lands directly on the list — there's no detail page's #back-btn to click here.
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 1e. Tasks grouped by managing integration — managed tasks bucket under their
  // integration; everything else falls under "Your tasks".
  await panel.locator('.hk-seg[data-seg="group"] .hk-seg-btn', { hasText: 'Integration' }).click();
  await expect(panel.locator('details.hk-group').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/11-panel-grouped-by-integration.png`, fullPage: true });
  // Reset grouping so later list shots are unaffected.
  await panel.locator('.hk-seg[data-seg="group"] .hk-seg-btn', { hasText: 'Status' }).click();
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
  const nozzleDueChip = panel
    .locator(`ha-card.hk-card[data-id="${TASK.nozzleUsage}"] .hk-chips ha-assist-chip`)
    .first();
  await expect(nozzleDueChip).toHaveAttribute('label', 'in 180 h');
  await nozzleDueChip.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/1c-panel-usage-countdown.png`, fullPage: true });

  await panel.locator(`.detail-open[data-detail-id="${TASK.nozzleUsage}"]`).click();
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
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/15-panel-monitored-section.png`, fullPage: true });

  // 19. The Completed section — a one-off (do-once) task drops here once it's done,
  // leaving the active list but keeping its completion history. Collapsed by default
  // (like Monitored); expand it for the shot.
  const completed = panel.locator('details.hk-group[data-group-key="status:completed"]');
  await expandGroup(completed);
  await expect(completed.locator('.hk-card').first()).toBeVisible();
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

  // The Area picker in the task's edit form, holding the saved room. Editing from a
  // detail page returns to the list and re-opens the form there.
  await panel.locator('.d-edit').click();
  await expect(panel.locator('#hk-task-form')).toBeVisible();
  await expect(panel.locator('#hk-task-form ha-selector-area')).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/42b-panel-task-area-form.png`, fullPage: true });
  // The task form is an inline card, not an `ha-dialog` — Escape leaves it open and
  // it would then sit on top of the grouped-list shot below. Close it properly.
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });

  // 42c. Grouped by Area — what the picker buys you: the task now sorts into its room
  // instead of the "Unassigned" bucket it was stuck in.
  await panel.locator('.hk-seg[data-seg="group"] .hk-seg-btn', { hasText: 'Area' }).click();
  await expect(panel.locator('details.hk-group[data-group-key^="area:"]').first()).toBeVisible({
    timeout: 10_000,
  });
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/42c-panel-tasks-grouped-by-area.png`, fullPage: true });
  // Reset grouping so later list shots are unaffected.
  await panel.locator('.hk-seg[data-seg="group"] .hk-seg-btn', { hasText: 'Status' }).click();

  // 2. Create form — floating recurrence + device picker.
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-form')).toBeVisible();
  await fillText(panel.locator('#hk-task-form'), 0, 'Replace dishwasher filter');
  await page.screenshot({ path: `${OUT}/2-panel-create-floating.png`, fullPage: true });

  // 3. Create form switched to a fixed (anchored) schedule.
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').first(), /fixed schedule/i);
  await expect(panel.locator('#hk-task-form ha-selector-datetime').first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/3-panel-create-fixed.png`, fullPage: true });

  // 20. Create form switched to a one-off (do-once) task — no cadence, just a single
  // Due date picker. Completing it later sends it to the Completed section.
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').first(), /Just once/);
  await expect(panel.locator('#hk-task-form ha-selector-datetime').first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/20-panel-create-one-off.png`, fullPage: true });

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
  await page.screenshot({ path: `${OUT}/30-panel-create-sensor-task.png`, fullPage: true });


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
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/30b-panel-sensor-backstop.png`, fullPage: true });
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
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/31-panel-create-sensor-threshold.png`, fullPage: true });

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
  await page.screenshot({ path: `${OUT}/43-panel-create-sensor-state.png`, fullPage: true });

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
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await page.screenshot({
    path: `${OUT}/47-panel-sensor-starting-reading.png`,
    fullPage: true,
  });

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
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await page.screenshot({
    path: `${OUT}/34-panel-create-linked-consumable.png`,
    fullPage: true,
  });

  // 36. The same edit form also offers "Links to show on card" — a multi-select of
  // the attached appliance's document/metadata links. The seeded task pins two, which
  // the dashboard card renders as openable chips on the task's row.
  await expect(
    panel.locator('#hk-task-form').getByText('Links to show on card'),
  ).toBeVisible();
  await panel.locator('#hk-task-form').getByText('Links to show on card').scrollIntoViewIfNeeded();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await page.screenshot({
    path: `${OUT}/36-panel-task-card-links.png`,
    fullPage: true,
  });
  await panel.locator('#f-cancel').click();
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
  await expect(panel.locator('.hk-hist-group').first()).toBeVisible();
  // Appliances carry notes of their own now (issue #163) — a Markdown card with the
  // same inline editor as a task, plus per-part notes in the Parts section.
  await expect(panel.locator('ha-markdown table').first()).toBeVisible({ timeout: 15_000 });
  await expect(panel.locator('.hk-part-notes ha-markdown strong').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/8-panel-appliance-detail.png`, fullPage: true });

  // 8b. Delete now asks for confirmation and is styled as a destructive action
  // (issue #173) — no more one-click loss of an appliance's documents/parts/history.
  await panel.locator('.d-del').click();
  await expect(page.locator('.hk-confirm-scrim ha-button[destructive]')).toBeAttached({
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
  await page.screenshot({ path: `${OUT}/6-panel-appliance-create.png`, fullPage: true });

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
  await page.screenshot({ path: `${OUT}/6b-panel-appliance-create-existing.png`, fullPage: true });

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
  await page.waitForTimeout(400);
  await page.screenshot({
    path: `${OUT}/32-panel-appliance-documents.png`,
    fullPage: true,
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
    page.locator('.hk-confirm-scrim ha-button[destructive]'),
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
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/38-panel-part-file.png`, fullPage: true });

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
  await buyPart.screenshot({ path: `${OUT}/39-panel-part-auto-buy.png` });

  // 47. Stock measured rather than counted (issue #220): the seeded "Descaling
  // solution" part (third, the only one with a unit) keeps its stock in millilitres
  // and uses 250 of them per completion, so its editor shows the Stock unit and
  // Used-per-completion fields alongside a decimal-capable Stock and Reorder at.
  const measuredPart = partsDetails.locator('.hk-part').nth(2);
  await measuredPart.scrollIntoViewIfNeeded();
  await expect(measuredPart.getByText('Stock unit', { exact: false })).toBeVisible();
  await expect(measuredPart.getByText('Used per completion', { exact: false })).toBeVisible();
  await page.waitForTimeout(400);
  await measuredPart.screenshot({ path: `${OUT}/47-panel-part-measured-stock.png` });

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

  // 17. The Settings tab — friendly forms mirroring the options flow: a General
  // card (one-off retention), a Shopping list card (where auto-buy reminders are
  // mirrored) and a Problem sensor sync card (toggle + entity / device / area /
  // label exclusions), each saved on change.
  await openPanel(page);
  await panel.locator('#tab-settings').click();
  await expect(panel.locator('#hk-settings')).toBeVisible();
  await expect(panel.locator('#hk-settings ha-form')).toBeVisible();
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
          auto: { overdue: true, due_soon: false },
        },
      ],
    });
  });
  await openPanel(page);
  await panel.locator('#tab-settings').click();
  // Settings → Profiles — the standalone saved-filter editor. Rows collapse by
  // default; expand each so its editor form shows in the shot.
  await expect(panel.locator('#hk-profiles')).toBeVisible();
  for (const h of await panel.locator('#hk-profiles .hk-item-header').all()) await h.click();
  await expect(panel.locator('#hk-profiles .hk-item-body ha-form').first()).toBeVisible();
  await page.waitForTimeout(700);
  await panel.locator('#hk-profiles').screenshot({ path: `${OUT}/profiles-card.png` });
  // Settings → Notifications — delivery bindings that each reference a Profile.
  await expect(panel.locator('#hk-notifications')).toBeVisible();
  for (const h of await panel.locator('#hk-notifications .hk-item-header').all()) await h.click();
  await expect(panel.locator('#hk-notifications .hk-item-body ha-form').first()).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/22-panel-notifications.png`, fullPage: true });

  // 17a2. The Tasks tab Profile dropdown — pick a saved Profile to filter the admin list.
  await openPanel(page);
  await expect(panel.locator('select[data-profile-filter]')).toBeVisible();
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

  // 17c-pre. Point a task mirror at the household's own to-do list — "Family chores",
  // the seeded local_todo list standing in for a Todoist project — on the "My chores"
  // Profile seeded above. Both shots below need the feature actually running: an
  // unconfigured Settings card is an empty-state alert, and an unmirrored list is a
  // blank card.
  await openPanel(page);
  await page.evaluate(async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    await hass.callService('home_keeper', 'set_options', {
      task_mirrors: [
        {
          id: 'demo_family_chores',
          entity_id: 'todo.family_chores',
          profile_id: 'demo_me',
          two_way: true,
          vanish_as_completed: true,
        },
      ],
    });
  });

  // 17c. Settings → To-do list sync — each row pairs a Profile (or the default
  // "when due" filter) with an existing to-do list, and the two per-mirror switches
  // cover the awkward providers. Rows collapse by default, so expand it: a
  // collapsed row is just a header and says nothing about what a sync holds.
  await openPanel(page);
  await panel.locator('#tab-settings').click();
  await expect(panel.locator('#hk-task-mirrors')).toBeVisible();
  for (const h of await panel.locator('#hk-task-mirrors .hk-item-header').all()) await h.click();
  await expect(panel.locator('#hk-task-mirrors .hk-item-body ha-form').first()).toBeVisible();
  await panel.locator('#hk-task-mirrors').scrollIntoViewIfNeeded();
  await page.waitForTimeout(700);
  await panel
    .locator('#hk-task-mirrors')
    .screenshot({ path: `${OUT}/47-panel-settings-task-mirrors.png` });

  // 48. The payoff: the mirrored chores sitting on the family's own to-do list, each
  // with the due date that makes it actionable on somebody's phone.
  //
  // Taller viewport for this one shot: the card runs past the 720px default, and an
  // element screenshot of something that has to be scrolled to catches Home
  // Assistant's *sticky* top bar across its head — which ate the card's own "Family
  // chores" title, the one thing that says which list this is. Restored afterwards so
  // the closing dashboard shot keeps its established framing.
  await page.setViewportSize({ width: 1280, height: 1280 });
  await openDashboard(page);
  const familyCard = page
    .locator('hui-todo-list-card, todo-list-card')
    .filter({ hasText: 'Family chores' })
    .first();
  await expect(
    familyCard.locator('ha-check-list-item, ha-md-list-item').first(),
  ).toBeVisible({ timeout: 40_000 });
  await page.waitForTimeout(600);
  await familyCard.screenshot({ path: `${OUT}/48-todo-sync-mirrored-task.png` });
  await page.setViewportSize({ width: 1280, height: 720 });

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
});
