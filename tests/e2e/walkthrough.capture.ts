/**
 * One-off **video** walkthrough capture for PR / README documentation — not part
 * of the e2e suite (filename does not match *.spec.ts). It records narrated tours
 * of the Home Keeper panel as WebMs, which ci/capture-video.sh then transcodes to
 * mp4 (+ a GIF fallback) under docs/videos/.
 *
 * Run it through the wrapper (recommended — it does the ffmpeg transcode too):
 *   bash ci/capture-video.sh
 *
 * Or directly (raw WebM only), from tests/e2e/:
 *   VIDEO_DIR=../../docs/videos npx playwright test \
 *     --config=walkthrough.config.ts
 *
 * ## Two tours, one harness
 *
 * The phone layout is different enough that the desktop tour documents none of it:
 * the tabs are along the bottom, Add floats, the edit drawer is a modal sheet, and
 * Settings opens on an index. So there are two tours, each recorded in its own
 * context.
 *
 * A context, not a resize. `recordVideo.size` is fixed when the context is created,
 * so resizing mid-recording leaves a 390px viewport sitting in a third of a 1280x800
 * frame beside a grey void — which is why an earlier attempt at this concluded the
 * phone layout could not be recorded at all. A second context at 390x844 records it
 * correctly framed.
 *
 * Two `test()` blocks rather than one, so each gets its own timeout and a flaky
 * phone tour cannot take the desktop recording down with it — this is a soft gate,
 * and half a walkthrough beats none.
 *
 * Video needs the recording wired at the browser *context* level and the file is
 * only flushed when the context closes, so each tour builds its own authenticated
 * context (reusing the auth state global-setup wrote) rather than the default
 * `page` fixture, then saves the video to a stable name we can transcode.
 */
import { test, expect, Browser, Locator, Page } from '@playwright/test';
import { resolve } from 'path';
import { gotoTab, openPanel, openDashboard, openSettingsSection } from './tests/helpers';
import { ASSET, TASK } from './fixture-ids';
import { DESKTOP, PHONE, Viewport } from './viewports';

const OUT = process.env.VIDEO_DIR || '/tmp/home-keeper-video';
const STATE_PATH = resolve(__dirname, '.auth/state.json');

/** A readable pause so motion in the recording is easy to follow. */
const BEAT = 900;

type Tour = {
  /** Names the test, and the variant ci/capture-video.sh transcodes. */
  name: string;
  size: Viewport;
  /** Basename under VIDEO_DIR. Kept in step with ci/capture-video.sh's VARIANTS. */
  file: string;
  run: (page: Page, panel: Locator) => Promise<void>;
};

/**
 * Record one tour into a context of its own, and save it under a stable name.
 *
 * The whole of the per-tour mechanism, so the two scripts below are nothing but
 * beats. The recording is flushed to disk only on `context.close()`, after which
 * `page.video().saveAs()` can name it.
 */
async function recordTour(browser: Browser, tour: Tour): Promise<void> {
  const context = await browser.newContext({
    storageState: STATE_PATH,
    viewport: tour.size,
    recordVideo: { dir: OUT, size: tour.size },
  });
  const page = await context.newPage();
  try {
    await tour.run(page, page.locator('home-keeper-panel').first());
  } finally {
    await context.close();
    const video = page.video();
    if (video) await video.saveAs(resolve(OUT, tour.file));
  }
}

/** The wide tour: the panel as a desktop browser draws it. */
async function desktopTour(page: Page, panel: Locator): Promise<void> {
  // 1. Land on the admin panel — the task list with overdue / due-soon tasks and
  //    the first-run orientation banner.
  await openPanel(page);
  // Show the banner and dismiss it *if it is there*, rather than requiring it.
  //
  // Dismissal persists in HA's per-user frontend store, so the first attempt spends
  // it for the whole container — and a `toBeVisible()` here meant every Playwright
  // retry died on step 1 before reaching whatever had actually gone wrong. One flaky
  // beat later in the tour therefore read as three identical failures and burned the
  // retries that exist to absorb it. The run that matters (a fresh container, which
  // is what CI gives it) still lands on the banner and still lingers on it.
  const intro = panel.locator('.hk-intro');
  if (await intro.isVisible().catch(() => false)) {
    await page.waitForTimeout(BEAT * 2);
    await panel.locator('ha-button.hk-intro-dismiss').click();
    await expect(intro).toHaveCount(0);
  }
  // Let the list re-render/settle after the banner collapses before clicking into it.
  await expect(panel.locator('#add-btn')).toBeVisible();
  await page.waitForTimeout(BEAT);

  // 1b. Shopping filter — show the filter bar's new Shopping pill, which isolates
  //     auto-created buy tasks from the main task list.
  const shoppingBtn = panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="shopping"]');
  await shoppingBtn.scrollIntoViewIfNeeded();
  await shoppingBtn.click();
  await page.waitForTimeout(BEAT * 2);
  const allBtn = panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="all"]');
  await allBtn.click();
  await page.waitForTimeout(BEAT);

  // 2. Open a task's detail page — full schedule, notes, completion history, and
  //    (since this task is linked to a part with a product URL) a clickable
  //    "Consumable link" row that jumps straight to buying the replacement.
  const taskRow = panel.locator(`.detail-open[data-detail-id="${TASK.waterFilter}"]`);
  await expect(taskRow).toBeVisible();
  await taskRow.click();
  await expect(panel.locator('.hk-hist-list li').first()).toBeVisible();
  await page.waitForTimeout(BEAT * 2);

  // 2a. "Move date" on a history row — back-dates/corrects a completion's
  //     timestamp without touching its note/cost/photo/who. Escape without saving
  //     so the walkthrough leaves the seeded data untouched.
  await panel.locator('.hk-hist-move').first().click();
  await expect(panel.locator('ha-dialog[open] ha-selector-datetime').first()).toBeVisible();
  await page.waitForTimeout(BEAT * 2);
  await page.keyboard.press('Escape');
  await expect(panel.locator('ha-dialog[open]')).toHaveCount(0);
  await page.waitForTimeout(BEAT);

  // 2a2. Notes are Markdown. The seeded note already renders as headings, a
  //      numbered list, a quote and a link; open the inline editor to show it
  //      being authored, with the live preview updating as the text is typed.
  await panel.locator('.d-note-edit').click();
  const walkNote = panel.locator('.d-note-input');
  await expect(walkNote).toBeVisible();
  await page.waitForTimeout(BEAT);
  // Type rather than fill so the preview visibly catches up — that's the point.
  await walkNote.fill('');
  await walkNote.pressSequentially('## Next time\n\n- Order **two** cartridges\n', {
    delay: 28,
  });
  await expect(panel.locator('.hk-md-preview ha-markdown h2')).toBeVisible();
  await page.waitForTimeout(BEAT * 2);
  // Cancel — the tour must leave the seeded note as it found it.
  await panel.locator('.d-note-cancel').click();
  await expect(panel.locator('.d-note-edit')).toBeVisible();
  await page.waitForTimeout(BEAT);

  // 2a3. Edit opens beside the page rather than replacing it: the form slides in as a
  //      column and the schedule, notes and history stay where they were. Cancel, so
  //      the tour changes nothing here either.
  await panel.locator('.d-edit').click();
  await expect(panel.locator('#hk-task-form')).toBeVisible();
  await page.waitForTimeout(BEAT * 3);
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#hk-form')).toHaveCount(0);
  await page.waitForTimeout(BEAT);

  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();
  await page.waitForTimeout(BEAT);

  // 2a4. Duplicate. Ten near-identical tasks — one per moisture sensor — used to mean
  //      ten full trips through the form. Press Duplicate on a sensor task and the
  //      create form opens already filled in, everything but the history, the tag and
  //      the meter's starting reading, so the copy is a field or two from done. The
  //      pause after the click is the point: the form fills itself in. Cancel, so the
  //      tour leaves the seeded data as every later frame expects it.
  //
  //      A dormant usage task has no due date to sort by, so it lives in the collapsed
  //      Monitored group. Open that first — the row exists either way, which is why a
  //      plain click times out rather than failing on a missing locator.
  const monitored = panel.locator('details.hk-group[data-group-key="status:monitored"]');
  if (!(await monitored.evaluate((el: HTMLDetailsElement) => el.open))) {
    await monitored.locator('summary').click();
    await page.waitForTimeout(BEAT);
  }
  await panel.locator(`.detail-open[data-detail-id="${TASK.nozzleUsage}"]`).click();
  await expect(panel.locator('.d-dup')).toBeVisible();
  await page.waitForTimeout(BEAT);
  await panel.locator('.d-dup').click();
  await expect(panel.locator('#hk-task-form')).toBeVisible();
  await page.waitForTimeout(BEAT * 3);
  await panel
    .locator('#hk-task-form ha-selector-text input')
    .first()
    .fill('Water the ferns');
  await page.waitForTimeout(BEAT * 2);
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#hk-form')).toHaveCount(0);
  await page.waitForTimeout(BEAT);

  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();
  await page.waitForTimeout(BEAT);

  // 2b. A synced problem-sensor task. It mirrors a device_class: problem binary
  //     sensor, so it can't be completed here — but it has no device to model, so
  //     its detail page offers an inline note for next time the problem fires (the
  //     fix, a part number, where the shut-off is). The note persists across the
  //     mirror clearing/re-arming and even being deleted and recreated.
  const problemRow = panel
    .locator('.hk-card', { hasText: 'Sump pump problem' })
    .locator('.detail-open')
    .first();
  await expect(problemRow).toBeVisible();
  await problemRow.click();
  await expect(panel.locator('.hk-managed-prompt')).toBeVisible();
  await page.waitForTimeout(BEAT);
  await panel.locator('.d-note-edit').click();
  const noteBox = panel.locator('.d-note-input');
  await expect(noteBox).toBeVisible();
  await page.waitForTimeout(BEAT);
  await noteBox.fill(
    'Reset the pump breaker in the garage panel, then prime it. Spare float switch: part #SFS-200 in the utility drawer.',
  );
  await page.waitForTimeout(BEAT);
  await panel.locator('.d-note-save').click();
  await expect(panel.locator('.d-note-edit')).toBeVisible();
  await page.waitForTimeout(BEAT * 2);
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();
  await page.waitForTimeout(BEAT);

  // 2c. NFC/RFID tags. Bind a tag to the fridge-filter task (quick-log) and
  //     scan-lock the furnace filter, show the chips and the blocked Done with its
  //     explanatory toast, then unbind both so the seeded data is untouched.
  await page.evaluate(async (IDS) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const tags: any[] = await hass.callWS({ type: 'tag/list' });
    if (!tags.some((t) => t.id === 'fridge-filter-tag')) {
      await hass.callWS({ type: 'tag/create', tag_id: 'fridge-filter-tag', name: 'Fridge filter' });
    }
    await hass.callService('home_keeper', 'update_task', {
      task_id: IDS.TASK.fridgeFilter,
      tag_id: 'fridge-filter-tag',
    });
    await hass.callService('home_keeper', 'update_task', {
      task_id: IDS.TASK.furnaceFilter,
      tag_id: 'fridge-filter-tag',
      require_tag_scan: true,
    });
  }, { TASK });
  await page.goto('/home-keeper', { waitUntil: 'domcontentloaded' });
  await expect(panel.locator('#add-btn')).toBeVisible();
  const nfcChip = panel.locator(`.hk-card[data-id="${TASK.fridgeFilter}"] .hk-tag`);
  await expect(nfcChip).toBeVisible({ timeout: 10_000 });
  await nfcChip.scrollIntoViewIfNeeded();
  await page.waitForTimeout(BEAT * 2);
  // Tap the scan-locked task's greyed Done — the toast explains a scan is needed.
  const lockedDone = panel.locator(`.hk-card[data-id="${TASK.furnaceFilter}"] .done-blocked-wrap`);
  await expect(lockedDone).toBeVisible();
  await lockedDone.click();
  await page.waitForTimeout(BEAT * 3); // linger so the toast reads on video
  await page.evaluate(async (IDS) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    await hass.callService('home_keeper', 'update_task', {
      task_id: IDS.TASK.furnaceFilter,
      tag_id: null,
      require_tag_scan: false,
    });
    await hass.callService('home_keeper', 'update_task', {
      task_id: IDS.TASK.fridgeFilter,
      tag_id: null,
    });
  }, { TASK });
  await page.goto('/home-keeper', { waitUntil: 'domcontentloaded' });
  await expect(panel.locator('#add-btn')).toBeVisible();
  await page.waitForTimeout(BEAT);

  // 3. Create a task — the drawer opens beside the list rather than over it, so
  //    the list keeps its place while the form is filled in. Linger on that first,
  //    then show the recurrence picker switching modes.
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-form')).toBeVisible();
  await expect(panel.locator('.hk-shell-drawer')).toBeVisible();
  await page.waitForTimeout(BEAT * 2);
  await panel
    .locator('#hk-task-form ha-selector-text')
    .first()
    .locator('input, textarea')
    .fill('Replace dishwasher filter');
  await page.waitForTimeout(BEAT);
  const recurrence = panel.locator('#hk-task-form ha-select').first();
  await recurrence.click();
  await page.getByRole('menuitem', { name: /fixed schedule/i }).first().click();
  await expect(panel.locator('#hk-task-form ha-selector-datetime').first()).toBeVisible();
  await page.waitForTimeout(BEAT * 2);

  // 3a. Switch the same form to a **sensor** task and build the shape a real service
  //     interval has: a meter target plus a time backstop. Typing the target, then
  //     the "Or every" months, makes the live hint *and* the rule summary above the
  //     submit button rewrite themselves — watching "Every 300 of use" become
  //     "Every 300 of use, or every 6 months" as you type is the whole argument for
  //     that strip, and a still screenshot can't show it. Give each field a beat.
  await recurrence.click();
  await page.getByRole('menuitem', { name: /based on a sensor/i }).first().click();
  await expect(panel.locator('#hk-task-form ha-selector-entity').first()).toBeVisible();
  await page.waitForTimeout(BEAT);
  const numberAt = (nth: number) =>
    panel.locator('#hk-task-form ha-selector-number').nth(nth).locator('input');
  await numberAt(0).fill('300'); // Target (units of use)
  await expect(panel.locator('#hk-sensor-hint')).toBeVisible();
  await page.waitForTimeout(BEAT * 2);
  // Type a **starting reading** and watch the hint rewrite itself from a forward
  // guess ("reads 780 now, due at 1080") into a statement about where this machine
  // actually is ("counting from 700, 80 of 300 already used, due at 1000"). That
  // rewrite is the argument for the field, and only motion shows it.
  await numberAt(1).fill('700'); // Starting reading
  await expect(panel.locator('#hk-sensor-hint')).toContainText('Counting from 700');
  await page.waitForTimeout(BEAT * 3);
  // Flip "Also come due on a schedule" — the three backstop fields appear, already
  // seeded, and the summary gains its second half. That reveal is the beat.
  await panel.locator('#hk-task-form ha-selector-boolean ha-switch').first().click();
  await expect(panel.locator('#hk-task-form ha-selector-number')).toHaveCount(3);
  await page.waitForTimeout(BEAT);
  await numberAt(2).fill('6'); // Or every … (the time backstop)
  await expect(panel.locator('#hk-form-summary-value')).toHaveText(
    'Every 300 of use, or every 6 months',
  );
  await page.mouse.move(0, 0);
  await page.waitForTimeout(BEAT * 3); // linger on the summary + "whichever comes first"

  // 3a2. **State** mode — the binary-sensor case, and the one that only reads as a
  //      motion: bind a binary_sensor and the value control *changes shape*, from a
  //      free-text box into an On/Off picker, because a binary sensor has only those
  //      two states. A still can show the end state but not the swap, so pick the
  //      entity first, beat, then switch the mode and let the form re-render.
  await panel
    .locator('#hk-task-form ha-selector-entity')
    .first()
    .locator('ha-picker-field')
    .click();
  await page.locator('input[placeholder="Search"]:visible').first().fill('hk_demo_water_tank');
  await page
    .locator('ha-combo-box-item:visible')
    .filter({ hasText: /HK demo water tank low/ })
    .first()
    .click();
  await page.waitForTimeout(BEAT * 2);
  await panel.locator('#hk-task-form ha-select').nth(1).click();
  await page.getByRole('menuitem', { name: /^State$/ }).first().click();
  // The summary rewrites itself again, now describing a transition rather than a
  // meter — the same strip, tracking a completely different kind of rule.
  await expect(panel.locator('#hk-form-summary-value')).toHaveText('When it changes to on');
  await page.mouse.move(0, 0);
  await page.waitForTimeout(BEAT * 3);

  // Reset by re-opening the panel fresh — closing the create form does a full
  // route change back to /home-keeper that can race a click (the screenshots
  // harness resets the create form the same way).
  await openPanel(page);
  await expect(panel.locator('#add-btn')).toBeVisible();
  await page.waitForTimeout(BEAT);

  // 3b. A usage task in flight: the seeded nozzle task meters printer hours against
  //     a 300 h target with a 6-month backstop, so its detail page shows the progress
  //     bar filling and the "180 h to go" line. It's dormant, so it lives in the
  //     collapsed Monitored group.
  const monitoredGroup = panel.locator(
    'details.hk-group[data-group-key="status:monitored"]',
  );
  if (!(await monitoredGroup.evaluate((el: HTMLDetailsElement) => el.open))) {
    await monitoredGroup.locator('summary').click();
    await page.waitForTimeout(BEAT);
  }
  await panel.locator(`.detail-open[data-detail-id="${TASK.nozzleUsage}"]`).click();
  await expect(panel.locator('.hk-meter').first()).toBeVisible();
  await page.waitForTimeout(BEAT * 3);
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();
  await page.waitForTimeout(BEAT);

  // 4. Appliances — the asset list, then an appliance's detail page (parts,
  //    metadata, related tasks and maintenance history).
  await gotoTab(panel, 'appliances');
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.waitForTimeout(BEAT);

  // 4-tree. Tree view — toggle from the flat list to the tree so the
  //         parent/child nesting is visible, then switch back.
  await panel.locator('.hk-seg[data-seg="assetView"] .hk-seg-btn[data-seg-val="tree"]').click();
  await expect(panel.locator('.hk-tree-child').first()).toBeVisible();
  await page.waitForTimeout(BEAT * 2);
  await panel.locator('.hk-seg[data-seg="assetView"] .hk-seg-btn[data-seg-val="flat"]').click();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.waitForTimeout(BEAT);

  const applianceRow = panel.locator(`.detail-open[data-detail-id="${ASSET.waterHeater}"]`);
  await expect(applianceRow).toBeVisible();
  await applianceRow.click();
  // The list it came from stays beside it, with this appliance marked in it.
  await expect(panel.locator('ha-card.hk-card.hk-selected')).toBeVisible();
  await expect(panel.locator('.hk-part-row').first()).toBeVisible();
  await page.waitForTimeout(BEAT * 2);

  // 4-tabs. The appliance's sections are sub-tabs, each with a URL of its own, so
  //         Back leaves a sub-tab and one can be linked to directly. Walk them.
  for (const tab of ['tasks', 'documents', 'related'] as const) {
    await panel.locator(`.hk-subtab[data-tab="${tab}"]`).click();
    await expect(panel.locator(`.hk-subtab[data-tab="${tab}"].active`)).toBeVisible();
    await page.waitForTimeout(BEAT);
  }
  await panel.locator('.hk-subtab[data-tab="history"]').click();
  await expect(panel.locator('.hk-hist-group').first()).toBeVisible();
  await page.waitForTimeout(BEAT * 2);

  // 4a. Appliances carry Markdown notes of their own — the shut-off location, a
  //     spec table, the yearly drain — plus per-part notes down in Parts. They
  //     live under Details, with the identity fields.
  await panel.locator('.hk-subtab[data-tab="details"]').click();
  await expect(panel.locator('ha-markdown table').first()).toBeVisible();
  await panel.locator('ha-markdown table').first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(BEAT * 2);

  // 4a2. Delete now confirms before doing anything, and is styled as a destructive
  //      action — cancel it to show it's a safe, reversible click.
  await panel.locator('.d-del').scrollIntoViewIfNeeded();
  await panel.locator('.d-del').click();
  await expect(page.locator('.hk-confirm-scrim ha-button[variant="danger"]')).toBeAttached();
  await page.waitForTimeout(BEAT * 2);
  await page.locator('.hk-confirm-scrim ha-button').filter({ hasText: 'Cancel' }).click();
  await expect(page.locator('.hk-confirm-scrim')).toHaveCount(0);
  await page.waitForTimeout(BEAT);

  // 4a3. Archive — an appliance that was replaced can be tucked out of the default
  //      list without losing its documents/parts/history, and brought back any time.
  await panel.locator('.d-archive').click();
  await expect(panel.locator('.d-restore')).toBeVisible();
  await expect(panel.locator('.hk-managed-prompt')).toContainText('Archived');
  await page.waitForTimeout(BEAT * 2);
  await panel.locator('#back-btn').click();
  await expect(panel.locator('.hk-seg[data-seg="assetFilter"]')).toBeVisible();
  await panel
    .locator('.hk-seg[data-seg="assetFilter"] button', { hasText: 'Archived' })
    .click();
  await expect(panel.locator('ha-assist-chip.hk-archived').first()).toBeVisible();
  await page.waitForTimeout(BEAT * 2);
  await panel.locator(`.detail-open[data-detail-id="${ASSET.waterHeater}"]`).click();
  await expect(panel.locator('.d-restore')).toBeVisible();
  await page.waitForTimeout(BEAT);
  // Restore it so the rest of the tour finds it back on the active list.
  await panel.locator('.d-restore').click();
  await expect(panel.locator('.d-archive')).toBeVisible();
  await page.waitForTimeout(BEAT);
  await panel.locator('#back-btn').click();
  await panel
    .locator('.hk-seg[data-seg="assetFilter"] button', { hasText: 'Active' })
    .click();
  await panel.locator(`.detail-open[data-detail-id="${ASSET.waterHeater}"]`).click();
  await expect(panel.locator('.d-archive')).toBeVisible();
  await page.waitForTimeout(BEAT);

  // 4a4. Stock that is measured, not counted — the descaling solution keeps its
  //      stock in millilitres and uses 250 of them per completion, so its chips
  //      read in real units instead of a bare count of somethings.
  await panel.locator('.hk-subtab[data-tab="parts"]').click();
  const measuredRow = panel
    .locator('.hk-part-row')
    .filter({ hasText: 'Descaling solution' });
  await measuredRow.scrollIntoViewIfNeeded();
  await expect(measuredRow.getByText('In stock: 750 ml')).toBeVisible();
  await page.waitForTimeout(BEAT * 2);

  // 4b. Auto-buy — open the editor, reveal the Parts section, and flip on
  //     "Auto-create buy task" for a stocked consumable so its Restock quantity
  //     appears: the low → buy → restocked loop, configured in a single toggle.
  await panel.locator('.d-edit').click();
  const assetForm = panel.locator('#hk-asset-form');
  await expect(assetForm).toBeVisible();
  const partsSection = assetForm
    .locator('details')
    .filter({ hasText: 'Parts & wear items' });
  if ((await partsSection.count()) > 0) {
    const open = await partsSection.first().evaluate((d: HTMLDetailsElement) => d.open);
    if (!open) await partsSection.first().locator('summary').click();
  }
  // The measured part's own editor first: a Stock unit and a Used-per-completion
  // amount sit beside the ordinary Stock and Reorder at.
  const measuredPart = partsSection.locator('.hk-part').nth(2);
  await measuredPart.scrollIntoViewIfNeeded();
  await expect(measuredPart.getByText('Stock unit', { exact: false })).toBeVisible();
  await page.waitForTimeout(BEAT * 2);
  const buyPart = partsSection.locator('.hk-part').last();
  await buyPart.scrollIntoViewIfNeeded();
  await page.waitForTimeout(BEAT);
  await buyPart.locator('ha-switch').first().click();
  await expect(buyPart.getByText('Restock quantity', { exact: false })).toBeVisible();
  await page.waitForTimeout(BEAT * 2);

  // 4c. Uploading a manual — the documents editor. Picking a file over the 100 MB
  //     ceiling is refused instantly, with the reason right under the button that
  //     was pressed (rather than in a banner far below the fold), then a real
  //     upload runs with a progress bar, percentage and byte counter.
  const docAdd = assetForm.locator('.hk-doc-add');
  await docAdd.scrollIntoViewIfNeeded();
  await page.waitForTimeout(BEAT);
  await docAdd.locator('input[type="file"]').evaluate((picker: HTMLInputElement) => {
    const file = new File([new Uint8Array(8)], 'water-heater-manual.pdf', {
      type: 'application/pdf',
    });
    Object.defineProperty(file, 'size', { value: 101 * 1024 * 1024 });
    const dt = new DataTransfer();
    dt.items.add(file);
    Object.defineProperty(picker, 'files', { value: dt.files, configurable: true });
    picker.dispatchEvent(new Event('change'));
  });
  await expect(docAdd.locator('ha-alert[alert-type="error"]')).toBeVisible();
  await page.waitForTimeout(BEAT * 2);

  // Throttle the upload so the bar's motion is actually visible in the recording.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', {
    offline: false,
    latency: 0,
    downloadThroughput: -1,
    uploadThroughput: 512 * 1024,
  });
  const chooser = page.waitForEvent('filechooser');
  await docAdd.locator('ha-button', { hasText: 'Upload file' }).click();
  await (await chooser).setFiles({
    name: 'water-heater-manual.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.concat([
      Buffer.from('%PDF-1.7\n'),
      Buffer.alloc(2 * 1024 * 1024, 0x30),
      Buffer.from('\n%%EOF\n'),
    ]),
  });
  await expect(assetForm.locator('.hk-upload-label')).toContainText('%', {
    timeout: 20_000,
  });
  await page.waitForTimeout(BEAT * 3);
  await cdp.send('Network.emulateNetworkConditions', {
    offline: false,
    latency: 0,
    downloadThroughput: -1,
    uploadThroughput: -1,
  });
  await expect(assetForm.locator('#hk-upload')).toHaveCount(0, { timeout: 30_000 });
  await page.waitForTimeout(BEAT);

  // Discard the unsaved toggle and return to the appliances list — a stable
  // top-level surface — for the next scene (``_closeAssetForm`` only re-renders,
  // so re-selecting the tab is the reliable way back to the list).
  await panel.locator('#a-cancel').click();
  await page.waitForTimeout(BEAT);
  await gotoTab(panel, 'appliances');
  await expect(panel.locator('#add-btn')).toBeVisible();
  await page.waitForTimeout(BEAT);

  // 5. Settings → Shopping list — where auto-buy reminders get mirrored onto an
  //    existing to-do list, so "go buy more" reaches a voice assistant.
  await gotoTab(panel, 'settings');
  await expect(panel.locator('#hk-settings-shopping ha-form')).toBeVisible();
  await page.waitForTimeout(BEAT);
  await panel.locator('#hk-settings-shopping').scrollIntoViewIfNeeded();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(BEAT * 2);

  // 6. Settings → Companions — integrations that work with Home Keeper. The card
  //    sits below the General / Shopping / Problem-sensor cards, so scroll it into
  //    view so the recording actually lands on it.
  await expect(panel.locator('#hk-companions')).toBeVisible();
  await page.waitForTimeout(BEAT);
  await panel.locator('#hk-companions').scrollIntoViewIfNeeded();
  await expect(panel.locator('.hk-comp-configure').first()).toBeVisible();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(BEAT * 2);

  // 6b. Settings → Profiles — a saved filter, and inside it the to-do list the
  //     household already checks. A sync *is* a profile: the same filter that
  //     chooses the chores also says where they go, so the tour opens the profile
  //     and then its **Sync to a to-do list** group.
  //
  //     The profile is seeded over the public service rather than added on camera:
  //     saving options reloads the config entry, which unregisters and re-registers
  //     the sidebar panel, and Home Assistant's frontend answers that by bouncing
  //     to the default dashboard. Seeding first keeps the tour on the panel; the
  //     *scene* is the row opening to show what the sync holds.
  await page.evaluate(async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    await hass.callService('home_keeper', 'set_options', {
      profiles: [
        {
          id: 'walkthrough_family_chores',
          // Named for the people, not the list: the row's own chip names the list
          // ("Family chores"), so reusing that here would read as one thing twice.
          name: 'Household chores',
          filter: { status: 'overdue', labels: [], areas: [], devices: [] },
          sync: {
            entity_id: 'todo.family_chores',
            two_way: true,
            vanish_as_completed: true,
          },
        },
      ],
    });
  });
  await openPanel(page);
  await gotoTab(panel, 'settings');
  const profilesCard = panel.locator('#hk-profiles');
  await expect(profilesCard).toBeVisible();
  await profilesCard.scrollIntoViewIfNeeded();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(BEAT * 2);
  // Rows start collapsed, so opening one is the beat: the filter that chooses the
  // chores, and below it the Sync group — already open, because a list is set —
  // naming the list and the two switches that cover the awkward providers.
  //
  //     Opening is guarded rather than a bare click: Home Assistant replaces the
  //     custom-panel element a few seconds after a page settles, and a fresh panel
  //     starts with every row folded, so an unguarded tour can record the group
  //     quietly closing itself.
  const syncedProfile = profilesCard.locator('.hk-item-card').first();
  const openSyncedProfile = async (): Promise<void> => {
    const header = syncedProfile.locator('> .hk-item-header');
    if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click();
    await expect(syncedProfile.locator('.hk-sync-group .hk-item-body ha-form')).toBeVisible();
  };
  await openSyncedProfile();
  await syncedProfile.scrollIntoViewIfNeeded();
  await page.waitForTimeout(BEAT * 2);
  // Then glide down to the group itself. The filter form above it is long enough
  // that framing the *row* leaves the sync below the fold, which is how an earlier
  // cut of this tour managed to visit the feature without ever showing it.
  await openSyncedProfile();
  await syncedProfile.locator('.hk-sync-group').scrollIntoViewIfNeeded();
  await page.waitForTimeout(BEAT * 3);

  // 7. Settings sections are addresses now. Walking the rail moves the URL and
  //    marks the section it lands on — the same route the phone tour opens as a
  //    page of its own.
  await openPanel(page);
  await gotoTab(panel, 'settings');
  await expect(panel.locator('.hk-settings-rail')).toBeVisible();
  await page.waitForTimeout(BEAT);
  for (const section of ['profiles', 'notifications', 'companions']) {
    await panel.locator(`.hk-rail-link[data-section="${section}"]`).click();
    await page.waitForTimeout(BEAT * 2);
  }

  // 8. The usage surfaces — the native to-do list and calendar, and beside them the
  //    family's own list, now carrying the synced chores with their due dates.
  await openDashboard(page);
  await page.waitForTimeout(BEAT * 2);
  const familyCard = page
    .locator('hui-todo-list-card, todo-list-card')
    .filter({ hasText: 'Family chores' })
    .first();
  await expect(
    familyCard.locator('ha-check-list-item, ha-md-list-item').first(),
  ).toBeVisible({ timeout: 40_000 });
  await expect(familyCard).toContainText('Family chores');
  // Framed on purpose rather than left to the masonry layout: the column order
  // reflows with the cards' heights, and the synced chores change those, so which
  // cards the closing shot happens to hold is otherwise luck. `scroll-margin-top`
  // does the framing, because a plain scroll-to-top tucks the card's own "Family
  // chores" heading under Home Assistant's sticky bar — and that heading is what
  // tells the viewer this is the household's list, not ours.
  await familyCard.evaluate((el) => {
    (el as HTMLElement).style.scrollMarginTop = '96px';
    el.scrollIntoView({ block: 'start', behavior: 'smooth' });
  });
  await page.waitForTimeout(BEAT * 4);
}

/**
 * The phone tour: deliberately different beats, not the desktop script at 390px.
 *
 * Every step here is something the wide tour structurally cannot show — the bottom
 * tab bar, the floating Add, the drawer arriving as a modal sheet, and Settings as
 * an index you drill into. Shorter than the desktop tour on purpose: it is a second
 * gif in the same PR comment, not a second full walkthrough.
 */
async function phoneTour(page: Page, panel: Locator): Promise<void> {
  // 1. Land on the task list. The tabs are along the bottom of the screen and Add
  //    floats above them.
  await openPanel(page);
  await expect(panel.locator('#hk-list')).toBeVisible();
  await expect(panel.locator('.hk-bottombar')).toBeVisible();
  await page.waitForTimeout(BEAT * 2);

  // 2. The scope pills wrap onto a second row rather than scrolling off the edge —
  //    a joined segment cannot wrap, so at this width it comes apart into chips.
  const overdue = panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="overdue"]');
  await overdue.click();
  await page.waitForTimeout(BEAT * 2);
  await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="all"]').click();
  await page.waitForTimeout(BEAT);

  // 3. Add opens the drawer as a sheet rising from the bottom, over a list that goes
  //    inert beneath it. Escape closes it and hands focus back to the button.
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-task-form')).toBeVisible();
  await page.waitForTimeout(BEAT * 3);
  await page.keyboard.press('Escape');
  await expect(panel.locator('#hk-task-form')).toHaveCount(0);
  await page.waitForTimeout(BEAT);

  // 4. A task detail is a page of its own, and Back returns to the list.
  await panel.locator(`.detail-open[data-detail-id="${TASK.fridgeFilter}"]`).click();
  await expect(panel.locator('#back-btn')).toBeVisible();
  await page.waitForTimeout(BEAT * 2);
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#hk-list')).toBeVisible();
  await page.waitForTimeout(BEAT);

  // 5. Appliances. There is no room for the 268px list beside a detail, so the list
  //    steps aside and the sub-tabs scroll to reach History.
  await gotoTab(panel, 'appliances');
  await expect(panel.locator('#hk-list')).toBeVisible();
  await page.waitForTimeout(BEAT * 2);
  await panel.locator(`.detail-open[data-detail-id="${ASSET.waterHeater}"]`).click();
  await expect(panel.locator('.hk-subtab').first()).toBeVisible();
  await page.waitForTimeout(BEAT * 2);
  await panel.locator('.hk-subtab[data-tab="history"]').click();
  await page.waitForTimeout(BEAT * 2);
  await panel.locator('#back-btn').click();
  await page.waitForTimeout(BEAT);

  // 6. Settings opens on an index of its sections — each naming what it is set to —
  //    and tapping one opens it alone, with a back arrow to the index.
  await openSettingsSection(panel, 'problem');
  await expect(panel.locator('#hk-settings')).toBeVisible();
  await page.waitForTimeout(BEAT * 3);
  await panel.locator('#settings-back').click();
  await expect(panel.locator('.hk-index-row').first()).toBeVisible();
  await page.waitForTimeout(BEAT * 2);
}

const TOURS: Tour[] = [
  // 800 rather than DESKTOP.height: the recording is the frame the gif is embedded
  // at, and a little more height reads better than the suite's 720.
  { name: 'desktop', size: { ...DESKTOP, height: 800 }, file: 'walkthrough.webm', run: desktopTour },
  { name: 'phone', size: PHONE, file: 'walkthrough-phone.webm', run: phoneTour },
];

for (const tour of TOURS) {
  test(`record Home Keeper panel walkthrough (${tour.name})`, async ({ browser }) => {
    await recordTour(browser, tour);
  });
}
