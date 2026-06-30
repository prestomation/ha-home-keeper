/**
 * One-off **video** walkthrough capture for PR / README documentation — not part
 * of the e2e suite (filename does not match *.spec.ts). It records a narrated
 * end-to-end tour of the Home Keeper panel as a WebM, which ci/capture-video.sh
 * then transcodes to mp4 (+ a GIF fallback) under docs/videos/.
 *
 * Run it through the wrapper (recommended — it does the ffmpeg transcode too):
 *   bash ci/capture-video.sh
 *
 * Or directly (raw WebM only), from tests/e2e/:
 *   VIDEO_DIR=../../docs/videos npx playwright test \
 *     --config=walkthrough.config.ts
 *
 * Unlike the screenshot captures, video needs the recording wired at the browser
 * *context* level (`recordVideo`), and the file is only flushed when the context
 * closes — so this spec builds its own authenticated context (reusing the auth
 * state global-setup wrote) rather than the default `page` fixture, then saves the
 * video to a stable name we can transcode.
 */
import { test, expect } from '@playwright/test';
import { resolve } from 'path';
import { openPanel, openDashboard } from './tests/helpers';

const OUT = process.env.VIDEO_DIR || '/tmp/home-keeper-video';
const STATE_PATH = resolve(__dirname, '.auth/state.json');
const SIZE = { width: 1280, height: 800 };

/** A readable pause so motion in the recording is easy to follow. */
const BEAT = 900;

test('record Home Keeper panel walkthrough', async ({ browser }) => {
  // Build an authenticated context that records video. The recording is flushed to
  // disk only on context.close(), after which page.video().saveAs() names it.
  const context = await browser.newContext({
    storageState: STATE_PATH,
    viewport: SIZE,
    recordVideo: { dir: OUT, size: SIZE },
  });
  const page = await context.newPage();

  try {
    // 1. Land on the admin panel — the task list with overdue / due-soon tasks and
    //    the first-run orientation banner.
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('.hk-intro')).toBeVisible();
    await page.waitForTimeout(BEAT * 2);
    await panel.locator('ha-button.hk-intro-dismiss').click();
    await expect(panel.locator('.hk-intro')).toHaveCount(0);
    // Let the list re-render/settle after the banner collapses before clicking into it.
    await expect(panel.locator('#add-btn')).toBeVisible();
    await page.waitForTimeout(BEAT);

    // 2. Open a task's detail page — full schedule, notes, and completion history.
    const taskRow = panel.locator('.detail-open[data-detail-id="task_fridge_filter"]');
    await expect(taskRow).toBeVisible();
    await taskRow.click();
    await expect(panel.locator('.hk-hist-list li').first()).toBeVisible();
    await page.waitForTimeout(BEAT * 2);
    await panel.locator('#back-btn').click();
    await expect(panel.locator('#add-btn')).toBeVisible();
    await page.waitForTimeout(BEAT);

    // 3. Create a task — show the form and the recurrence picker switching modes.
    await panel.locator('#add-btn').click();
    await expect(panel.locator('#hk-form')).toBeVisible();
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
    // Reset by re-opening the panel fresh — closing the create form does a full
    // route change back to /home-keeper that can race a click (the screenshots
    // harness resets the create form the same way).
    await openPanel(page);
    await expect(panel.locator('#add-btn')).toBeVisible();
    await page.waitForTimeout(BEAT);

    // 4. Appliances — the asset list, then an appliance's detail page (parts,
    //    metadata, related tasks and maintenance history).
    await panel.locator('#tab-appliances').click();
    await expect(panel.locator('.hk-name').first()).toBeVisible();
    await page.waitForTimeout(BEAT);
    const applianceRow = panel.locator('.detail-open[data-detail-id="asset_water_heater"]');
    await expect(applianceRow).toBeVisible();
    await applianceRow.click();
    await expect(panel.locator('.hk-hist-group').first()).toBeVisible();
    await page.waitForTimeout(BEAT * 2);
    await panel.locator('#back-btn').click();
    await expect(panel.locator('#add-btn')).toBeVisible();
    await page.waitForTimeout(BEAT);

    // 5. Settings → Companions — integrations that work with Home Keeper. The card
    //    sits below the General / Problem-sensor cards, so scroll it into view so the
    //    recording actually lands on it.
    await panel.locator('#tab-settings').click();
    await expect(panel.locator('#hk-companions')).toBeVisible();
    await page.waitForTimeout(BEAT);
    await panel.locator('#hk-companions').scrollIntoViewIfNeeded();
    await expect(panel.locator('.hk-comp-configure').first()).toBeVisible();
    await page.mouse.move(0, 0);
    await page.waitForTimeout(BEAT * 2);

    // 6. The usage surfaces — native to-do list + calendar on a dashboard.
    await openDashboard(page);
    await page.waitForTimeout(BEAT * 3);
  } finally {
    // Close the context to flush the recording, then save it to a stable filename.
    await context.close();
    const video = page.video();
    if (video) await video.saveAs(resolve(OUT, 'walkthrough.webm'));
  }
});
