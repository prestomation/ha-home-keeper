/**
 * Screenshot capture for fixed schedules as RRULEs (#391) and moving one date (#390).
 * Not part of the e2e suite (the filename is not *.spec.ts). Run from tests/e2e:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-fixed-schedule.config.ts
 *
 * Creates a "Take trash out" task on Tuesdays and Fridays, moves its third date one
 * day later, and photographs, at desktop and phone width:
 *  71.  The task form: Frequency weekly, Tue and Fri pressed, the next dates below.
 *  72.  The same form with a custom rule typed in: the day buttons greyed out and
 *       Reset to simple beside them.
 *  73.  The task page's Upcoming block, with the moved date marked.
 *  74.  The snooze dialog on "A later date", a date picked.
 *  card-snooze-later-date. The same dialog opened from the dashboard card.
 *
 * The task is deleted at the end, so the fixture is untouched for any later capture.
 */
import { test, expect, type Locator, type Page } from '@playwright/test';
import { centre, shotWithDrawer } from './shots';
import { callService, createTask, deleteTask, openCardDashboard, openPanel } from './tests/helpers';
import { DESKTOP, PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

/**
 * 07:00 on the next Tuesday that is at least 2 days out, plus *days*. The time has no
 * offset, so Home Assistant reads it in its own zone and the shots show 7:00 AM.
 */
function nextTuesday(days = 0): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + 2);
  while (d.getUTCDay() !== 2) d.setUTCDate(d.getUTCDate() + 1);
  d.setUTCDate(d.getUTCDate() + days);
  return `${d.toISOString().slice(0, 10)}T07:00:00`;
}

/** Clip a dialog to its own surface, as the card capture does. */
async function shotDialog(page: Page, dialog: Locator, path: string): Promise<void> {
  const PAD = 22;
  const box = await dialog.evaluate((el) => {
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    for (const child of Array.from(el.children)) {
      const r = child.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      x0 = Math.min(x0, r.x);
      y0 = Math.min(y0, r.y);
      x1 = Math.max(x1, r.x + r.width);
      y1 = Math.max(y1, r.y + r.height);
    }
    return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
  });
  const view = page.viewportSize() ?? { width: box.width, height: box.height };
  const x = Math.max(0, box.x - PAD);
  const y = Math.max(0, box.y - PAD);
  await page.screenshot({
    path,
    clip: {
      x,
      y,
      width: Math.min(view.width - x, box.width + PAD * 2),
      height: Math.min(view.height - y, box.height + PAD * 2),
    },
  });
}

async function openTask(page: Page, id: string): Promise<Locator> {
  await page.goto(`/home-keeper/tasks/${id}`, { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  await expect(panel.locator('#hk-upcoming .hk-up-row')).toHaveCount(6, { timeout: 15_000 });
  return panel;
}

/** 71 and 72: the form with the day buttons, then with a custom rule. */
async function formShots(page: Page, id: string, suffix: string): Promise<void> {
  const panel = await openTask(page, id);
  await panel.locator('.d-edit').click();
  const days = panel.locator('#hk-rule-days');
  await expect(days.locator('.hk-day-btn[aria-pressed="true"]')).toHaveCount(2);
  await expect(panel.locator('#hk-form-next')).toContainText('Fri', { timeout: 10_000 });
  await centre(days);
  await page.waitForTimeout(500);
  await shotWithDrawer(page, `${OUT}/71${suffix}-fixed-weekdays.png`);

  const ruleForm = panel.locator('#hk-task-form-rule');
  await ruleForm.locator('ha-expansion-panel').click();
  const box = ruleForm.locator('ha-selector-text input');
  await box.fill('FREQ=MONTHLY;BYDAY=1TU');
  await expect(days.locator('.hk-day-btn').first()).toBeDisabled();
  await expect(panel.locator('#hk-rule-reset')).toBeVisible();
  await expect(panel.locator('#hk-form-next')).toContainText('Tue', { timeout: 10_000 });
  await box.blur();
  await centre(days);
  await page.waitForTimeout(500);
  await shotWithDrawer(page, `${OUT}/72${suffix}-fixed-custom-rule.png`);
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });
}

/** 73 and 74: the Upcoming block, then Move on its fourth date. */
async function upcomingShots(page: Page, id: string, suffix: string): Promise<void> {
  const panel = await openTask(page, id);
  const upcoming = panel.locator('#hk-upcoming');
  await expect(upcoming.locator('.hk-moved-badge')).toHaveCount(1);
  await centre(upcoming);
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/73${suffix}-upcoming-moved.png` });

  await upcoming.locator('.hk-up-move').nth(3).click();
  const dialog = panel.locator('ha-dialog[open]');
  await expect(dialog.locator('.hk-later-row.picked')).toHaveCount(1);
  await expect(dialog.locator('.hk-move-hint')).toContainText('moves to');
  await page.waitForTimeout(500);
  await shotDialog(page, dialog, `${OUT}/74${suffix}-snooze-later-date.png`);
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });
}

/** The card's snooze dialog, switched to "A later date" with a date picked. */
async function cardShot(page: Page, id: string, path: string): Promise<void> {
  const card = await openCardDashboard(page);
  const snooze = card.locator(`.hk-defer-snooze[data-id="${id}"]`);
  await snooze.scrollIntoViewIfNeeded();
  await snooze.click();
  const dialog = page.locator('ha-dialog[open]').first();
  await dialog.locator('#hk-snooze-mode-later').click();
  await expect(dialog.locator('.hk-later-row')).toHaveCount(6, { timeout: 15_000 });
  await dialog.locator('.hk-later-row').nth(1).click();
  await expect(dialog.locator('.hk-later-row.picked')).toHaveCount(1);
  await page.waitForTimeout(500);
  await shotDialog(page, dialog, path);
  await dialog.getByRole('button', { name: 'Cancel' }).click();
}

test('capture fixed schedules and moving one date', async ({ page }) => {
  test.setTimeout(240_000);
  await openPanel(page);
  const id = await createTask({
    name: 'Take trash out',
    notes: 'Bins to the curb before 07:00.',
    rrule: 'FREQ=WEEKLY;BYDAY=TU,FR',
    anchor: nextTuesday(),
  });
  try {
    // Move the third date (the second Tuesday) a day later, as the city might.
    await callService('home_keeper', 'move_occurrence', {
      task_id: id,
      occurrence: nextTuesday(7),
      to: nextTuesday(8),
    });

    await page.setViewportSize(DESKTOP);
    await formShots(page, id, '-panel');
    await upcomingShots(page, id, '-panel');
    await page.setViewportSize({ width: 1280, height: 2400 });
    await cardShot(page, id, `${OUT}/card-snooze-later-date.png`);

    await page.setViewportSize(PHONE);
    await formShots(page, id, 'c-panel-mobile');
    await upcomingShots(page, id, 'c-panel-mobile');
    await cardShot(page, id, `${OUT}/card-snooze-later-date-mobile.png`);
  } finally {
    await page.setViewportSize(DESKTOP);
    await deleteTask(id);
  }
});
