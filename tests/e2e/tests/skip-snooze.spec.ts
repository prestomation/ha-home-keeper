import { test, expect } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';
import { TASK } from '../fixture-ids';

/** Deep-link straight to a panel destination and wait for the element to attach. */
async function gotoPanel(page: import('@playwright/test').Page, path: string) {
  await page.goto(`/home-keeper${path}`, { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  return panel;
}

/**
 * Snooze and skip, reached from the panel (issue #268).
 *
 * Both verbs shipped as services and notification buttons long before this, but
 * neither had a websocket command, so the panel — which only talks `callWS` — could
 * not offer them at all. These drive the real chrome: the caret beside Done, the
 * snooze dialog's preset picker, and the skip appearing in history without being
 * counted as a completion.
 */
test.describe('Home Keeper panel — snooze and skip', { tag: '@responsive' }, () => {
  test('the caret beside Done opens a menu naming both verbs', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await gotoPanel(page, `/tasks/${TASK.waterFilter}`);

    const caret = panel.locator('.hk-detail-actions .hk-split-caret');
    await expect(caret).toBeVisible();
    await expect(caret).toHaveAttribute('aria-expanded', 'false');

    await caret.click();
    const menu = panel.locator('.hk-defer-menu');
    await expect(menu).toBeVisible();
    await expect(caret).toHaveAttribute('aria-expanded', 'true');
    await expect(menu.locator('.hk-defer-snooze')).toBeVisible();
    await expect(menu.locator('.hk-defer-skip')).toBeVisible();
    // Each entry says what it does to the schedule — the verbs are not
    // self-explanatory, which is what the issue was about.
    await expect(menu.locator('.hk-defer-snooze .hk-defer-sub')).not.toBeEmpty();

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('the closed menu takes up no space and swallows no clicks', async ({ page }) => {
    // A regression guard with teeth. `.hk-defer-menu` sets `display: flex`, which
    // beats the user-agent rule for the hidden attribute — so without an explicit
    // override the menu renders while "hidden", floats over the row beneath it and
    // intercepts that row's Done button. The unit test cannot see this: it asserts
    // the `hidden` property, and jsdom does no layout.
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const menu = panel.locator('.hk-defer-menu').first();
    await expect(menu).toBeAttached();
    await expect(menu).toBeHidden();
    await expect(menu).toHaveCSS('display', 'none');

    // The real symptom: every Done in the list stays clickable.
    const dones = panel.locator('.done-btn');
    const count = await dones.count();
    expect(count).toBeGreaterThan(1);
    for (let i = 0; i < count; i += 1) {
      const box = await dones.nth(i).boundingBox();
      if (!box) continue;
      const topmost = await page.evaluate(
        ([x, y]) => {
          const el = document.elementFromPoint(x as number, y as number);
          const path = el?.shadowRoot ? [el] : [el];
          // Walk into shadow roots so the check names the real hit target.
          let node: Element | null = el;
          while (node?.shadowRoot) {
            const inner = node.shadowRoot.elementFromPoint(x as number, y as number);
            if (!inner || inner === node) break;
            node = inner;
            path.push(node);
          }
          return path.map((n) => n?.className || n?.tagName || '').join(' ');
        },
        [box.x + box.width / 2, box.y + box.height / 2],
      );
      expect(topmost).not.toContain('hk-defer');
    }
  });

  test('Escape closes the menu without acting', async ({ page }) => {
    const panel = await gotoPanel(page, `/tasks/${TASK.waterFilter}`);

    await panel.locator('.hk-split-caret').click();
    await expect(panel.locator('.hk-defer-menu')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(panel.locator('.hk-defer-menu')).toBeHidden();
  });

  test('the snooze dialog previews the date its preset resolves to', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await gotoPanel(page, `/tasks/${TASK.waterFilter}`);

    await panel.locator('.hk-split-caret').click();
    await panel.locator('.hk-defer-snooze').click();

    const dialog = panel.locator('ha-dialog[open]');
    // Same `ha-dialog-footer` structure every other dialog needs (#144): buttons
    // slotted straight onto ha-dialog silently do not render.
    const footer = dialog.locator('ha-dialog-footer[slot="footer"]');
    await expect(footer).toHaveCount(1);
    await expect(footer.locator('ha-button[slot="primaryAction"]')).toHaveCount(1);
    await expect(dialog.locator('[slot="headerTitle"]')).toBeVisible();

    // The user reads the resolved date rather than doing the arithmetic.
    const hint = dialog.locator('.hk-snooze-hint');
    await expect(hint).toBeVisible();
    await expect(hint).not.toBeEmpty();

    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('skipping logs the skip in history without counting it as a completion', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    // A live recurring task with existing history. (A completed one-off such as
    // `carRegistration` has no caret at all — there is no occurrence left to defer,
    // which is correct, and the dormant case below covers it.)
    const panel = await gotoPanel(page, `/tasks/${TASK.fridgeFilter}`);

    const before = await panel.locator('.hk-hist-sub').first().textContent();

    await panel.locator('.hk-split-caret').click();
    await panel.locator('.hk-defer-skip').click();

    const dialog = panel.locator('ha-dialog[open]');
    await expect(dialog.locator('[slot="headerTitle"]')).toBeVisible();
    await dialog.getByRole('button', { name: 'Skip' }).click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });

    // The skip shows in history, marked as one…
    const skipRow = panel.locator('.hk-hist-list li.hk-hist-is-skip').first();
    await expect(skipRow).toBeVisible({ timeout: 10_000 });
    await expect(skipRow.locator('.hk-hist-skip-chip')).toBeVisible();
    // …and the completion tally is exactly what it was, because a skip is the record
    // of *not* doing the thing. This is the assertion the separate log exists for.
    await expect(panel.locator('.hk-hist-sub').first()).toHaveText(before ?? '');

    // Undo it, so the seeded fixture is left as the other specs expect it.
    await skipRow.locator('.hk-hist-skip-del').click();
    await expect(panel.locator('.hk-hist-list li.hk-hist-is-skip')).toHaveCount(0, {
      timeout: 10_000,
    });

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a problem-sensor task offers snooze but not skip', async ({ page }) => {
    // The store rejects skip on a synced mirror — only the originating integration
    // can say the problem is dealt with — so offering it would be a dead button.
    // Snooze asserts nothing about the problem, so it stays.
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const blocked = panel.locator('.hk-card .done-blocked-wrap, .hk-card .hk-auto-clear').first();
    if ((await blocked.count()) === 0) test.skip(true, 'no completion-blocked task seeded');

    const row = panel.locator('.hk-card').filter({ has: blocked }).first();
    const caret = row.locator('.hk-split-caret');
    if ((await caret.count()) === 0) return; // dormant mirror: no caret at all, also correct
    await caret.click();
    await expect(row.locator('.hk-defer-snooze')).toBeVisible();
    await expect(row.locator('.hk-defer-skip')).toHaveCount(0);
  });

  test('turning a verb off in Settings withdraws it from the task page', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await gotoPanel(page, '/settings/skipsnooze');

    const card = panel.locator('#hk-settings-skipsnooze');
    await expect(card).toBeVisible();
    // Both default on, so the summary says so before anything is touched.
    await expect(card).toContainText(/available/i);

    const skipSwitch = card.locator('ha-selector-boolean ha-switch, ha-switch').nth(1);
    await skipSwitch.click();

    await gotoPanel(page, `/tasks/${TASK.waterFilter}`);
    await panel.locator('.hk-split-caret').click();
    await expect(panel.locator('.hk-defer-snooze')).toBeVisible();
    await expect(panel.locator('.hk-defer-skip')).toHaveCount(0);

    // Put it back — the seeded options are shared with the other specs.
    await gotoPanel(page, '/settings/skipsnooze');
    await panel.locator('#hk-settings-skipsnooze ha-switch').nth(1).click();
    await expect(panel.locator('#hk-settings-skipsnooze')).toContainText(/available/i);

    // Saving an option reloads the config entry, so a fetch landing inside that
    // window is answered `not_loaded`. That is the panel reporting a known transient
    // and retrying, not a fault — every other error still fails the test.
    const unexpected = errors.filter((e) => !e.includes('not_loaded'));
    expect(unexpected, `panel errors:\n${unexpected.join('\n')}`).toHaveLength(0);
  });

  test('on a phone the menu opens inside the viewport, not off the edge', async ({
    page,
  }) => {
    // A list row puts its actions hard against the right margin, so a menu anchored
    // to the split's left edge starts there and runs its full width past the screen.
    // The symptom is a page that scrolls sideways to reach half a menu, which is why
    // this asserts on the document's scroll width and not only on the menu's box.
    await page.setViewportSize({ width: 360, height: 800 });
    const panel = await gotoPanel(page, '/tasks');
    const row = panel.locator('ha-card.hk-card').filter({ hasText: 'Front door sensor' }).first();
    await row.scrollIntoViewIfNeeded();
    await row.locator('.hk-split-caret').first().click();

    const menu = row.locator('.hk-defer-menu').first();
    await expect(menu.locator('.hk-defer-skip')).toBeVisible();
    const box = await menu.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(360);
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBe(360);
  });

  test('a chip narrower than its label keeps that label inside the pill', async ({
    page,
  }) => {
    // A wrapped label had nowhere to go: the chip's container height is fixed, so the
    // second and third lines drew straight through the pill's outline and over the
    // row. "Managed by Battery Notes" on a phone did exactly that.
    //
    // The width is forced rather than waited for, because whether the seeded chip
    // happens to overflow depends on the viewport, the font and the integration's
    // name — none of which this is really about. What it is about is what happens
    // when a chip cannot fit, so the test creates that condition directly.
    await page.setViewportSize({ width: 360, height: 800 });
    const panel = await gotoPanel(page, '/tasks');
    const row = panel.locator('ha-card.hk-card').filter({ hasText: 'Front door sensor' }).first();
    await row.scrollIntoViewIfNeeded();
    const label = await row.evaluate((card) => {
      const chip = card.querySelectorAll('.hk-chips-inline ha-assist-chip')[1] as HTMLElement;
      chip.style.maxWidth = '110px';
      const el = (chip as HTMLElement & { shadowRoot: ShadowRoot }).shadowRoot.querySelector(
        'span.label',
      ) as HTMLElement;
      return { box: Math.round(el.getBoundingClientRect().height), scroll: el.scrollHeight };
    });
    // The label's box is a fixed-height line and does not grow, so its height says
    // nothing. What a wrapped label does is overflow that box — measured, 42 against
    // a 32px box — and that overflow is what draws through the pill's outline.
    expect(label.scroll).toBeLessThanOrEqual(label.box);
  });
});
