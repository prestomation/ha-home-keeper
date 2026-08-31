import { test, expect, Page } from '@playwright/test';
import { callService, openPanel } from './helpers';
import { TASK } from '../fixture-ids';
import { PHONE, WIDE } from '../viewports';

/**
 * The accessibility contracts an audit found broken, pinned so they stay fixed.
 *
 * All of these were invisible to the rest of the suite: nothing failed when the
 * selected filter was conveyed by fill alone, when every click threw the keyboard
 * back to `<body>`, or when the phone sheet left thirty tabbable controls underneath
 * an opaque overlay. They fail loudly here instead.
 */
const panelOf = (page: Page) => page.locator('home-keeper-panel').first();

test.describe(
  'Home Keeper panel — accessibility contracts',
  { tag: '@responsive' },
  () => {
  test('the selected filter is stated, not just coloured', async ({ page }) => {
    await openPanel(page);
    const panel = panelOf(page);
    const chips = panel.locator('.hk-seg[data-seg="filter"] .hk-seg-btn');
    await expect(chips.first()).toBeVisible();
    // Exactly one is pressed, and it is the one that is styled active.
    await expect(panel.locator('.hk-seg[data-seg="filter"] [aria-pressed="true"]')).toHaveCount(1);
    await expect(panel.locator('.hk-seg-btn.active').first()).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    // The group and the dropdowns carry names; the visible caption is a sibling span,
    // so without these a screen reader reads an unlabelled combo box.
    await expect(panel.locator('.hk-seg').first()).toHaveAttribute('role', 'group');
    await expect(panel.locator('.hk-seg').first()).not.toHaveAttribute('aria-label', '');
    for (const sel of await panel.locator('.hk-menu-select').all()) {
      expect(await sel.getAttribute('aria-label')).toBeTruthy();
    }
    // …and no two of them share a name. The scope pills were handed `group.by`, the
    // same name the Group by dropdown beside them carries, so a screen reader heard
    // two controls that do different things announced identically and had no way to
    // tell which one it had landed on. Having *a* name was never the whole contract.
    const names = await panel.evaluate((el) =>
      Array.from(
        el.shadowRoot!.querySelectorAll('.hk-seg[aria-label], .hk-menu-select[aria-label]'),
      ).map((n) => n.getAttribute('aria-label')),
    );
    expect(names.length, 'expected the controls row to carry named controls').toBeGreaterThan(1);
    expect(new Set(names).size, `duplicate control names: ${names.join(' / ')}`).toBe(names.length);
  });

  test('keyboard focus survives the re-render an activation causes', async ({ page }) => {
    // `_render()` replaces the whole shadow tree, so without restoring focus every
    // filter click drops the keyboard at the top of the document.
    await openPanel(page);
    const panel = panelOf(page);
    await panel.locator('.hk-seg-btn').nth(1).focus();
    await page.keyboard.press('Enter');
    await expect(panel.locator('.hk-seg-btn.active')).toHaveText(/Overdue/);
    const still = await panel.evaluate((el) => {
      const active = el.shadowRoot?.activeElement as HTMLElement | null;
      return { cls: active?.className ?? '', val: active?.getAttribute('data-seg-val') };
    });
    expect(still.cls).toContain('hk-seg-btn');
    expect(still.val).toBe('overdue');
  });

  test('the chip overflow is a control, so nothing clickable is unreachable', async ({ page }) => {
    // Several of the chips it folds away do something when clicked — a device chip
    // opens the device page — so a bare "+2" caption put an action behind a
    // navigation that used to be one click.
    //
    // No seeded task carries three chips, so make one: the battery task already has a
    // part chip and its integration's chip, and a tag is a third.
    await callService('home_keeper', 'update_task', {
      task_id: TASK.doorBattery,
      tag_id: 'a11y-overflow-tag',
    });
    await openPanel(page);
    const panel = panelOf(page);
    // The panel is told about the change over its websocket subscription, so the row
    // may still be the pre-tag one on first paint.
    const more = panel.locator(`ha-card.hk-card[data-id="${TASK.doorBattery}"] .hk-chip-more`);
    await expect(more).toBeVisible({ timeout: 20_000 });
    await expect(more).toHaveAttribute('aria-expanded', 'false');
    const row = panel.locator(`ha-card.hk-card[data-id="${TASK.doorBattery}"]`);
    const hiddenBefore = await row.locator('.hk-chips-inline > *:nth-child(3)').isVisible();
    expect(hiddenBefore).toBe(false);
    await more.click();
    await expect(more).toHaveAttribute('aria-expanded', 'true');
    await expect(row.locator('.hk-chips-inline > *:nth-child(3)')).toBeVisible();

    await callService('home_keeper', 'update_task', {
      task_id: TASK.doorBattery,
      tag_id: '',
    });
  });

  test('the appliance sub-tabs are navigation, not a broken tab widget', async ({ page }) => {
    // They declared role="tab" and then implemented none of the contract: no
    // tabpanel, no roving tabindex, no arrow keys. Plain links are the honest shape.
    await page.goto('/home-keeper/appliances');
    const panel = panelOf(page);
    await panel.locator('.hk-card[data-id]').first().click();
    await expect(panel.locator('.hk-subtab').first()).toBeVisible();
    // (HA's own ha-tab-group owns the three top-level tabs and uses role="tab"
    // legitimately — this is about the sub-tabs and the phone bar we added.)
    expect(await panel.locator('.hk-subtab[role="tab"]').count()).toBe(0);
    expect(await panel.locator('.hk-subtabs[role="tablist"]').count()).toBe(0);
    expect(await panel.locator('.hk-bottombar[role="tablist"]').count()).toBe(0);
    await expect(panel.locator('.hk-subtab.active')).toHaveAttribute('aria-current', 'page');
  });
  },
);

/**
 * The drawer's two personalities, and the seam between them.
 *
 * These resize the page themselves rather than running under a viewport project,
 * because that is the assertion: `_syncDrawerModality()` reads `matchMedia` — the
 * one place in the panel that reads the viewport at all — and a project with a fixed
 * width can never exercise it. The 1400px case is also wider than any project.
 */
test.describe('Home Keeper panel — the drawer across the sheet threshold', () => {
  test('the phone sheet is a modal dialog, and the list under it is inert', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await openPanel(page);
    const panel = panelOf(page);
    await panel.locator('#add-btn').click();
    await expect(panel.locator('#hk-task-form')).toBeVisible();

    const open = await panel.evaluate((el) => {
      const root = el.shadowRoot!;
      const drawer = root.querySelector('.hk-drawer[data-open]');
      return {
        role: drawer?.getAttribute('role'),
        modal: drawer?.getAttribute('aria-modal'),
        // Without `inert` the keyboard walks a list nobody can see, and Enter on a
        // row navigates away and discards the open form.
        wrapInert: root.querySelector('.hk-wrap')?.hasAttribute('inert'),
        // The tab bar is a *sibling* of `.hk-wrap`, not a child, so inerting the wrap
        // left it live — the one thing still tappable behind an `aria-modal` overlay,
        // and a tap on it silently discarded the open form. A modal that leaves a
        // navigation control reachable is not one.
        barInert: root.querySelector('.hk-bottombar')?.hasAttribute('inert'),
        focusInside: !!drawer?.contains(root.activeElement),
      };
    });
    expect(open).toEqual({
      role: 'dialog',
      modal: 'true',
      wrapInert: true,
      barInert: true,
      focusInside: true,
    });

    // Escape closes it and gives back both the list and the way off this tab.
    await page.keyboard.press('Escape');
    await expect(panel.locator('#hk-task-form')).toHaveCount(0);
    expect(
      await panel.evaluate((el) => {
        const root = el.shadowRoot!;
        return [
          root.querySelector('.hk-wrap')?.hasAttribute('inert'),
          root.querySelector('.hk-bottombar')?.hasAttribute('inert'),
        ];
      }),
    ).toEqual([false, false]);
  });

  test('beside the list, the drawer is a panel and the list stays live', async ({ page }) => {
    // The counterpart to the test above: at a width where the drawer sits *next to*
    // the list rather than over it, disabling the list would take away marking
    // another task done — which the inline form it replaced never did.
    await page.setViewportSize(WIDE);
    await openPanel(page);
    const panel = panelOf(page);
    await panel.locator('#add-btn').click();
    await expect(panel.locator('#hk-task-form')).toBeVisible();
    expect(
      await panel.evaluate((el) => el.shadowRoot?.querySelector('.hk-wrap')?.hasAttribute('inert')),
    ).toBe(false);
    // A Done button in the dimmed list is still a real target.
    await expect(panel.locator('#hk-list .done-btn').first()).toBeVisible();
    expect(
      await panel.evaluate(
        (el) =>
          getComputedStyle(el.shadowRoot!.querySelector('#hk-list')!).pointerEvents !== 'none',
      ),
    ).toBe(true);
  });

});

/**
 * Closing the drawer has to give the keyboard back.
 *
 * Opening it renders, and `_render()` replaces the whole shadow tree — so the opener
 * captured on the way in is a detached node by the time the drawer closes. Holding the
 * element meant the `isConnected` guard was never true and focus was silently dropped
 * on `<body>`: a keyboard reader who pressed Edit and changed their mind was returned
 * to the top of the document, on every one of the three ways out.
 *
 * Untagged: this is about focus, not layout, and the panel drawer is the same object
 * at every width — the sheet's modality is `a11y.spec`'s threshold block above.
 */
test.describe('Home Keeper panel — the drawer hands the keyboard back', () => {
  const focusedId = (panel: ReturnType<typeof panelOf>): Promise<string | null> =>
    panel.evaluate((el) => (el.shadowRoot?.activeElement as HTMLElement | null)?.id ?? null);

  for (const exit of [
    { name: 'Escape', close: (page: Page) => page.keyboard.press('Escape') },
    {
      name: 'the close button',
      close: (page: Page) => panelOf(page).locator('#hk-drawer-close').click(),
    },
    {
      name: 'Cancel',
      close: (page: Page) => panelOf(page).locator('#f-cancel').click(),
    },
  ]) {
    test(`${exit.name} returns focus to Add task`, async ({ page }) => {
      await page.setViewportSize(WIDE);
      await openPanel(page);
      const panel = panelOf(page);

      await panel.locator('#add-btn').focus();
      await panel.locator('#add-btn').click();
      await expect(panel.locator('#hk-task-form')).toBeVisible();

      await exit.close(page);
      await expect(panel.locator('#hk-task-form')).toHaveCount(0);
      expect(await focusedId(panel)).toBe('add-btn');
    });
  }

  test('a Delete the reader thinks better of leaves Escape working', async ({ page }) => {
    // Opening the confirmation takes the drawer's Escape handler away, so one Escape
    // cannot dismiss both overlays. Cancelling has to give it back — otherwise the
    // drawer stands with no keyboard way out for the rest of the edit.
    await page.setViewportSize(WIDE);
    await page.goto(`/home-keeper/tasks/${TASK.fridgeFilter}`, { waitUntil: 'domcontentloaded' });
    const panel = panelOf(page);
    await panel.waitFor({ state: 'attached', timeout: 45_000 });
    await panel.locator('.d-edit').click();
    await expect(panel.locator('#hk-task-form')).toBeVisible();

    await panel.locator('.hk-drawer-delete').click();
    const scrim = page.locator('.hk-confirm-scrim');
    await expect(scrim).toBeVisible();
    // Cancel leads the confirmation's button row; Delete closes it.
    await scrim.locator('ha-button').first().click();
    await expect(scrim).toHaveCount(0);
    await expect(panel.locator('#hk-task-form')).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(panel.locator('#hk-task-form')).toHaveCount(0);
    // …and the keyboard lands back on the control that opened the drawer.
    expect(
      await panel.evaluate(
        (el) => (el.shadowRoot?.activeElement as HTMLElement | null)?.className ?? null,
      ),
    ).toContain('d-edit');
  });
});
