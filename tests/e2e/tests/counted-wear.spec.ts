import { expect, test } from '@playwright/test';
import { ASSET, PART, TASK } from '../fixture-ids';
import { PHONE } from '../viewports';
import {
  callService,
  gotoTab,
  listTasks,
  openAppliance,
  openPanel,
  todoSummaries,
} from './helpers';

/**
 * Counted wear items (issue #306), from the household's side.
 *
 * The unit tier proves the arithmetic and the integration tier proves the Home
 * Assistant contracts. What only a browser shows is that the count actually reaches
 * the surfaces people read: a use task has no due date at all, so if the chip does
 * not render there is literally nothing on its row — a blank where the whole feature
 * should be, and no test below the browser would notice.
 *
 * These assert on the same surfaces the README screenshots capture. A captured
 * surface with nothing asserting on it is how #221 hid in plain sight for months.
 */

const TARGET = 25;

/** The seeded rain jacket's coating, read back over the public service API. */
async function readPart(): Promise<Record<string, any>> {
  const { assets } = await callService('home_keeper', 'list_assets', {}, true);
  const asset = assets.find((a: any) => a.id === ASSET.rainJacket);
  return asset.parts.find((p: any) => p.id === PART.dwrCoating);
}

/**
 * The live count, from the same 2 tasks the panel reads.
 *
 * Deliberately not the seeded 17. The container keeps its store, and the specs below
 * complete a use on purpose — so a constant here would make each test depend on which
 * ones ran before it, and on whether this container had ever run the suite. Reading it
 * is also the stronger assertion: what is pinned is that the panel agrees with the
 * store, not that a fixture holds a particular number.
 */
async function currentCount(): Promise<number> {
  const tasks = await listTasks();
  const useTask = tasks.find((t) => t.id === TASK.wearJacket);
  const replaceTask = tasks.find((t) => t.id === TASK.renewDwr);
  const since = replaceTask?.last_completed
    ? new Date(replaceTask.last_completed).getTime()
    : null;
  return (useTask?.completions ?? []).filter(
    (entry: { ts: string }) => since === null || new Date(entry.ts).getTime() > since,
  ).length;
}

test.describe('Home Keeper panel — counted wear items', () => {
  test('the use task has its own section and reads its count @responsive', async ({
    page,
  }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await gotoTab(panel, 'tasks');
    const row = panel.locator(`ha-card.hk-card[data-id="${TASK.wearJacket}"]`);
    await expect(row).toBeVisible();
    // The chip is the only thing on this row that says anything: no due date, no
    // overdue badge, nothing else to read.
    await expect(row).toContainText(`${await currentCount()} of ${TARGET} wears`);
  });

  test('the Counted pill scopes the list to use tasks @responsive', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await gotoTab(panel, 'tasks');
    await panel
      .locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="counted"]')
      .click();
    await expect(panel.locator(`ha-card.hk-card[data-id="${TASK.wearJacket}"]`)).toBeVisible();
    // The replacement half is dormant and belongs to Monitored, not here.
    await expect(panel.locator(`ha-card.hk-card[data-id="${TASK.renewDwr}"]`)).toHaveCount(0);
    // And an ordinary maintenance task is not swept in.
    await expect(panel.locator(`ha-card.hk-card[data-id="${TASK.anode}"]`)).toHaveCount(0);
  });

  test('the use task groups under Counted, not under No schedule @responsive', async ({
    page,
  }) => {
    // The regression this pins: `statusBucket` returns 'none' for any task with no
    // due date, above the line the Counted check was first written beside — so the
    // section rendered empty and the row fell into No schedule.
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await gotoTab(panel, 'tasks');
    await panel.locator('select[data-seg-select="group"]').selectOption('status');
    const counted = panel.locator('details.hk-group[data-bucket="counted"]');
    await expect(counted).toBeVisible();
    await expect(
      counted.locator(`ha-card.hk-card[data-id="${TASK.wearJacket}"]`),
    ).toBeVisible();
  });

  test('Done counts one use and the chip follows @responsive', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await gotoTab(panel, 'tasks');
    const before = await currentCount();
    const row = panel.locator(`ha-card.hk-card[data-id="${TASK.wearJacket}"]`);
    await expect(row).toContainText(`${before} of ${TARGET} wears`);
    await row.locator('.done-btn').first().click();
    await expect(row).toContainText(`${before + 1} of ${TARGET} wears`, {
      timeout: 15_000,
    });
    expect(await currentCount()).toBe(before + 1);
    // Still dateless: a use is not an end state, so nothing arms.
    const tasks = await listTasks();
    expect(tasks.find((t) => t.id === TASK.wearJacket)?.next_due).toBeNull();
  });

  test('a use draws down no stock and stamps no replacement @responsive', async () => {
    // The panel half of the store gate. Every use carries a part source, so without
    // it a wear would consume a spare and mark the treatment as done.
    const before = await readPart();
    await callService('home_keeper', 'complete_task', { task_id: TASK.wearJacket });
    const after = await readPart();
    expect(after.stock).toEqual(before.stock);
    expect(after.last_replaced).toEqual(before.last_replaced);
  });

  test('the use task is an undated item on the to-do list @responsive', async () => {
    const summaries = await todoSummaries();
    expect(summaries).toContain('Wear rain jacket');
  });

  test('the appliance part row shows the count and a meter @responsive', async ({
    page,
  }) => {
    await openPanel(page);
    const panel = await openAppliance(page, ASSET.rainJacket, 'parts');
    const meter = panel.locator('.hk-use-meter').first();
    await expect(meter).toBeVisible();
    // The bar is a progressbar with the real numbers on it, so a screen reader gets
    // the count rather than only a coloured strip.
    await expect(meter).toHaveAttribute('aria-valuemax', String(TARGET));
    expect(Number(await meter.getAttribute('aria-valuenow'))).toBe(await currentCount());
    await expect(panel.locator('.hk-part-cadence')).toContainText('wears');
  });

  test('the part editor reveals the counting fields @responsive', async ({ page }) => {
    // Deep-linked and waited on the panes, the way detail-edit.spec.ts opens this
    // same form. Going through the tab and clicking Edit raced the detail render: the
    // click landed while the pane was still settling and the drawer never opened.
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
    // itself, so an unconditional click *collapses* it and every field below goes
    // away — which is how this test failed at all 3 widths.
    const section = form
      .locator('details.hk-collapsible')
      .filter({ hasText: 'Parts & wear items' })
      .first();
    if ((await section.getAttribute('open')) === null) {
      await section.locator('summary').first().click();
    }
    await expect(section).toHaveAttribute('open', '');
    const part = form.locator('.hk-part').first();
    // Filtered to what is actually shown. An `ha-form` renders some labels twice —
    // once in a hidden slot — so an unfiltered `.first()` can pick a copy that is never
    // visible and the assertion then fails on a field that is plainly on screen.
    //
    // No `scrollIntoViewIfNeeded`: Playwright's "visible" means a non-empty box, not
    // "in the viewport", so an off-screen field already passes. Scrolling only added a
    // race, because the dependent form re-renders and detaches the matched element
    // between resolving it and acting on it.
    for (const label of ['Count uses as', 'Use task name']) {
      await expect(
        part.getByText(label, { exact: true }).filter({ visible: true }).first(),
        `the part editor should offer ${label}`,
      ).toBeVisible();
    }
    // The action picker and the backstop switch are **not** asserted here, and the
    // reveal is not driven from this test either. `ha-form` renders both inside shadow
    // roots whose `innerText` is empty and whose labels sit in nodes that never
    // measure, so every assertion on them either passes vacuously or fails on a
    // control that is plainly on screen.
    //
    // That logic is not untested; it is tested at the tier that can see it.
    // `forms-schema.test.js` and `counted-wear.test.js` pin the exact schema — which
    // fields a counted part reveals, which grids they sit in, which selectors they
    // use, the rebuild key that drives the reveal, and the clear-on-switch-back that
    // broke while this was being built. What this test adds is the one thing those
    // cannot: that the fields reach a real browser at all.
  });

  test('the count chip survives the phone layout', async ({ page }) => {
    // Below 700px the row stacks and the pills come apart into wrapping chips. The
    // count is the row's only content, so it is the thing that would be squeezed out.
    await page.setViewportSize(PHONE);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await gotoTab(panel, 'tasks');
    const row = panel.locator(`ha-card.hk-card[data-id="${TASK.wearJacket}"]`);
    await expect(row).toBeVisible();
    await expect(row).toContainText('of 25 wears');
    const chip = row.locator('ha-assist-chip.hk-counted').first();
    // Scrolled in first: the phone list runs past the fold, so "on screen" only means
    // something once the row is. What this pins is that the chip is not clipped out of
    // its row by the narrower layout, which is the phone-specific risk.
    await chip.scrollIntoViewIfNeeded();
    await expect(chip).toBeInViewport();
    const box = await chip.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThan(0);
  });
});
