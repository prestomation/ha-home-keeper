import { test, expect } from '@playwright/test';
import { callService, openDashboard, openPanel, shoppingListCard } from './helpers';

/**
 * The buy-reminder mirror, from the shopper's side.
 *
 * The integration suite proves the loop over the service API. What only a
 * browser shows is the payoff: the reminder appearing as an ordinary line on the
 * household's own shopping list card, and disappearing from it again. This is
 * also the surface the README screenshot captures — a captured surface with
 * nothing asserting on it is how #221 hid in plain sight for months.
 */

const SHOPPING_LIST = 'todo.shopping_list';
const APPLIANCE = 'E2E mirror appliance';
const REMINDER = 'Buy E2E cartridge';

type Ids = { assetId: string; partId: string };

/**
 * Read a Home Keeper list, answering `null` while the entry is mid-reload.
 *
 * Creating or retiring a buy reminder that owns device entities schedules a
 * deferred reload, during which these 500 with "No active coordinator". Inside an
 * `expect.poll` a thrown error ends the poll instead of retrying it, so the read
 * has to swallow it and let the next tick try again.
 */
async function listAssets(): Promise<any[] | null> {
  try {
    return (await callService('home_keeper', 'list_assets', {}, true)).assets;
  } catch {
    return null;
  }
}

async function listTasks(): Promise<any[] | null> {
  try {
    return (await callService('home_keeper', 'list_tasks', {}, true)).tasks;
  } catch {
    return null;
  }
}

/** Summaries currently on the household shopping list, optionally by status. */
async function shoppingSummaries(status?: string[]): Promise<string[]> {
  const data: Record<string, unknown> = { entity_id: SHOPPING_LIST };
  if (status) data.status = status;
  const resp = await callService('todo', 'get_items', data, true);
  return (resp[SHOPPING_LIST]?.items ?? []).map((i: any) => i.summary);
}

/** Retry a Home Keeper service call through the deferred entry-reload window. */
async function callWhenReady(
  service: string,
  data: Record<string, unknown>,
): Promise<void> {
  await expect
    .poll(
      async () => {
        try {
          await callService('home_keeper', service, data);
          return true;
        } catch {
          return false;
        }
      },
      { timeout: 40_000 },
    )
    .toBe(true);
}

test.describe('Home Keeper — buy reminders on the household shopping list', () => {
  let ids: Ids | null = null;

  test.beforeEach(async () => {
    await callService('home_keeper', 'add_asset', {
      name: APPLIANCE,
      parts: [
        {
          name: 'E2E cartridge',
          type: 'consumable',
          stock: 2,
          reorder_at: 1,
          create_buy_task: true,
          restock_quantity: 4,
        },
      ],
    });
    const asset = (await listAssets())!.find((a) => a.name === APPLIANCE);
    ids = { assetId: asset.id, partId: asset.parts[0].id };
    await callWhenReady('set_options', { shopping_list_entity: SHOPPING_LIST });
  });

  test.afterEach(async () => {
    // The container's store is the committed seed fixture, so this spec has to
    // leave nothing behind — appliance, option, and the line on the list.
    await callWhenReady('set_options', { shopping_list_entity: '' });
    if (ids) await callWhenReady('delete_asset', { asset_id: ids.assetId });
    ids = null;
    const leftovers = (await callService('todo', 'get_items', { entity_id: SHOPPING_LIST }, true))[
      SHOPPING_LIST
    ]?.items?.filter((i: any) => i.summary === REMINDER)
      .map((i: any) => i.uid);
    if (leftovers?.length) {
      await callService('todo', 'remove_item', { entity_id: SHOPPING_LIST, item: leftovers });
    }
  });

  test('a low part shows up on the shopping list, and leaves once it is restocked', async ({
    page,
  }) => {
    // Before: the shopper's list has no line for this part.
    await openPanel(page);
    expect(await shoppingSummaries()).not.toContain(REMINDER);

    // Drive the part below its reorder point.
    await callWhenReady('adjust_part_stock', {
      asset_id: ids!.assetId,
      part_id: ids!.partId,
      delta: -1,
    });

    await expect
      .poll(async () => await shoppingSummaries(['needs_action']), { timeout: 40_000 })
      .toContain(REMINDER);
    await openDashboard(page);
    const card = shoppingListCard(page);
    await expect(card).toBeVisible({ timeout: 30_000 });
    await expect(card).toContainText(REMINDER);

    // After: restock in Home Keeper and the line goes — asserted from both ends,
    // because a test that only checks the post-state also passes for a line that
    // was never there.
    await callWhenReady('adjust_part_stock', {
      asset_id: ids!.assetId,
      part_id: ids!.partId,
      delta: 5,
    });
    await expect
      .poll(async () => await shoppingSummaries(), { timeout: 40_000 })
      .not.toContain(REMINDER);
    await openDashboard(page);
    await expect(shoppingListCard(page)).not.toContainText(REMINDER);
  });

  test('ticking the line off restocks the part and clears the reminder', async ({ page }) => {
    await callWhenReady('adjust_part_stock', {
      asset_id: ids!.assetId,
      part_id: ids!.partId,
      delta: -1,
    });
    await expect
      .poll(async () => await shoppingSummaries(['needs_action']), { timeout: 40_000 })
      .toContain(REMINDER);

    // Tick it off in the browser, the way the shopper would — the card's checkbox,
    // not a service call.
    await openDashboard(page);
    const card = shoppingListCard(page);
    await expect(card).toBeVisible({ timeout: 30_000 });
    const row = card.locator('ha-check-list-item, ha-md-list-item').filter({ hasText: REMINDER }).first();
    await row.locator('ha-checkbox, input[type="checkbox"]').first().click();

    // Home Keeper completes the reminder, which restocks the part (1 + 4) and
    // retires it.
    await expect
      .poll(
        async () => {
          const asset = (await listAssets())?.find((a) => a.id === ids!.assetId);
          return asset?.parts?.[0]?.stock ?? null;
        },
        { timeout: 60_000 },
      )
      .toBe(5);
    await expect
      .poll(
        async () => {
          const tasks = await listTasks();
          if (tasks === null) return null; // mid-reload; not an answer either way
          return tasks.some((t) => ((t.source || {}).buy || {}).asset_id === ids!.assetId);
        },
        { timeout: 40_000 },
      )
      .toBe(false);
  });
});
