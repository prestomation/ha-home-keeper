/**
 * One-off screenshot capture for times shown in Home Assistant's zone (X04-7) — not
 * part of the e2e suite (the filename is not *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-timezone.config.ts
 *
 * The config puts the browser on Asia/Tokyo, 13 hours ahead of the container's
 * America/New_York. The panel must still show the New York wall clock: the edit form
 * shows the anchor as 09:30, and the history shows the completions at their New York
 * times and dates. `tests/e2e/tests/timezone.spec.ts` asserts the same values.
 */
import { expect, Page, test } from '@playwright/test';
import { callService, createTask, deleteTask, openPanel, openTaskTab } from './tests/helpers';
import { shotWithDrawer } from './shots';
import { PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/hk-shots';

// 09:30 in New York is 23:30 the same day in Tokyo.
const ANCHOR = '2026-11-02T09:30:00-05:00';
// Each of these is a day earlier in New York than in Tokyo. The newest goes first:
// it moves the schedule one occurrence on, and the older 2 only fill in the log.
const DONE = ['2026-09-02T22:10:00-04:00', '2026-08-02T21:30:00-04:00', '2026-07-02T20:45:00-04:00'];

let taskId: string | undefined;

test.beforeAll(async () => {
  taskId = await createTask({
    name: 'Clean range hood filter',
    recurrence_type: 'fixed',
    freq: 'MONTHLY',
    interval: 1,
    anchor: ANCHOR,
  });
  for (const at of DONE) {
    await callService('home_keeper', 'complete_task', { task_id: taskId, completed_at: at });
  }
});

test.afterAll(async () => {
  await deleteTask(taskId);
});

async function openHistory(page: Page): Promise<void> {
  const panel = page.locator('home-keeper-panel').first();
  await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
  await expect(panel.locator('.hk-detail-actions').first()).toBeVisible({ timeout: 30_000 });
  await openTaskTab(panel, 'history');
  // 22:10 on Sep 2 in New York. In the browser zone it would be Sep 3.
  await expect(panel.locator('.hk-hist-list li').first()).toContainText('Sep 2, 2026');
  await page.waitForTimeout(500);
}

async function openForm(page: Page): Promise<void> {
  const panel = page.locator('home-keeper-panel').first();
  await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
  await expect(panel.locator('.hk-detail-actions').first()).toBeVisible({ timeout: 30_000 });
  await panel.locator('.d-edit').click();
  const anchor = panel.locator('#hk-task-form ha-selector-datetime').first();
  await expect(anchor).toBeVisible();
  await expect
    .poll(() => anchor.evaluate((el: Element & { value?: string }) => el.value))
    .toBe('2026-11-02 09:30:00');
  await anchor.evaluate((node: Element) => node.scrollIntoView({ block: 'center' }));
  // On a phone the date-time row is wider than the sheet, so the scroll above also
  // moves the sheet sideways. Put it back, to show what a person sees.
  await panel.evaluate((el: Element) => {
    const walk = (root: ParentNode): void => {
      for (const node of root.querySelectorAll('*')) {
        if ((node as HTMLElement).scrollLeft) (node as HTMLElement).scrollLeft = 0;
        const sr = (node as HTMLElement).shadowRoot;
        if (sr) walk(sr);
      }
    };
    walk(el.shadowRoot ?? el);
  });
  await page.waitForTimeout(600);
}

test('capture times in the Home Assistant zone', async ({ page }) => {
  await openPanel(page);

  await openHistory(page);
  await page.screenshot({ path: `${OUT}/75-panel-timezone-task-history.png`, fullPage: true });

  await openForm(page);
  await shotWithDrawer(page, `${OUT}/74-panel-timezone-task-form.png`);

  await page.setViewportSize(PHONE);

  await openHistory(page);
  await page.screenshot({ path: `${OUT}/75c-panel-mobile-zone-completions.png`, fullPage: true });

  await openForm(page);
  await page.screenshot({ path: `${OUT}/74c-panel-mobile-timezone-task-form.png` });
});
