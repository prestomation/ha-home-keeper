import { test, expect, Locator, Page } from '@playwright/test';
import { openAppliance, openPanel } from './helpers';
import { ASSET, TASK } from '../fixture-ids';

/**
 * The layout contracts the panel's media queries exist to keep.
 *
 * Every other spec asks what the panel *does*; these ask what it *looks like*, at the
 * widths where that changes. They are here because the redesign moved four
 * breakpoints' worth of chrome — the tab bar, the Add button, the filter segment, the
 * appliance master pane, the edit drawer — and nothing failed when any of it broke.
 * Two of the bugs this spec now pins were found by writing it.
 *
 * ## How these measure
 *
 * `getComputedStyle` for *keywords* (`position`, `flex-wrap`, `overflow-x`) and
 * bounding boxes for *relationships* (A is above B; this box is inside that one).
 * Never an absolute coordinate and never an exact size, so a spacing tweak does not
 * turn the suite red. The one literal number asserted is the 44px WCAG tap target,
 * and it is read from the panel's own `--hk-tap` token rather than written out.
 *
 * Every list assertion checks the list is non-empty first: a renamed class would
 * otherwise make the loop pass by iterating nothing.
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

/** The value of a design token on the panel host. */
async function token(panel: Locator, name: string): Promise<string> {
  return panel.evaluate((el, n) => getComputedStyle(el).getPropertyValue(n).trim(), name);
}

/** How far `el` overflows its own client box horizontally. <= 0 means it fits. */
async function horizontalOverflow(panel: Locator, selector: string): Promise<number> {
  return panel.evaluate((el, sel) => {
    const node = el.shadowRoot?.querySelector(sel) as HTMLElement | null;
    return node ? node.scrollWidth - node.clientWidth : Number.NaN;
  }, selector);
}

/** A shadow-DOM node's box in viewport coordinates. */
async function boxOf(panel: Locator, selector: string) {
  return panel.evaluate((el, sel) => {
    const node = el.shadowRoot?.querySelector(sel) as HTMLElement | null;
    if (!node) return null;
    const { x, y, width, height } = node.getBoundingClientRect();
    return { x, y, width, height, right: x + width, bottom: y + height };
  }, selector);
}

/** Scroll the page down and report how far it actually moved. */
async function scrollDown(page: Page, by = 2000): Promise<number> {
  return page.evaluate((amount) => {
    const el = document.scrollingElement || document.documentElement;
    const before = el.scrollTop;
    el.scrollTop = before + amount;
    return el.scrollTop - before;
  }, by);
}

const viewportOf = (page: Page) => page.viewportSize()!;

test.describe('Home Keeper panel — phone layout', { tag: '@phone' }, () => {
  test('the tabs move to a bar anchored to the screen, not the page', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('#hk-list')).toBeVisible();

    expect(await styleOf(panel, 'ha-tab-group', 'display')).toBe('none');
    await expect(panel.locator('.hk-bottombar')).toBeVisible();
    expect(await styleOf(panel, '.hk-bottombar', 'position')).toBe('fixed');

    const bar = (await boxOf(panel, '.hk-bottombar'))!;
    const { height: viewportHeight, width: viewportWidth } = viewportOf(page);
    expect(bar.bottom).toBeGreaterThan(viewportHeight - 2);
    expect(bar.width).toBeGreaterThan(viewportWidth - 2);

    // Anchored to the viewport, not sitting at the bottom of a long document. The
    // static read alone would still pass under the `container-type: :host`
    // regression the rules warn about — which turns every fixed descendant into a
    // page-positioned one — so scroll and re-read.
    const moved = await scrollDown(page);
    expect(moved, 'the page needs to actually scroll for this to prove anything')
      .toBeGreaterThan(0);
    const afterScroll = (await boxOf(panel, '.hk-bottombar'))!;
    expect(Math.abs(afterScroll.y - bar.y)).toBeLessThanOrEqual(1);
  });

  test('Add floats clear of the bar and stays put while the list scrolls', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('#hk-list')).toBeVisible();

    expect(await styleOf(panel, '.hk-add-btn', 'position')).toBe('fixed');
    const add = (await boxOf(panel, '#add-btn'))!;
    const bar = (await boxOf(panel, '.hk-bottombar'))!;
    const { width: viewportWidth } = viewportOf(page);

    // Above the bar rather than behind it, and fully on screen.
    expect(add.bottom).toBeLessThanOrEqual(bar.y + 1);
    expect(add.right).toBeLessThanOrEqual(viewportWidth);
    expect(add.x).toBeGreaterThanOrEqual(0);

    const moved = await scrollDown(page);
    expect(moved).toBeGreaterThan(0);
    const afterScroll = (await boxOf(panel, '#add-btn'))!;
    expect(Math.abs(afterScroll.y - add.y)).toBeLessThanOrEqual(1);
  });

  test('the filter segment comes apart into chips, and none is off the edge', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('.hk-seg-btn').first()).toBeVisible();

    // A joined segment cannot wrap — it is one pill with hairlines between its
    // buttons — so at this width it stops being one.
    expect(await styleOf(panel, '.hk-seg', 'flex-wrap')).toBe('wrap');
    expect(await styleOf(panel, '.hk-seg', 'border-top-width')).toBe('0px');
    expect(await styleOf(panel, '.hk-seg-btn', 'border-radius')).not.toBe('0px');

    // Nothing scrolls sideways: a control parked off the edge of a phone screen is
    // a control nobody finds, and there is no affordance saying to swipe for it.
    for (const selector of ['.hk-controls', '.hk-wrap']) {
      expect(await horizontalOverflow(panel, selector), `${selector} overflows`)
        .toBeLessThanOrEqual(0);
    }
    expect(
      await page.evaluate(() => {
        const el = document.scrollingElement || document.documentElement;
        return el.scrollWidth - el.clientWidth;
      }),
    ).toBeLessThanOrEqual(0);

    // And every chip really is inside the row that holds them.
    const controls = (await boxOf(panel, '.hk-controls'))!;
    const chips = panel.locator('.hk-seg-btn');
    const count = await chips.count();
    expect(count, 'no filter chips found — has the class been renamed?').toBeGreaterThan(2);
    for (let i = 0; i < count; i++) {
      const chip = (await chips.nth(i).boundingBox())!;
      expect(chip.x + chip.width, `chip ${i} runs past the controls row`)
        .toBeLessThanOrEqual(controls.right + 1);
    }
  });

  test('the controls a thumb reaches for meet the tap target the panel defines', async ({
    page,
  }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('.hk-seg-btn').first()).toBeVisible();

    // Read the floor off the panel's own token rather than writing 44 here twice.
    const tap = Number.parseFloat(await token(panel, '--hk-tap'));
    expect(tap).toBeGreaterThan(0);

    for (const selector of ['.hk-seg-btn', '.hk-menu']) {
      const targets = panel.locator(selector);
      const count = await targets.count();
      expect(count, `no ${selector} found`).toBeGreaterThan(0);
      for (let i = 0; i < count; i++) {
        const box = (await targets.nth(i).boundingBox())!;
        // Sub-pixel layout, so allow half a pixel rather than demanding >= exactly.
        expect(box.height, `${selector}[${i}] is under the tap target`)
          .toBeGreaterThanOrEqual(tap - 0.5);
      }
    }
    // The ha-button host is what a thumb hits, not the button inside its shadow root.
    const add = (await panel.locator('#add-btn').boundingBox())!;
    expect(add.height).toBeGreaterThanOrEqual(tap - 0.5);
  });

  test('a task row stacks without leaving an empty line in it', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const row = panel.locator(`ha-card.hk-card[data-id="${TASK.doorBattery}"] .hk-card-row`);
    await expect(row).toBeVisible();

    const parts = await row.evaluate((el) =>
      [...el.children].map((child) => {
        const { y, height, x } = child.getBoundingClientRect();
        return {
          cls: child.className,
          display: getComputedStyle(child).display,
          y,
          x,
          bottom: y + height,
        };
      }),
    );
    const find = (cls: string) => parts.find((p) => p.cls.includes(cls))!;
    const name = find('grow');
    const chips = find('hk-chips-inline');
    const status = find('hk-status');
    const actions = find('hk-card-actions');
    expect([name, chips, status, actions].every(Boolean)).toBe(true);

    // Title, then the chips, then the status pill beside the button it argues for.
    expect(name.bottom).toBeLessThanOrEqual(chips.y + 1);
    expect(chips.bottom).toBeLessThanOrEqual(status.y + 1);
    expect(Math.abs(actions.y - status.y)).toBeLessThan(20);
    expect(actions.x).toBeGreaterThan(status.x);

    // The spacer only pushes Done rightwards on a single-line row. Left visible on a
    // wrapped one it could not share a line with a full-width sibling, so it took an
    // empty line of its own and cost the row a phantom 10px gap.
    expect(find('hk-row-spacer').display).toBe('none');
  });
});

test.describe('Home Keeper panel — tablet layout', { tag: '@tablet' }, () => {
  test('keeps the top tabs and the inline Add button', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('#hk-list')).toBeVisible();

    // The phone chrome arrives at 700px, well below this. Asserting it here is what
    // keeps the 700px rules from leaking upward into the band that only wanted the
    // drawer and the master pane to change.
    await expect(panel.locator('ha-tab-group')).toBeVisible();
    expect(await styleOf(panel, '.hk-bottombar', 'display')).toBe('none');
    expect(await styleOf(panel, '.hk-add-btn', 'position')).not.toBe('fixed');
    expect(await horizontalOverflow(panel, '.hk-wrap')).toBeLessThanOrEqual(0);
  });

  test('the panel gets the whole window, not the window minus a sidebar', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('#hk-list')).toBeVisible();

    // Worth stating rather than assuming. The breakpoints are reasoned about as
    // "the viewport minus Home Assistant's ~256px sidebar", which is why the sheet
    // threshold is 1150 rather than 900 — but by this width HA has gone narrow and
    // collapsed that sidebar, so the panel has the lot. If HA moves its own
    // breakpoint, this fails and says so instead of quietly changing what the
    // tablet project is testing.
    const shell = (await boxOf(panel, '.hk-shell'))!;
    expect(shell.width).toBeGreaterThan(viewportOf(page).width - 40);
  });

  test('an appliance takes the column, and its sub-tabs stay reachable', async ({ page }) => {
    await openPanel(page);
    const panel = await openAppliance(page, ASSET.waterHeater, 'parts');
    await expect(panel.locator('.hk-subtab').first()).toBeVisible();

    // No room for a 268px list beside a detail, so the list steps aside and the
    // back button in the bar becomes the only way out of it.
    expect(await styleOf(panel, '.hk-master', 'display')).toBe('none');
    expect(await styleOf(panel, '.hk-master-controls', 'display')).toBe('none');
    await expect(panel.locator('#back-btn')).toBeVisible();

    // Sub-tabs scroll rather than clipping Related and History off the edge with no
    // cue. Assert *reachability*, not that they overflow — whether they do depends
    // on the locale's label lengths.
    expect(await styleOf(panel, '.hk-subtabs', 'overflow-x')).toBe('auto');
    expect(await styleOf(panel, '.hk-subtabs', 'flex-wrap')).toBe('nowrap');
    await panel.evaluate((el) => {
      const tabs = el.shadowRoot?.querySelector('.hk-subtabs') as HTMLElement | null;
      if (tabs) tabs.scrollLeft = tabs.scrollWidth;
    });
    const tabs = (await boxOf(panel, '.hk-subtabs'))!;
    const last = (await panel.locator('.hk-subtab').last().boundingBox())!;
    expect(last.x).toBeGreaterThanOrEqual(tabs.x - 1);
    expect(last.x + last.width).toBeLessThanOrEqual(tabs.right + 1);
  });
});

test.describe('Home Keeper panel — the edit drawer as a sheet', { tag: '@narrow' }, () => {
  test('rises from the bottom of the screen and scrolls inside itself', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#add-btn').click();
    await expect(panel.locator('#hk-task-form')).toBeVisible();

    // Geometry only — `a11y.spec.ts` owns the modality contract (inert, role,
    // focus, Escape), and restating it here would mean two places to update.
    expect(await styleOf(panel, '.hk-drawer[data-open]', 'position')).toBe('fixed');

    const sheet = (await boxOf(panel, '.hk-drawer[data-open]'))!;
    const { width: viewportWidth, height: viewportHeight } = viewportOf(page);
    // Full-bleed and anchored to the bottom edge…
    expect(sheet.x).toBeLessThanOrEqual(1);
    expect(sheet.width).toBeGreaterThanOrEqual(viewportWidth - 1);
    expect(Math.abs(sheet.bottom - viewportHeight)).toBeLessThanOrEqual(2);
    // …but never the whole screen: a strip of the list stays visible above it, which
    // is what says this is a sheet over a page rather than a new page. Asserted on
    // the top edge rather than the height, because the `max-height: 92dvh` caps the
    // drawer's *content* box and the padding and border sit outside it.
    expect(sheet.y).toBeGreaterThanOrEqual(viewportHeight * 0.05);

    // The sheet is already fixed to the viewport, so its inner column scrolls
    // within it rather than sticking to anything.
    expect(await styleOf(panel, '.hk-drawer[data-open] .hk-drawer-sticky', 'position')).toBe(
      'static',
    );
  });
});
