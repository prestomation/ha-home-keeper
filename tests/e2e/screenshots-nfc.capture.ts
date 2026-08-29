/**
 * One-off screenshot capture for NFC/RFID tag completion (issue #211) — not part of
 * the e2e suite (filename isn't *.spec.ts). Run:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-nfc.capture.ts \
 *     --config=screenshots-nfc.config.ts
 *
 * Covers the two README shots:
 *  44.  The task form's NFC/RFID tag picker (holding a registry tag) with the
 *       require-scan toggle beneath it.
 *  44b. The task list wearing the new chips: an NFC chip on a quick-log task and a
 *       lock on a scan-required one, whose Done button is blocked.
 *
 * Seeds two HA tags and binds them to seeded tasks up front; undoes both bindings at
 * the end so the fixture is untouched for any capture that runs after this one.
 */
import { test, expect } from '@playwright/test';
import { openPanel } from './tests/helpers';
import { centre, shotWithDrawer } from './shots';
import { TASK } from './fixture-ids';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

test('capture NFC tag picker + chips', async ({ page }) => {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-name').first()).toBeVisible();

  // Seed: two tags in HA's registry (idempotent — a re-run finds them existing),
  // one bound as a quick-log tag, one bound with the scan requirement.
  await page.evaluate(async (IDS) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const tags: any[] = await hass.callWS({ type: 'tag/list' });
    const ensure = async (tag_id: string, name: string) => {
      if (!tags.some((t) => t.id === tag_id)) {
        await hass.callWS({ type: 'tag/create', tag_id, name });
      }
    };
    await ensure('fridge-filter-tag', 'Fridge filter');
    await ensure('furnace-filter-tag', 'Furnace filter');
    await hass.callService('home_keeper', 'update_task', {
      task_id: IDS.TASK.fridgeFilter,
      tag_id: 'fridge-filter-tag',
    });
    await hass.callService('home_keeper', 'update_task', {
      task_id: IDS.TASK.furnaceFilter,
      tag_id: 'furnace-filter-tag',
      require_tag_scan: true,
    });
  }, { TASK });

  // Fresh load so the panel refetches tasks and the tag registry.
  await openPanel(page);
  await expect(panel.locator(`.hk-card[data-id="${TASK.fridgeFilter}"] .hk-tag`)).toBeVisible({
    timeout: 10_000,
  });
  await expect(panel.locator(`.hk-card[data-id="${TASK.furnaceFilter}"] .hk-tag`)).toBeVisible();
  await page.waitForTimeout(600);

  // 44b. The list: fridge filter wears the NFC chip, furnace filter the lock (its
  // Done button greyed out).
  await page.screenshot({ path: `${OUT}/44b-panel-task-nfc-chip.png`, fullPage: true });

  // 44. The edit form: the tag picker holding "Fridge filter" and the require-scan
  // toggle below it.
  await panel.locator(`.detail-open[data-detail-id="${TASK.fridgeFilter}"]`).click();
  await expect(panel.locator('.hk-detail-title')).toBeVisible();
  await panel.locator('.d-edit').click();
  await expect(panel.locator('#hk-task-form')).toBeVisible();
  await expect(panel.locator('#hk-task-form ha-selector-select').first()).toBeVisible({
    timeout: 10_000,
  });
  // Editing happens in a drawer that scrolls its own content, and the tag picker sits
  // below its fold — bring it into frame, then let the helper decide between a
  // full-page and a viewport capture. Centre the require-scan toggle rather than the
  // picker itself: the two belong together in this shot, and the toggle is the lower
  // of the pair, so centring it keeps both on screen.
  await centre(panel.locator('#hk-task-form ha-selector-boolean').first());
  await page.waitForTimeout(600);
  await shotWithDrawer(page, `${OUT}/44-panel-task-tag-form.png`);
  await panel.locator('#f-cancel').click();
  await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });

  // Undo the bindings (flag first in the same call — clearing the tag alone while
  // the flag stands is rejected by design).
  await page.evaluate(async (IDS) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    await hass.callService('home_keeper', 'update_task', {
      task_id: IDS.TASK.furnaceFilter,
      tag_id: null,
      require_tag_scan: false,
    });
    await hass.callService('home_keeper', 'update_task', {
      task_id: IDS.TASK.fridgeFilter,
      tag_id: null,
    });
  }, { TASK });
});
