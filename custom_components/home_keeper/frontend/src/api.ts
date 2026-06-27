import type {
  Asset,
  AssetDocument,
  Companion,
  Hass,
  HassLabel,
  HomeKeeperOptions,
  Inventory,
  Profile,
  Task,
} from './types';

/** Thin wrappers around the Home Keeper websocket commands. */

/** Read the companion integrations for the Settings → Companions section. */
export async function getCompanions(hass: Hass): Promise<Companion[]> {
  const res = await hass.callWS<{ companions: Companion[] }>({
    type: 'home_keeper/get_companions',
  });
  return res?.companions ?? [];
}

export async function getTasks(hass: Hass): Promise<Task[]> {
  const res = await hass.callWS<{ tasks: Task[] }>({ type: 'home_keeper/get_tasks' });
  return res.tasks;
}

/**
 * The HA label registry, keyed by `label_id`. Home Assistant doesn't eagerly
 * populate `hass.labels` on every surface (unlike areas/devices), so the card
 * fetches it directly to resolve label ids to display names/colors for its chips.
 */
export async function getLabels(hass: Hass): Promise<Record<string, HassLabel>> {
  const list = await hass.callWS<HassLabel[]>({ type: 'config/label_registry/list' });
  const map: Record<string, HassLabel> = {};
  for (const label of list) map[label.label_id] = label;
  return map;
}

/** Read the integration options (for the Settings tab). */
export async function getOptions(
  hass: Hass,
): Promise<{ options: HomeKeeperOptions; notifyTargets: string[] }> {
  const res = await hass.callWS<{ options: HomeKeeperOptions; notify_targets?: string[] }>({
    type: 'home_keeper/get_options',
  });
  return { options: res.options, notifyTargets: res.notify_targets ?? [] };
}

/** Saved profiles (filters) — used by the dashboard card's profile picker. */
export async function getProfiles(hass: Hass): Promise<Profile[]> {
  const res = await hass.callWS<{ profiles: Profile[] }>({
    type: 'home_keeper/get_profiles',
  });
  return res.profiles ?? [];
}

/** Persist a partial options change (the backend reloads + re-syncs). */
export async function setOptions(
  hass: Hass,
  options: Partial<HomeKeeperOptions>,
): Promise<HomeKeeperOptions> {
  const res = await hass.callWS<{ options: HomeKeeperOptions }>({
    type: 'home_keeper/set_options',
    options,
  });
  return res.options;
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

/**
 * Link a task to an appliance consumable/part (so completing it draws down stock
 * and fires the low-stock reorder event), or clear the link by passing nulls.
 */
export async function setTaskConsumable(
  hass: Hass,
  taskId: string,
  assetId: string | null,
  partId: string | null,
): Promise<Task> {
  const res = await hass.callWS<{ task: Task }>({
    type: 'home_keeper/set_task_consumable',
    task_id: taskId,
    asset_id: assetId,
    part_id: partId,
  });
  return res.task;
}

/** Optional per-completion metadata sent with a completion or an edit. */
export interface CompletionMetadata {
  note?: string;
  cost?: number;
  photo?: string;
  who?: string;
}

/** Drop empty metadata keys so we never send blank `note: ""` etc. */
function metadataMsg(metadata?: CompletionMetadata): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (!metadata) return out;
  if (metadata.note) out.note = metadata.note;
  if (metadata.cost != null && !Number.isNaN(metadata.cost)) out.cost = metadata.cost;
  if (metadata.photo) out.photo = metadata.photo;
  if (metadata.who) out.who = metadata.who;
  return out;
}

export async function completeTask(
  hass: Hass,
  taskId: string,
  metadata?: CompletionMetadata,
): Promise<Task> {
  const res = await hass.callWS<{ task: Task }>({
    type: 'home_keeper/complete_task',
    task_id: taskId,
    ...metadataMsg(metadata),
  });
  return res.task;
}

/**
 * Amend a recorded completion's metadata (identified by its `ts`). Every metadata
 * key is always sent (blanks omitted) so clearing a field on the backend works:
 * an omitted key clears it server-side.
 */
export async function updateCompletion(
  hass: Hass,
  taskId: string,
  ts: string,
  metadata: CompletionMetadata,
): Promise<Task> {
  const res = await hass.callWS<{ task: Task }>({
    type: 'home_keeper/update_completion',
    task_id: taskId,
    ts,
    ...metadataMsg(metadata),
  });
  return res.task;
}

/** Remove a single completion from a task (undo an accidental "done"). */
export async function deleteCompletion(
  hass: Hass,
  taskId: string,
  ts: string,
): Promise<Task> {
  const res = await hass.callWS<{ task: Task }>({
    type: 'home_keeper/delete_completion',
    task_id: taskId,
    ts,
  });
  return res.task;
}

/** Remove a single completion from an appliance's archived task history. */
export async function deleteArchivedCompletion(
  hass: Hass,
  assetId: string,
  taskId: string,
  ts: string,
): Promise<Asset> {
  const res = await hass.callWS<{ asset: Asset }>({
    type: 'home_keeper/delete_archived_completion',
    asset_id: assetId,
    task_id: taskId,
    ts,
  });
  return res.asset;
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

/** Adjust a part's on-hand spare count by `delta` (clamped at zero server-side). */
export async function adjustPartStock(
  hass: Hass,
  assetId: string,
  partId: string,
  delta: number,
): Promise<Asset> {
  const res = await hass.callWS<{ asset: Asset }>({
    type: 'home_keeper/adjust_part_stock',
    asset_id: assetId,
    part_id: partId,
    delta,
  });
  return res.asset;
}

/** Attach an external link document (manual/warranty/receipt) to an appliance. */
export async function addAssetDocument(
  hass: Hass,
  assetId: string,
  document: Partial<AssetDocument>,
): Promise<Asset> {
  const res = await hass.callWS<{ asset: Asset }>({
    type: 'home_keeper/add_asset_document',
    asset_id: assetId,
    document: { ...document, kind: 'link' },
  });
  return res.asset;
}

/** Detach a document (link or file) from an appliance; the file blob is deleted. */
export async function removeAssetDocument(
  hass: Hass,
  assetId: string,
  documentId: string,
): Promise<Asset> {
  const res = await hass.callWS<{ asset: Asset }>({
    type: 'home_keeper/remove_asset_document',
    asset_id: assetId,
    document_id: documentId,
  });
  return res.asset;
}

/** Edit an existing document: rename it, or (for a link) change its URL. A file's
 *  blob is immutable here, so only its display name is editable. */
export async function updateAssetDocument(
  hass: Hass,
  assetId: string,
  documentId: string,
  changes: { name?: string; url?: string },
): Promise<Asset> {
  const res = await hass.callWS<{ asset: Asset }>({
    type: 'home_keeper/update_asset_document',
    asset_id: assetId,
    document_id: documentId,
    changes,
  });
  return res.asset;
}

/** Mint a short-lived signed URL the browser can open for a file document. */
export async function signDocumentUrl(
  hass: Hass,
  assetId: string,
  documentId: string,
): Promise<string> {
  const res = await hass.callWS<{ url: string }>({
    type: 'home_keeper/sign_document_url',
    asset_id: assetId,
    document_id: documentId,
  });
  return res.url;
}

/**
 * Upload a file document to an appliance via the Home Keeper HTTP view. The binary
 * can't ride the websocket, so this POSTs multipart with the auth token. `documentId`
 * is a client-minted uuid that becomes the document's id. Returns the updated asset.
 */
export async function uploadAssetDocument(
  hass: Hass,
  assetId: string,
  documentId: string,
  file: File,
  name?: string,
): Promise<Asset> {
  const body = new FormData();
  body.append('file', file, file.name);
  if (name) body.append('name', name);
  const token = hass.auth?.data?.access_token;
  const res = await fetch(`/api/home_keeper/document/${assetId}/${documentId}`, {
    method: 'POST',
    body,
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) {
    // Only a JSON {message} is a real Home Keeper error. A non-JSON body (e.g. an
    // nginx HTML "413 Request Entity Too Large") means something *in front of* HA
    // rejected the upload — surface that distinctly so the panel can guide the user.
    let detail = '';
    try {
      detail = ((await res.json()) as { message?: string }).message ?? '';
    } catch {
      /* non-JSON body (a proxy's error page) — leave detail empty */
    }
    const error = new Error(detail || `Upload failed (${res.status})`) as UploadError;
    error.status = res.status;
    error.serverMessage = !!detail;
    throw error;
  }
  return ((await res.json()) as { asset: Asset }).asset;
}

/** An upload failure, tagged with the HTTP status and whether Home Keeper (vs a proxy
 *  in front of HA) produced the message. */
export interface UploadError extends Error {
  status?: number;
  serverMessage?: boolean;
}

/** Fetch the home-inventory report (for insurance) plus a ready-to-save CSV. */
export async function exportInventory(
  hass: Hass,
): Promise<{ inventory: Inventory; csv: string }> {
  return hass.callWS<{ inventory: Inventory; csv: string }>({
    type: 'home_keeper/export_inventory',
  });
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

/**
 * Set of config entry ids that are currently *loaded*. Used to detect orphaned
 * managed tasks: a managed task whose owning `config_entry_id` is not in this set
 * (uninstalled, disabled, or failing to set up) is no longer protected and can be
 * cleaned up by the user.
 */
export async function getLoadedEntryIds(hass: Hass): Promise<Set<string>> {
  const entries = await hass.callWS<{ entry_id: string; state: string }[]>({
    type: 'config_entries/get',
  });
  const ids = new Set<string>();
  for (const e of entries) if (e.state === 'loaded') ids.add(e.entry_id);
  return ids;
}
