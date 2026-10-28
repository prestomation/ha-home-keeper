/**
 * The reporter's case for issue #493: 1 water filter system with 2 different filters,
 * and 1 task that replaces both. Shared by the spec, the screenshot capture and the
 * walkthrough, so the 3 show the same records.
 *
 * Each caller owns what this makes: it calls `removeWaterSystem` when it is done,
 * because the container's store is the committed seed fixture.
 */
import { expect } from '@playwright/test';
import { callService } from './tests/helpers';

export const WATER = {
  appliance: 'Water filter system',
  task: 'Replace water filters',
  sediment: 'Sediment filter',
  carbon: 'Carbon filter',
  // A long name, so the list row has to cut it and still show the count.
  salt: 'Water softener salt pellets',
  saltTask: 'Top up softener salt',
};

export type WaterIds = {
  assetId: string;
  deviceId: string;
  taskId: string;
  sedimentId: string;
  carbonId: string;
  saltId: string;
  saltTaskId: string;
};

/**
 * Call a Home Keeper service, and retry it through the deferred entry reload that a
 * new appliance or a device attach starts. A call made while the entry reloads
 * answers 500 "No active coordinator".
 */
export async function callWhenReady(
  service: string,
  data: Record<string, unknown>,
  returnResponse = false,
): Promise<any> {
  let result: any;
  await expect
    .poll(
      async () => {
        try {
          result = await callService('home_keeper', service, data, returnResponse);
          return true;
        } catch {
          return false;
        }
      },
      { timeout: 60_000 },
    )
    .toBe(true);
  return result;
}

/**
 * Make the appliance and the task, attach the task to the appliance's device, and
 * link both filters. A second task on the same device takes the salt, which has a
 * long name. The sediment filter takes 2 for each completion. The carbon
 * filter is at its reorder point, so the list chip reads "2 parts · Low stock".
 */
export async function seedWaterSystem(): Promise<WaterIds> {
  await removeLeftovers();
  await callWhenReady('add_asset', {
    name: WATER.appliance,
    manufacturer: 'Aquasana',
    parts: [
      { name: WATER.sediment, type: 'consumable', stock: 6, reorder_at: 2 },
      { name: WATER.carbon, type: 'consumable', stock: 1, reorder_at: 1 },
      { name: WATER.salt, type: 'consumable', stock: 8, reorder_at: 2 },
    ],
  });
  // The virtual device is provisioned after the save, and its id is written back.
  let asset: any;
  await expect
    .poll(
      async () => {
        const listed = await callWhenReady('list_assets', {}, true);
        asset = listed.assets.find((a: any) => a.name === WATER.appliance);
        return Boolean(asset?.device_id);
      },
      { timeout: 60_000 },
    )
    .toBe(true);
  const added = await callWhenReady(
    'add_task',
    {
      name: WATER.task,
      recurrence_type: 'floating',
      interval: 6,
      unit: 'months',
      device_id: asset.device_id,
    },
    true,
  );
  const salted = await callWhenReady(
    'add_task',
    {
      name: WATER.saltTask,
      recurrence_type: 'floating',
      interval: 1,
      unit: 'months',
      device_id: asset.device_id,
    },
    true,
  );
  const ids: WaterIds = {
    assetId: asset.id,
    deviceId: asset.device_id,
    taskId: added.task_id,
    sedimentId: asset.parts.find((p: any) => p.name === WATER.sediment).id,
    carbonId: asset.parts.find((p: any) => p.name === WATER.carbon).id,
    saltId: asset.parts.find((p: any) => p.name === WATER.salt).id,
    saltTaskId: salted.task_id,
  };
  await callWhenReady('set_task_consumable', {
    task_id: ids.taskId,
    parts: [
      { asset_id: ids.assetId, part_id: ids.sedimentId, quantity: 2 },
      { asset_id: ids.assetId, part_id: ids.carbonId },
    ],
  });
  await callWhenReady('set_task_consumable', {
    task_id: ids.saltTaskId,
    parts: [{ asset_id: ids.assetId, part_id: ids.saltId }],
  });
  return ids;
}

/** Delete the task and the appliance. Safe to call twice. */
export async function removeWaterSystem(ids: WaterIds | null): Promise<void> {
  if (ids) {
    await callWhenReady('delete_task', { task_id: ids.taskId }).catch(() => undefined);
    await callWhenReady('delete_task', { task_id: ids.saltTaskId }).catch(() => undefined);
    await callWhenReady('delete_asset', { asset_id: ids.assetId }).catch(() => undefined);
  }
  await removeLeftovers();
}

/** A run that died half way can leave records with these names. Remove them. */
async function removeLeftovers(): Promise<void> {
  const tasks = (await callWhenReady('list_tasks', {}, true)).tasks as any[];
  for (const task of tasks.filter((t) => t.name === WATER.task || t.name === WATER.saltTask)) {
    await callWhenReady('delete_task', { task_id: task.id });
  }
  const assets = (await callWhenReady('list_assets', {}, true)).assets as any[];
  for (const asset of assets.filter((a) => a.name === WATER.appliance)) {
    await callWhenReady('delete_asset', { asset_id: asset.id });
  }
}
