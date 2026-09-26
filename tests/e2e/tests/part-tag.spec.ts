import { test, expect } from '@playwright/test';
import { callService, gotoTab, listTasks, openPanel, openPart } from './helpers';
import { ASSET, PART, TASK } from '../fixture-ids';

/**
 * An NFC/RFID tag bound to a wear item, not to a task.
 *
 * A task the reconciler derives from a wear part has no Edit of its own, so the tag
 * picker the task form offers never reached it. The part editor offers the same pair
 * now, and the reconciler copies the binding onto the derived task. The unit tests
 * prove that copy; what only a browser and a real container show is that the fields
 * reach the editor a household uses, and that a tag set on the part comes out on the
 * task Home Assistant lists.
 */

const TAG = 'e2e-anode-tag';

/** The seeded water heater, read back over the public service API. */
async function readHeater(): Promise<Record<string, any>> {
  const { assets } = await callService('home_keeper', 'list_assets', {}, true);
  return assets.find((a: any) => a.id === ASSET.waterHeater);
}

/**
 * Rewrite the anode rod's binding, sending the other parts back as they are —
 * `update_asset` replaces the whole list. Only the keys the service accepts go back;
 * the upload-only file fields are refused by its schema.
 */
async function setAnodeTag(tagId: string | null, requireScan = false): Promise<void> {
  const heater = await readHeater();
  const WRITABLE = [
    'id', 'name', 'part_number', 'type', 'vendor', 'cost', 'url', 'notes',
    'replace_interval', 'replace_unit', 'last_replaced', 'stock', 'reorder_at',
    'stock_unit', 'consume_quantity', 'create_buy_task', 'restock_quantity',
    'action', 'use_noun', 'use_task_name', 'replace_also_every',
    'tag_id', 'require_tag_scan',
  ];
  await callService('home_keeper', 'update_asset', {
    asset_id: heater.id,
    parts: heater.parts.map((p: Record<string, unknown>) => {
      const out: Record<string, unknown> = {};
      for (const key of WRITABLE) if (p[key] !== undefined && p[key] !== null) out[key] = p[key];
      if (p.id === PART.anode) {
        out.tag_id = tagId;
        out.require_tag_scan = requireScan;
      }
      return out;
    }),
  });
}

async function anodeTask(): Promise<Record<string, any>> {
  return (await listTasks()).find((t) => t.id === TASK.anode)!;
}

test.describe('a tag on a wear item', () => {
  test('is offered in the part editor for a wear item and not for a consumable', { tag: '@responsive' }, async ({
    page,
  }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await gotoTab(panel, 'appliances');
    await panel.locator(`.detail-open[data-detail-id="${ASSET.waterHeater}"]`).click();
    await panel.locator('.d-edit').click();

    const form = panel.locator('#hk-asset-form');
    await expect(form).toBeVisible();
    const parts = form.locator('details').filter({ hasText: 'Parts & wear items' });
    if ((await parts.count()) > 0) {
      const open = await parts.first().evaluate((d: HTMLDetailsElement) => d.open);
      if (!open) await parts.first().locator('summary').click();
    }

    // First part in the seed: the anode rod, a wear item replaced every 12 months.
    const anode = parts.locator('.hk-part').first();
    await openPart(anode);
    await expect(
      anode.locator('ha-selector-select').filter({ hasText: 'NFC/RFID tag' }),
    ).toBeVisible();
    await expect(
      anode.locator('ha-selector-boolean').filter({ hasText: 'Require a tag scan to complete' }),
    ).toBeVisible();

    // Third part: the descaling solution, a consumable. It creates no task, so there
    // is nothing for a scan to complete and the pair is not offered.
    const descaler = parts.locator('.hk-part').nth(2);
    await openPart(descaler);
    await expect(descaler.getByText('Stock unit', { exact: false })).toBeVisible();
    await expect(descaler.locator('ha-selector-select').filter({ hasText: 'NFC/RFID tag' })).toHaveCount(0);
  });

  test.describe('bound through the service', () => {
    test.afterEach(async () => {
      // The container's store is the committed seed fixture; put the part back.
      await setAnodeTag(null);
      await expect.poll(async () => (await anodeTask()).tag_id ?? null).toBeNull();
    });

    test('lands on the derived task, and leaves it when the part drops it', async ({ page }) => {
      await setAnodeTag(TAG, true);
      await expect.poll(async () => (await anodeTask()).tag_id).toBe(TAG);
      expect((await anodeTask()).require_tag_scan).toBe(true);

      // What the household sees: the derived task's row wears the lock chip, and its
      // Done button is the greyed one — the same treatment a task bound in its own
      // form gets, because it is the same task field.
      await openPanel(page);
      const panel = page.locator('home-keeper-panel').first();
      const row = panel.locator(`ha-card.hk-card[data-id="${TASK.anode}"]`);
      await expect(row.locator('.hk-tag')).toBeVisible({ timeout: 10_000 });
      await expect(row.locator('.done-blocked-wrap')).toBeVisible();

      await setAnodeTag(null);
      await expect.poll(async () => (await anodeTask()).tag_id ?? null).toBeNull();
      expect((await anodeTask()).require_tag_scan).toBe(false);
    });
  });
});
