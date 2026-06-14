import type { Asset, Hass, Task } from './types';

/** Thin wrappers around the Home Keeper websocket commands. */

export async function getTasks(hass: Hass): Promise<Task[]> {
  const res = await hass.callWS<{ tasks: Task[] }>({ type: 'home_keeper/get_tasks' });
  return res.tasks;
}

export async function addTask(hass: Hass, task: Partial<Task>): Promise<Task> {
  const res = await hass.callWS<{ task: Task }>({
    type: 'home_keeper/add_task',
    task,
  });
  return res.task;
}

export async function updateTask(
  hass: Hass,
  taskId: string,
  updates: Partial<Task>,
): Promise<Task> {
  const res = await hass.callWS<{ task: Task }>({
    type: 'home_keeper/update_task',
    task_id: taskId,
    updates,
  });
  return res.task;
}

export async function deleteTask(hass: Hass, taskId: string): Promise<void> {
  await hass.callWS({ type: 'home_keeper/delete_task', task_id: taskId });
}

export async function completeTask(hass: Hass, taskId: string): Promise<Task> {
  const res = await hass.callWS<{ task: Task }>({
    type: 'home_keeper/complete_task',
    task_id: taskId,
  });
  return res.task;
}

export async function getAssets(hass: Hass): Promise<Asset[]> {
  const res = await hass.callWS<{ assets: Asset[] }>({ type: 'home_keeper/get_assets' });
  return res.assets;
}

export async function addAsset(hass: Hass, asset: Partial<Asset>): Promise<Asset> {
  const res = await hass.callWS<{ asset: Asset }>({
    type: 'home_keeper/add_asset',
    asset,
  });
  return res.asset;
}

export async function updateAsset(
  hass: Hass,
  assetId: string,
  updates: Partial<Asset>,
): Promise<Asset> {
  const res = await hass.callWS<{ asset: Asset }>({
    type: 'home_keeper/update_asset',
    asset_id: assetId,
    updates,
  });
  return res.asset;
}

export async function deleteAsset(hass: Hass, assetId: string): Promise<void> {
  await hass.callWS({ type: 'home_keeper/delete_asset', asset_id: assetId });
}

/**
 * Map every config entry id to its integration domain. Used to resolve a
 * device's brand logo (`brands.home-assistant.io`) for the device chip.
 */
export async function getEntryDomains(hass: Hass): Promise<Record<string, string>> {
  const entries = await hass.callWS<{ entry_id: string; domain: string }[]>({
    type: 'config_entries/get',
  });
  const map: Record<string, string> = {};
  for (const e of entries) map[e.entry_id] = e.domain;
  return map;
}
