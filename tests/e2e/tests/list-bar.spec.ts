import { test, expect, Locator, Page } from '@playwright/test';
import { listStates, openListFilters, openPanel, trackPanelErrors } from './helpers';
import { PHONE } from '../viewports';

/**
 * The task list bar (#488): Search, Filters, the spend button and Add in 1 bar that
 * stays at the top while the list scrolls. A phone folds the filter controls behind
 * the Filters button, shows a chip for each active filter, and shows the spend totals
 * in a sheet. A desktop keeps the controls in view and shows the totals on 1 line.
 *
 * The measures are relations (A is inside B, A is above B), as in
 * `responsive-layout.spec.ts`.
 */

const panelOf = (page: Page): Locator => page.locator('home-keeper-panel').first();

/** A shadow-DOM node's box in viewport coordinates, or null. */
async function boxOf(panel: Locator, selector: string) {
  return panel.evaluate((el, sel) => {
    const node = el.shadowRoot?.querySelector(sel) as HTMLElement | null;
    if (!node) return null;
    const { x, y, width, height } = node.getBoundingClientRect();
    return { x, y, width, height, right: x + width, bottom: y + height };
  }, selector);
}

/** Put the stored list state back, so no spec leaks a fold or a scope into the next. */
async function resetListState(page: Page): Promise<void> {
  await page.evaluate(() => {
    localStorage.removeItem('home-keeper.controls');
    localStorage.setItem('home-keeper.filter', 'all');
    localStorage.setItem('home-keeper.profile', '');
  });
}

/** Scroll the list until the bar is pinned. */
async function scrollUntilPinned(page: Page, panel: Locator): Promise<void> {
  await expect(async () => {
    const card = await boxOf(panel, '#hk-list ha-card.hk-card');
    await page.mouse.move((card?.x ?? 100) + 20, (card?.y ?? 300) + 10);
    await page.mouse.wheel(0, 600);
    await expect(panel.locator('.hk-listbar[data-stuck]')).toHaveCount(1, { timeout: 1000 });
  }).toPass({ timeout: 15_000 });
}

/** The topmost element at a point, through every shadow root on the way down. */
async function deepTagsAt(page: Page, x: number, y: number): Promise<string[]> {
  return page.evaluate(
    ([px, py]) => {
      const tags: string[] = [];
      let root: Document | ShadowRoot = document;
      for (let i = 0; i < 30; i++) {
        const el = root.elementFromPoint(px, py) as HTMLElement | null;
        if (!el) break;
        tags.push(el.tagName.toLowerCase());
        if (!el.shadowRoot || el.shadowRoot === root) break;
        root = el.shadowRoot;
      }
      return tags;
    },
    [x, y],
  );
}

test.describe('Home Keeper panel — the task list bar on a phone', { tag: '@phone' }, () => {
  test.beforeEach(async ({ page }) => {
    await openPanel(page);
    await resetListState(page);
    await page.reload();
    await expect(panelOf(page).locator('.hk-listbar')).toBeVisible();
  });

  test.afterEach(async ({ page }) => {
    await resetListState(page);
  });

  test('the filters start folded, and the browser keeps the choice', async ({ page }) => {
    const panel = panelOf(page);
    const toggle = panel.locator('#hk-filters-btn');
    const controls = panel.locator('#hk-list-controls');
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(toggle).toHaveAttribute('aria-controls', 'hk-list-controls');
    await expect(controls).toBeHidden();
    // Search, Filters and the spend button share 1 row.
    const search = (await boxOf(panel, '.hk-listbar .hk-search'))!;
    const btn = (await boxOf(panel, '#hk-filters-btn'))!;
    expect(btn.y).toBeLessThan(search.bottom);
    expect(btn.bottom).toBeGreaterThan(search.y);

    await toggle.click();
    await expect(controls).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await page.reload();
    await expect(panel.locator('#hk-list-controls')).toBeVisible();
    await panel.locator('#hk-filters-btn').click();
    await expect(panel.locator('#hk-list-controls')).toBeHidden();
    await page.reload();
    await expect(panel.locator('#hk-list-controls')).toBeHidden();
  });

  test('a filter shows a count and a chip, and the chip clears it', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = panelOf(page);
    await openListFilters(panel);
    await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="overdue"]').click();
    await panel.locator('#hk-filters-btn').click();
    await expect(panel.locator('#hk-list-controls')).toBeHidden();

    const chip = panel.locator('.hk-filter-chip');
    await expect(chip).toHaveCount(1);
    await expect(chip).toContainText('Overdue');
    await expect(panel.locator('.hk-filters-badge')).toHaveText('1');
    await expect(panel.locator('#hk-filters-btn')).toHaveAccessibleName('Filters: 1 on');
    const clear = chip.locator('[data-clear-filter="scope"]');
    await expect(clear).toHaveAccessibleName('Clear filter: Overdue');
    // The clear button is a thumb-size target, whatever the circle draws.
    const hit = await clear.evaluate((el) => {
      const r = getComputedStyle(el, '::before');
      const b = el.getBoundingClientRect();
      return b.width - parseFloat(r.left) - parseFloat(r.right);
    });
    expect(hit).toBeGreaterThanOrEqual(44);

    await clear.click();
    await expect(panel.locator('.hk-filter-chip')).toHaveCount(0);
    await expect(panel.locator('.hk-filters-badge')).toHaveCount(0);
    await expect(panel.locator('#hk-filters-btn')).toBeFocused();
    expect(errors).toEqual([]);
  });

  test('the search text is a chip too, and Clear all clears both', async ({ page }) => {
    const panel = panelOf(page);
    await openListFilters(panel);
    await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="overdue"]').click();
    const box = panel.locator('.hk-search-input');
    await box.click();
    await box.pressSequentially('filter');
    await expect(box).toBeFocused();
    await expect(panel.locator('.hk-filter-chip')).toHaveCount(2);
    await expect(panel.locator('.hk-filters-badge')).toHaveText('2');
    await panel.locator('[data-clear-filter="all"]').click();
    await expect(panel.locator('.hk-filter-chip')).toHaveCount(0);
    await expect(box).toHaveValue('');
  });

  test('the bar stays at the top of the screen, and Filters goes back to the controls', async ({
    page,
  }) => {
    const panel = panelOf(page);
    await scrollUntilPinned(page, panel);
    const bar = (await boxOf(panel, '.hk-listbar'))!;
    // Pinned to the top edge: not above it, and no lower than its own height.
    expect(bar.y).toBeGreaterThanOrEqual(-1);
    expect(bar.y).toBeLessThan(bar.height);
    // It sits under the floating Add button and the tab bar, not over them.
    const order = await panel.evaluate((el) => {
      const z = (s: string) => Number(getComputedStyle(el.shadowRoot!.querySelector(s)!).zIndex);
      return { bar: z('.hk-listbar'), tabs: z('.hk-bottombar'), add: z('.hk-add-btn') };
    });
    expect(order.bar).toBeLessThan(order.tabs);
    expect(order.bar).toBeLessThan(order.add);

    await panel.locator('#hk-filters-btn').click();
    await expect(panel.locator('.hk-listbar[data-stuck]')).toHaveCount(0, { timeout: 10_000 });
    await expect(panel.locator('#hk-list-controls')).toBeVisible();
    await expect(panel.locator('#hk-list-controls .hk-seg-btn').first()).toBeInViewport();
  });

  test('the spend button opens a sheet, and Escape gives focus back', async ({ page }) => {
    const panel = panelOf(page);
    // The totals are behind the button on a phone, not above the list.
    await expect(panel.locator('#hk-list .hk-spend-compact')).toBeHidden();
    const btn = panel.locator('#hk-spend-btn');
    await expect(btn).toBeVisible();
    await expect(btn).toHaveAttribute('aria-haspopup', 'dialog');
    await expect(btn).toHaveAccessibleName(/^Maintenance spend, Last 30 days: /);

    await btn.click();
    const sheet = panel.locator('.hk-spend-sheet');
    await expect(sheet).toBeVisible();
    await expect(sheet).toHaveAttribute('role', 'dialog');
    await expect(sheet).toHaveAttribute('aria-modal', 'true');
    await expect(sheet.locator('.hk-spend-total')).not.toHaveCount(0);
    await expect(panel.locator('.hk-wrap')).toHaveAttribute('inert', '');
    await expect(panel.locator('.hk-bottombar')).toHaveAttribute('inert', '');
    expect(await sheet.evaluate((el) => el.contains(el.getRootNode().activeElement))).toBe(true);
    // The sheet ends at the bottom of the screen and stays inside it.
    const box = (await boxOf(panel, '.hk-spend-sheet'))!;
    expect(box.bottom).toBeLessThanOrEqual(PHONE.height + 1);
    expect(box.y).toBeGreaterThan(0);

    // A total opens its records inside the sheet.
    await sheet.locator('.hk-spend-total[data-spend]').first().click();
    await expect(panel.locator('.hk-spend-sheet .hk-spend-records')).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(panel.locator('.hk-spend-sheet')).toHaveCount(0);
    await expect(panel.locator('#hk-spend-btn')).toBeFocused();
    await expect(panel.locator('.hk-wrap')).not.toHaveAttribute('inert', '');

    // The scrim closes it too.
    await panel.locator('#hk-spend-btn').click();
    await panel.locator('.hk-spend-scrim').click({ position: { x: 20, y: 20 } });
    await expect(panel.locator('.hk-spend-sheet')).toHaveCount(0);
  });

  test('long search text and long names stay on the screen', async ({ page }) => {
    const panel = panelOf(page);
    await openListFilters(panel);
    await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="soon"]').click();
    await panel.locator('.hk-search-input').fill('a very long search text that no task name holds');
    await expect(panel.locator('.hk-filter-chip')).toHaveCount(2);
    for (const sel of ['.hk-listbar', '.hk-active-filters', '.hk-listbar-row']) {
      const over = await panel.evaluate((el, s) => {
        const n = el.shadowRoot!.querySelector(s) as HTMLElement;
        return n.scrollWidth - n.clientWidth;
      }, sel);
      expect(over, `${sel} overflows`).toBeLessThanOrEqual(0);
    }
    const chips = panel.locator('.hk-filter-chip');
    const row = (await boxOf(panel, '.hk-active-filters'))!;
    for (let i = 0; i < (await chips.count()); i++) {
      const c = (await chips.nth(i).boundingBox())!;
      expect(c.x + c.width).toBeLessThanOrEqual(row.right + 1);
    }
    expect(
      await page.evaluate(() => document.scrollingElement!.scrollWidth - innerWidth),
    ).toBeLessThanOrEqual(0);
  });

  test('a short screen, as with the keyboard open, keeps the pinned search usable', async ({
    page,
  }) => {
    const panel = panelOf(page);
    await scrollUntilPinned(page, panel);
    const box = panel.locator('.hk-search-input');
    await box.click();
    // The viewport an on-screen keyboard leaves on a phone.
    await page.setViewportSize({ width: PHONE.width, height: 380 });
    await box.pressSequentially('gutter');
    await expect(box).toBeFocused();
    await expect(box).toHaveValue('gutter');
    const bar = (await boxOf(panel, '.hk-listbar'))!;
    expect(bar.y).toBeGreaterThanOrEqual(-1);
    expect(bar.bottom).toBeLessThanOrEqual(380);
    await page.setViewportSize(PHONE);
  });

  test("Home Assistant's own dialogs open above the pinned bar", async ({ page }) => {
    const panel = panelOf(page);
    await scrollUntilPinned(page, panel);
    const states = await listStates();
    const entityId = states.find((s) => s.entity_id.startsWith('sensor.'))?.entity_id;
    expect(entityId).toBeTruthy();
    await page.evaluate((id) => {
      document.querySelector('home-assistant')!.dispatchEvent(
        new CustomEvent('hass-more-info', { detail: { entityId: id }, bubbles: true, composed: true }),
      );
    }, entityId);
    const bar = (await boxOf(panel, '.hk-listbar'))!;
    await expect
      .poll(async () => (await deepTagsAt(page, bar.x + bar.width / 2, bar.y + bar.height / 2)).join(' '), {
        timeout: 10_000,
      })
      .toMatch(/more-info/);
    await page.keyboard.press('Escape');
  });
});

test.describe('Home Keeper panel — the task list bar on a desktop', () => {
  test.beforeEach(async ({ page }) => {
    await openPanel(page);
    await resetListState(page);
    await page.reload();
    await expect(panelOf(page).locator('.hk-listbar')).toBeVisible();
  });

  test.afterEach(async ({ page }) => {
    await resetListState(page);
  });

  test('the controls stay in view, and the totals take 1 line', async ({ page }) => {
    const panel = panelOf(page);
    await expect(panel.locator('#hk-list-controls')).toBeVisible();
    await expect(panel.locator('#hk-filters-btn')).toBeHidden();
    await expect(panel.locator('#hk-spend-btn')).toBeHidden();
    await expect(panel.locator('.hk-active-filters')).toBeHidden();
    const strip = panel.locator('#hk-list .hk-spend-compact');
    await expect(strip).toBeVisible();
    const totals = strip.locator('.hk-spend-total');
    const n = await totals.count();
    expect(n).toBeGreaterThan(2);
    const tops = new Set<number>();
    for (let i = 0; i < n; i++) tops.add(Math.round((await totals.nth(i).boundingBox())!.y));
    expect([...tops]).toHaveLength(1);
  });

  test('the pinned bar adds Filters and the chips, and Filters goes back', async ({ page }) => {
    const panel = panelOf(page);
    await panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="overdue"]').click();
    await scrollUntilPinned(page, panel);
    await expect(panel.locator('#hk-filters-btn')).toBeVisible();
    await expect(panel.locator('.hk-filter-chip')).toContainText('Overdue');
    await expect(panel.locator('#hk-spend-btn')).toBeHidden();
    await panel.locator('#hk-filters-btn').click();
    await expect(panel.locator('.hk-listbar[data-stuck]')).toHaveCount(0, { timeout: 10_000 });
    await expect(panel.locator('#hk-list-controls .hk-seg-btn').first()).toBeInViewport();
    await expect(panel.locator('#hk-list-controls .hk-seg-btn').first()).toBeFocused();
  });
});
