import { test, expect } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';
import { ASSET, TASK } from '../fixture-ids';

/**
 * What the task list says about itself (#262).
 *
 * `docs/images/44-panel-shopping-filter.png` had been documenting the dead end in this
 * first test for months — an empty scope with no way out of it but the pill you came
 * from — and nothing failed, because a capture photographs a surface without asserting
 * on it. These are the assertions.
 */
test.describe('Home Keeper panel — the list tells the truth about what it shows', () => {
  test('an empty scope is dimmed on the way in and escapable on the way out', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    const seg = panel.locator('.hk-seg[data-seg="filter"]');
    const shopping = seg.locator('.hk-seg-btn[data-seg-val="shopping"]');
    const all = seg.locator('.hk-seg-btn[data-seg-val="all"]');

    // The seeded store has no shopping tasks, so that pill reads 0 and recedes.
    await expect(shopping).toHaveClass(/hk-seg-empty/);
    await expect(all, 'a scope with tasks in it is not dimmed').not.toHaveClass(/hk-seg-empty/);
    const dimmed = await shopping.evaluate((el) => Number(getComputedStyle(el).opacity));
    expect(dimmed, 'an empty scope should be visibly dimmer').toBeLessThan(1);

    // Still pressable — "is it really empty?" is a fair question.
    await shopping.click();
    await expect(panel.locator('ha-alert')).toContainText('No tasks match this filter');

    // ...and the answer now comes with a way back, rather than leaving the pill you
    // came from as the only exit.
    const showAll = panel.locator('#hk-show-all');
    await expect(showAll).toBeVisible();
    await showAll.click();
    await expect(all).toHaveAttribute('aria-pressed', 'true');
    await expect(panel.locator('.hk-card').first()).toBeVisible();

    // The selected pill is never dimmed, even at zero: it must stay a live control.
    await shopping.click();
    await expect(shopping).not.toHaveClass(/hk-seg-empty/);
    await panel.locator('#hk-show-all').click();

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a completed one-off reads as done under every grouping, not just Status', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    // "Renew car registration" is seeded complete: a one-off with a last_completed and
    // no next_due. Group by Status tucks it into a collapsed Completed section; every
    // other grouping used to leave it mid-list with nothing but a small pill to say so,
    // which made changing the grouping change what looked like your active list.
    const done = panel.locator(`.hk-card[data-id="${TASK.carRegistration}"]`);

    for (const grouping of ['area', 'device', 'none', 'status']) {
      await panel.locator('select[data-seg-select="group"]').selectOption(grouping);
      // Status keeps it in a collapsed section, so open every section first.
      for (const details of await panel.locator('details.hk-group').all()) {
        if (!(await details.getAttribute('open'))) await details.locator('summary').click();
      }
      await expect(done, `grouping: ${grouping}`).toHaveClass(/hk-task-done/);
      const struck = await done
        .locator('.hk-name')
        .evaluate((el) => getComputedStyle(el).textDecorationLine);
      expect(struck, `grouping: ${grouping}`).toContain('line-through');
    }

    await panel.locator('select[data-seg-select="group"]').selectOption('status');
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a task pointing at a device the registry lost shows no chip, not its id', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    // "Replace water filter" is seeded against a device id that is not in the registry.
    // It used to render that id as a chip label, cut mid-string by the chip's border.
    const row = panel.locator(`.hk-card[data-id="${TASK.waterFilter}"]`);
    await expect(row).toBeVisible();
    await expect(row.locator('ha-assist-chip.hk-device-chip')).toHaveCount(0);

    // Nothing anywhere on the list may render a bare 32-hex device id — not a chip,
    // not a section heading under Group by Device, not an appliance title.
    const listText = await panel.evaluate(
      (el: HTMLElement) => (el.shadowRoot?.textContent || '').replace(/\s+/g, ' '),
    );
    expect(listText, 'a raw device id leaked into the list').not.toMatch(/[0-9a-f]{32}/);

    await panel.locator('select[data-seg-select="group"]').selectOption('device');
    const groupedText = await panel.evaluate(
      (el: HTMLElement) => (el.shadowRoot?.textContent || '').replace(/\s+/g, ' '),
    );
    expect(groupedText, 'a raw device id headed a Group by Device section').not.toMatch(
      /[0-9a-f]{32}/,
    );
    await panel.locator('select[data-seg-select="group"]').selectOption('status');

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a task owned by its source says so, rather than just withholding the buttons', async ({
    page,
  }) => {
    // A reconciler-derived wear-part task offers no Edit and no Delete, which is
    // correct — the appliance's part record owns it. But it used to say nothing about
    // that, so the whole action row read "<name> / Done" and looked like a surface
    // that had failed to render half of itself. The managed-integration path beside it
    // has always explained itself; this is the same idea said out loud.
    const errors = trackPanelErrors(page);
    await page.goto(`/home-keeper/tasks/${TASK.anode}`, { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    await panel.waitFor({ state: 'attached', timeout: 45_000 });

    await expect(panel.locator('.d-done')).toBeVisible();
    await expect(panel.locator('.d-edit')).toHaveCount(0);
    await expect(panel.locator('.d-del')).toHaveCount(0);
    // The explanation stands where the two missing buttons would have been.
    await expect(panel.locator('.hk-detail-actions .hk-managed-info')).toBeVisible();
    await expect(panel.locator('.hk-detail-actions .hk-managed-info')).not.toBeEmpty();

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('both lists put a chip on the same rail, and an appliance row still says what it holds', async ({
    page,
  }) => {
    // `docs/images/5-panel-appliances-list.png` documented the old three-line appliance
    // block for as long as it existed and never asserted a thing about it. A row is a
    // grid now: name, chips, then what the appliance holds. These are the assertions
    // that the restyle did not quietly drop a chip on the way.
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    // Every task row's chip cluster starts at the same x — that is the whole point of
    // the fixed track, and the thing a screenshot cannot check. The rails are gated at
    // 1151px, so this asserts at a width that has them. Only rows that are actually
    // laid out: the Status grouping keeps Monitored and Completed in closed <details>,
    // whose rows measure zero and would agree with nothing.
    await page.setViewportSize({ width: 1400, height: 900 });
    const lefts = (sel: string) =>
      panel.evaluate(
        (el: HTMLElement, s: string) =>
          [...(el.shadowRoot?.querySelectorAll(s) || [])]
            .filter((c) => c.firstElementChild && c.getBoundingClientRect().width > 0)
            .map((c) => Math.round(c.getBoundingClientRect().left)),
        sel,
      );

    const starts = await lefts('.hk-row-task .hk-chips-inline');
    expect(starts.length, 'the seeded list should carry chips to align').toBeGreaterThan(1);
    expect(new Set(starts).size, `chip clusters start at ${starts.join(', ')}`).toBe(1);

    // The status pills line up too — they used to agree only on where they ended.
    const pills = await lefts('.hk-row-task .hk-status');
    expect(pills.length).toBeGreaterThan(1);
    expect(new Set(pills).size, `status pills start at ${pills.join(', ')}`).toBe(1);

    await panel.locator('#tab-appliances').click();
    const row = panel.locator(`.hk-card[data-id="${ASSET.shades}"]`);
    await expect(row).toBeVisible();
    // Its device chip qualifies the name; its sub-device count is what it holds, and
    // that moved to the status rail rather than being dropped.
    await expect(row.locator('.hk-chips .hk-device-chip')).toHaveCount(1);
    await expect(row.locator('.hk-status ha-assist-chip')).not.toHaveCount(0);
    await expect(row.locator('.hk-status')).toContainText('subdevice');

    // The whole row still opens the appliance, not only the text at its left end.
    // Splitting the row into tracks nearly left the opener holding one of them.
    await row.click({ position: { x: 10, y: 10 } });
    await expect(page).toHaveURL(new RegExp(`/home-keeper/appliances/${ASSET.shades}`));
    await page.goBack();
    await expect(row).toBeVisible();
    const box = (await row.boundingBox())!;
    await row.click({ position: { x: box.width - 10, y: box.height / 2 } });
    await expect(page, 'the right-hand end of an appliance row opens it too').toHaveURL(
      new RegExp(`/home-keeper/appliances/${ASSET.shades}`),
    );

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
