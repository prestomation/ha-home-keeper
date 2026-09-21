import { test, expect, Locator, Page } from '@playwright/test';
import {
  createTask,
  deleteTask,
  listTasks,
  openPanel,
  setTaskLayout,
  trackPanelErrors,
} from './helpers';
import { TASK } from '../fixture-ids';
import { DESKTOP, PHONE } from '../viewports';

/**
 * The Tasks tab's Layout menu, and the two compact layouts behind it.
 *
 * `task-layout.test.js` pins the decisions — which value a stored string means,
 * what a short due label reads, which rows an action sheet offers — against a
 * jsdom panel. None of that can say whether a tile grid really lays out three to a
 * row, whether a board column head follows Group by, or whether a press held for
 * half a second opens a page instead of a sheet. Those are the browser's answers,
 * so they are asked here.
 *
 * ## How these measure
 *
 * `getComputedStyle` through the panel's shadow root for the grid and the scroller,
 * the same way `responsive-layout.spec.ts` does, because a track count is what
 * "three to a row" means and a class name is not. Every list assertion checks the
 * list is non-empty first, or a renamed class would pass by measuring nothing.
 *
 * The layout is stored per user on the server, so it outlives a test. Every test
 * here leaves it on `rows` (see `afterEach`) — otherwise the next spec in the run
 * opens on tiles and fails on a `.hk-card-row` that no longer exists.
 */

/** Computed style of one shadow-DOM node, by property. */
async function styleOf(panel: Locator, selector: string, prop: string): Promise<string> {
  return panel.evaluate(
    (el, [sel, p]) => {
      const node = el.shadowRoot?.querySelector(sel);
      return node ? getComputedStyle(node).getPropertyValue(p) : 'MISSING';
    },
    [selector, prop],
  );
}

/**
 * How many columns the first laid-out `.hk-tiles` grid has.
 *
 * `grid-template-columns` computes to the resolved track sizes ("400px 400px
 * 400px"), so counting them is how the CSS answers "three to a row". Read from the
 * first grid that has a box: the Completed and Monitored groups render folded, and
 * a `display: none` grid computes its tracks as `none`.
 */
async function tileTracks(panel: Locator): Promise<number> {
  return panel.evaluate((el) => {
    const grids = [...(el.shadowRoot?.querySelectorAll('.hk-tiles') ?? [])];
    const laidOut = grids.find((g) => (g as HTMLElement).getBoundingClientRect().width > 0);
    if (!laidOut) return 0;
    return getComputedStyle(laidOut).gridTemplateColumns.trim().split(/\s+/).length;
  });
}

/**
 * The board's column headings, in the order they are drawn.
 *
 * Lower-cased, because a head is drawn `text-transform: uppercase` like a group
 * title and `allInnerTexts` reports what is rendered. The test is about which
 * groups the columns are, not about the letter case the stylesheet picks.
 */
async function columnHeads(panel: Locator): Promise<string[]> {
  const heads = await panel
    .locator('.hk-board-col .hk-board-head .hk-group-title')
    .allInnerTexts();
  return heads.map((h) => h.trim().toLowerCase());
}

/** Pick a value in one of the control row's menus. */
async function pick(panel: Locator, menu: string, value: string): Promise<void> {
  await panel.locator(`select[data-seg-select="${menu}"]`).selectOption(value);
}

/** Open the panel already in `layout`, the way a returning user arrives in it. */
async function openPanelIn(page: Page, layout: string): Promise<Locator> {
  await openPanel(page);
  await setTaskLayout(page, layout);
  await openPanel(page);
  return page.locator('home-keeper-panel').first();
}

test.describe('Home Keeper panel — task list layouts', () => {
  let created: string[] = [];

  test.beforeEach(() => {
    created = [];
  });

  test.afterEach(async ({ page }) => {
    // Back to rows, and through the store rather than the menu: a test that failed
    // half way may have left the panel somewhere the menu is not on screen, and a
    // layout left behind is the next spec's mystery failure.
    await page.setViewportSize(DESKTOP);
    await openPanel(page);
    await setTaskLayout(page, 'rows');
    for (const id of created) await deleteTask(id);
  });

  test('the Layout menu stands beside Group by on the Tasks tab', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const layout = panel.locator('select[data-seg-select="layout"]');
    const group = panel.locator('select[data-seg-select="group"]');
    await expect(layout).toBeVisible();

    // The three layouts, in the order the menu lists them.
    await expect(layout.locator('option')).toHaveText(['Rows', 'Tiles', 'Board']);
    await expect(layout).toHaveValue('rows');

    // Beside Group by, not under it: the two answer the same kind of question, and
    // the pairing is the reason the picker is on the tab rather than in Settings.
    const layoutBox = (await layout.boundingBox())!;
    const groupBox = (await group.boundingBox())!;
    expect(layoutBox.x, 'Layout should follow Group by').toBeGreaterThan(groupBox.x);
    expect(Math.abs(layoutBox.y - groupBox.y), 'the two menus share a row').toBeLessThanOrEqual(2);

    // Tasks only. The appliance list has one layout, so the menu goes away with it.
    await panel.locator('#tab-appliances').click();
    await expect(panel.locator('#hk-list')).toBeVisible();
    await expect(layout).toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test('Tiles lay out three to a row on a desktop and two on a phone', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    // Group by none, so the whole list is one grid: this test is about the grid, and
    // a status section that renders folded would have it measuring a hidden box.
    await pick(panel, 'group', 'none');
    await pick(panel, 'layout', 'tiles');

    await expect(panel.locator('.hk-tiles')).toBeVisible();
    const tiles = panel.locator('.hk-tiles .hk-tile');
    await expect(tiles.first()).toBeVisible();
    expect(await tiles.count(), 'no tiles drawn — has the class been renamed?')
      .toBeGreaterThan(3);
    // A tile is one press target, so it says so and names the task it is for.
    await expect(tiles.first()).toHaveAttribute('role', 'button');
    await expect(tiles.first()).toHaveAttribute('aria-label', /\S/);

    expect(await tileTracks(panel), 'a desktop fits three tiles to a row').toBe(3);

    // Below 700px the grid is a different grid, not a narrower one. Same page, so
    // this also proves the change is CSS rather than a re-render.
    await page.setViewportSize(PHONE);
    await expect(panel.locator('.hk-tiles')).toBeVisible();
    expect(await tileTracks(panel), 'a phone fits two').toBe(2);

    expect(errors).toEqual([]);
  });

  test('Board draws a column per group, and Group by decides which', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await pick(panel, 'group', 'status');
    await pick(panel, 'layout', 'board');

    await expect(panel.locator('.hk-board')).toBeVisible();
    const columns = panel.locator('.hk-board-col');
    await expect(columns.first()).toBeVisible();
    // The seed spans overdue, due soon, shopping, monitored and completed, so a
    // status board is several columns wide rather than one.
    expect(await columns.count(), 'a status board should be several columns wide')
      .toBeGreaterThanOrEqual(3);
    const statusHeads = await columnHeads(panel);
    expect(statusHeads.length).toBe(await columns.count());

    // Every column is open — a board is read across, and a folded column would
    // leave a heading with a gap under it.
    await expect(panel.locator('.hk-board-col .hk-bcard').first()).toBeVisible();

    // The columns follow Group by rather than being a second grouping of their own.
    await pick(panel, 'group', 'area');
    await expect(panel.locator('.hk-board-col[data-group-key^="area:"]').first()).toBeVisible();
    const areaHeads = await columnHeads(panel);
    expect(areaHeads, 'the heads should be rooms now, not statuses').not.toEqual(statusHeads);

    // Group by none is still a board: one column, headed the way the whole-list
    // scope pill is.
    await pick(panel, 'group', 'none');
    await expect(columns).toHaveCount(1);
    expect(await columnHeads(panel)).toEqual(['all']);

    expect(errors).toEqual([]);
  });

  test('the board scrolls sideways on a phone, a column at a time', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await page.setViewportSize(PHONE);
    const panel = await openPanelIn(page, 'board');
    await expect(panel.locator('.hk-board')).toBeVisible();
    await expect(panel.locator('.hk-board-col').first()).toBeVisible();

    // A phone has no room for columns side by side, so they go off the right edge —
    // which is only usable if the swipe is there and lands on a whole column.
    expect(await styleOf(panel, '.hk-board', 'overflow-x')).toBe('auto');
    expect(await styleOf(panel, '.hk-board', 'scroll-snap-type')).toContain('x');

    expect(errors).toEqual([]);
  });

  test('a press on a tile opens the actions that task allows', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await pick(panel, 'group', 'none');
    await pick(panel, 'layout', 'tiles');

    // The furnace filter is due months out, so due today has a date to bring nearer
    // and the sheet offers it. This is the same rule `skip-snooze.spec.ts` pins on
    // the detail page's caret — the sheet has to withhold what the caret withholds,
    // or a tile is a way around it.
    await panel.locator(`.hk-tile[data-id="${TASK.furnaceFilter}"]`).click();
    // The `ha-dialog` host portals its surface and has no box of its own, so the
    // rows are what a test can see — the host is only ever counted.
    const sheet = panel.locator('ha-dialog[open]');
    await expect(sheet).toHaveCount(1);
    await expect(sheet.locator('.hk-sheet-row[data-action="done"]')).toBeVisible();
    await expect(sheet.locator('.hk-sheet-row[data-action="dueToday"]')).toBeVisible();
    await expect(sheet.locator('.hk-sheet-row[data-action="open"]')).toBeVisible();

    // Escape closes it, and nothing happened to the task.
    await page.keyboard.press('Escape');
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0);

    // The water filter is already overdue, so there is no due date to pull forward.
    await panel.locator(`.hk-tile[data-id="${TASK.waterFilter}"]`).click();
    await expect(sheet).toHaveCount(1);
    await expect(sheet.locator('.hk-sheet-row[data-action="done"]')).toBeVisible();
    await expect(sheet.locator('.hk-sheet-row[data-action="dueToday"]')).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test('Done on the sheet completes the task', async ({ page }) => {
    const errors = trackPanelErrors(page);
    // Its own task, not a seeded one: this is the one test here that writes, and the
    // seed is the fixture every other spec and every screenshot reads.
    const id = await createTask({
      name: 'Wipe the tile layout bench',
      recurrence_type: 'floating',
      interval: 3,
      unit: 'months',
    });
    created.push(id);

    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await pick(panel, 'group', 'none');
    await pick(panel, 'layout', 'tiles');

    const tile = panel.locator(`.hk-tile[data-id="${id}"]`);
    await expect(tile).toBeVisible();
    await tile.click();
    await panel.locator('ha-dialog[open] .hk-sheet-row[data-action="done"]').click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0);

    // The store is the answer, not the tile: a completion that only redrew the card
    // is the failure this is looking for.
    await expect
      .poll(
        async () => Boolean((await listTasks()).find((x) => x.id === id)?.last_completed),
        { timeout: 20_000 },
      )
      .toBe(true);

    expect(errors).toEqual([]);
  });

  test('a press held on a tile opens the task rather than its sheet', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await pick(panel, 'group', 'none');
    await pick(panel, 'layout', 'tiles');

    const tile = panel.locator(`.hk-tile[data-id="${TASK.waterFilter}"]`);
    await expect(tile).toBeVisible();
    const box = (await tile.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    // Past the 500ms threshold, with room for a slow frame either side of it.
    await page.waitForTimeout(600);
    await page.mouse.up();

    // The page, not the sheet — and the click that ends the hold must not open one
    // on top of it.
    await expect(page).toHaveURL(new RegExp(`/home-keeper/tasks/${TASK.waterFilter}$`));
    await expect(panel.locator('#back-btn')).toBeVisible();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0);

    expect(errors).toEqual([]);
  });

  test('the layout belongs to the user, so it survives a reload', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await pick(panel, 'layout', 'tiles');
    // One grid per status section here, so take the first rather than the set.
    await expect(panel.locator('.hk-tiles').first()).toBeVisible();

    // Stored on the server against this user, so a reload reads it back rather than
    // starting over on rows — which is what a per-browser `localStorage` choice
    // would do for somebody arriving on their phone.
    await page.reload({ waitUntil: 'domcontentloaded' });
    const fresh = page.locator('home-keeper-panel').first();
    await expect(fresh.locator('.hk-tiles').first()).toBeVisible();
    await expect(fresh.locator('select[data-seg-select="layout"]')).toHaveValue('tiles');

    expect(errors).toEqual([]);
  });
});
