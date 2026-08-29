import { test, expect } from '@playwright/test';
import { openAppliance, openPanel, trackPanelErrors } from './helpers';
import { ASSET, TASK } from '../fixture-ids';

/**
 * The id row is what makes the service layer reachable by hand: every
 * `home_keeper.*` service identifies its target by an id that, before this,
 * appeared in no UI a person reads. A screenshot proves it rendered once; these
 * assert it stays rendered, on every surface a service takes an id for.
 */
test.describe('Home Keeper panel — object ids are visible and copyable', { tag: '@responsive' }, () => {
  test('a task detail page shows its id with a copy button', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator(`.detail-open[data-detail-id="${TASK.fridgeFilter}"]`).click();

    const row = panel.locator('.hk-id-row');
    await expect(row).toHaveCount(1);
    // The id shown must be the one the services actually take.
    await expect(row.locator('code')).toHaveText(TASK.fridgeFilter);
    await expect(row.locator('ha-icon-button.hk-copy')).toHaveAttribute(
      'data-copy',
      TASK.fridgeFilter,
    );
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('an appliance page shows its own id and one per part and document', async ({ page }) => {
    await openPanel(page);
    // An appliance's sections are sub-tabs now, and only the open one renders, so
    // each id has to be read from the section that carries it rather than from one
    // long page.
    const panel = await openAppliance(page, ASSET.waterHeater, 'details');

    // The appliance's own id, on the About card. Anchored, because the part and
    // document ids on this page are all prefixed with it.
    await expect(
      panel.locator('code').filter({ hasText: new RegExp(`^${ASSET.waterHeater}$`) }),
    ).toBeVisible();

    // `adjust_part_stock` needs the part id as well as the appliance id, so the
    // part rows carry theirs too — that pairing is the whole point.
    await panel.locator('.hk-subtab[data-tab="parts"]').click();
    const partIds = panel.locator('.hk-part-row .hk-id-inline');
    await expect(partIds.first()).toBeVisible();
    for (const text of await partIds.locator('code').allTextContents()) {
      expect(text.trim()).not.toBe('');
    }

    // Documents likewise — `remove_asset_document` and friends take both ids.
    await panel.locator('.hk-subtab[data-tab="documents"]').click();
    await expect(panel.locator('.hk-doc-row .hk-id-inline code').first()).toBeVisible();
  });

  test('the copy button puts the id on the clipboard', async ({ page, context }) => {
    // Chromium only grants clipboard-write on an explicit permission.
    await context.grantPermissions(['clipboard-write', 'clipboard-read']);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator(`.detail-open[data-detail-id="${TASK.fridgeFilter}"]`).click();
    await panel.locator('.hk-id-row ha-icon-button.hk-copy').click();

    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe(TASK.fridgeFilter);
  });
});
