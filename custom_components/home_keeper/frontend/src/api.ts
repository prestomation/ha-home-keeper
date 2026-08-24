import type {
  Asset,
  AssetDocument,
  Companion,
  Hass,
  HassLabel,
  HomeKeeperOptions,
  Inventory,
  Part,
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

/**
 * The HA tag registry (NFC/RFID tags), as picker options. A tag carries an
 * optional friendly `name`; an unnamed one is only ever identified by its id, so
 * that is what the option shows.
 */
export async function getTags(hass: Hass): Promise<{ value: string; label: string }[]> {
  const list = await hass.callWS<{ id: string; name?: string | null }[]>({ type: 'tag/list' });
  return (Array.isArray(list) ? list : []).map((tag) => ({
    value: tag.id,
    label: tag.name || tag.id,
  }));
}

/** Read the integration options (for the Settings tab). */
export async function getOptions(
  hass: Hass,
): Promise<{
  options: HomeKeeperOptions;
  notifyTargets: string[];
  ownTodoEntities: string[];
}> {
  const res = await hass.callWS<{
    options: HomeKeeperOptions;
    notify_targets?: string[];
    own_todo_entities?: string[];
  }>({
    type: 'home_keeper/get_options',
  });
  return {
    options: res.options,
    notifyTargets: res.notify_targets ?? [],
    ownTodoEntities: res.own_todo_entities ?? [],
  };
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

const INTRO_DISMISSED_KEY = 'home_keeper_intro_dismissed';

/** Whether the current user has dismissed the first-run intro banner — stored
 *  server-side per-user via HA's own frontend user-data store, so it follows the
 *  user across browsers/devices instead of being pinned to one localStorage. */
export async function getIntroDismissed(hass: Hass): Promise<boolean> {
  const res = await hass.callWS<{ value: boolean | null }>({
    type: 'frontend/get_user_data',
    key: INTRO_DISMISSED_KEY,
  });
  return res.value === true;
}

export async function setIntroDismissed(hass: Hass): Promise<void> {
  await hass.callWS({
    type: 'frontend/set_user_data',
    key: INTRO_DISMISSED_KEY,
    value: true,
  });
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
  /** A sensor task's meter reading for this completion. Numeric like `cost`, so it
   *  needs the same `!= null` treatment — a genuine reading of 0 (a fresh hour
   *  meter) is falsy and a truthiness check would silently drop it. */
  reading?: number;
}

/** Drop empty metadata keys so we never send blank `note: ""` etc. */
function metadataMsg(metadata?: CompletionMetadata): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (!metadata) return out;
  if (metadata.note) out.note = metadata.note;
  if (metadata.cost != null && !Number.isNaN(metadata.cost)) out.cost = metadata.cost;
  if (metadata.photo) out.photo = metadata.photo;
  if (metadata.who) out.who = metadata.who;
  if (metadata.reading != null && !Number.isNaN(metadata.reading))
    out.reading = metadata.reading;
  return out;
}

export async function completeTask(
  hass: Hass,
  taskId: string,
  metadata?: CompletionMetadata,
  completedAt?: string,
): Promise<Task> {
  const res = await hass.callWS<{ task: Task }>({
    type: 'home_keeper/complete_task',
    task_id: taskId,
    ...(completedAt ? { completed_at: completedAt } : {}),
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

/**
 * Re-timestamp a recorded completion (back-date or correct it), identified by its
 * current `ts`. Distinct from `updateCompletion`, which edits metadata but never
 * moves the timestamp.
 */
export async function moveCompletion(
  hass: Hass,
  taskId: string,
  oldTs: string,
  newTs: string,
): Promise<Task> {
  const res = await hass.callWS<{ task: Task }>({
    type: 'home_keeper/move_completion',
    task_id: taskId,
    old_ts: oldTs,
    new_ts: newTs,
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

export async function archiveAsset(hass: Hass, assetId: string): Promise<Asset> {
  const res = await hass.callWS<{ asset: Asset }>({
    type: 'home_keeper/archive_asset',
    asset_id: assetId,
  });
  return res.asset;
}

export async function restoreAsset(hass: Hass, assetId: string): Promise<Asset> {
  const res = await hass.callWS<{ asset: Asset }>({
    type: 'home_keeper/restore_asset',
    asset_id: assetId,
  });
  return res.asset;
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

/** Progress of an in-flight upload, reported to `UploadOptions.onProgress`. */
export interface UploadProgress {
  /** Bytes of the request body sent so far. */
  loaded: number;
  /** Total bytes to send; 0 when the browser can't compute it. */
  total: number;
  /** No byte counts available (yet) — show an indeterminate bar. */
  indeterminate: boolean;
  /** The body is fully sent and we're now waiting on the server to store it. */
  sent: boolean;
}

/** Per-request upload options: progress reporting and cancellation. */
export interface UploadOptions {
  onProgress?: (progress: UploadProgress) => void;
  signal?: AbortSignal;
}

/** An upload failure, tagged with the HTTP status and whether Home Keeper (vs a proxy
 *  in front of HA) produced the message. `aborted` marks a user cancellation (nothing
 *  to report); `bytesSent` is how far the body got, which distinguishes a connection
 *  dropped *mid-body* (a proxy's size limit) from one that never opened. */
export interface UploadError extends Error {
  status?: number;
  serverMessage?: boolean;
  aborted?: boolean;
  bytesSent?: number;
}

/**
 * POST a multipart body to a Home Keeper upload view, reporting byte progress.
 *
 * Deliberately `XMLHttpRequest` and not `fetch`: the Fetch spec exposes progress only
 * for the *response* body, so a `fetch` upload is a black box until it finishes. (The
 * `ReadableStream` + `duplex: 'half'` workaround is Chromium-only and needs HTTP/2 or
 * HTTPS — no good for a panel plenty of people open over plain http on the LAN.)
 * `xhr.upload.onprogress` is still the only portable way to drive a progress bar.
 *
 * No `xhr.timeout` is set (0 = none) on purpose: a 20 MB upload over a slow WAN link
 * must not be killed by a client-side timer. Cancellation is explicit, via `signal`.
 */
function postUpload<T>(
  url: string,
  token: string | undefined,
  body: FormData,
  opts?: UploadOptions,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    let bytesSent = 0;

    const fail = (message: string, extra: Partial<UploadError> = {}): void => {
      const error = new Error(message) as UploadError;
      error.bytesSent = bytesSent;
      Object.assign(error, extra);
      reject(error);
    };

    xhr.open('POST', url, true);
    // Unlike fetch's options object, headers can only be set after open().
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    // Leave responseType as text: the proxy detection below relies on JSON.parse
    // *throwing* for a non-JSON error body. Setting 'json' would silently null it out.

    // Always tracked, even with no onProgress callback: `bytesSent` is what tells a
    // failed upload apart from one cut off mid-body (a proxy's size limit).
    xhr.upload.addEventListener('progress', (e) => {
      bytesSent = e.loaded;
      opts?.onProgress?.({
        loaded: e.loaded,
        total: e.lengthComputable ? e.total : 0,
        indeterminate: !e.lengthComputable,
        sent: false,
      });
    });
    // The last byte is on the wire, but the server still has to validate the bytes,
    // write the blob and save the store — a real pause for a large file. Flag it so
    // the UI can say "saving" instead of sitting at 100% looking hung.
    xhr.upload.addEventListener('load', () => {
      opts?.onProgress?.({ loaded: bytesSent, total: bytesSent, indeterminate: true, sent: true });
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as T);
        } catch {
          fail(`Upload failed (${xhr.status})`, { status: xhr.status, serverMessage: false });
        }
        return;
      }
      // Only a JSON {message} is a real Home Keeper error. A non-JSON body (e.g. an
      // nginx HTML "413 Request Entity Too Large") means something *in front of* HA
      // rejected the upload — surface that distinctly so the panel can guide the user.
      let detail = '';
      try {
        detail = (JSON.parse(xhr.responseText) as { message?: string }).message ?? '';
      } catch {
        /* non-JSON body (a proxy's error page) — leave detail empty */
      }
      fail(detail || `Upload failed (${xhr.status})`, {
        status: xhr.status,
        serverMessage: !!detail,
      });
    });

    // A transport-level failure has no status. Whether the body was still in flight
    // tells the panel whether to suspect a proxy body limit that cut the connection.
    xhr.addEventListener('error', () => {
      fail(`Upload failed (${xhr.status || 0})`, { status: xhr.status || 0, serverMessage: false });
    });
    xhr.addEventListener('abort', () => {
      fail('Upload cancelled', { aborted: true });
    });

    if (opts?.signal) {
      if (opts.signal.aborted) {
        fail('Upload cancelled', { aborted: true });
        return;
      }
      opts.signal.addEventListener('abort', () => xhr.abort(), { once: true });
    }

    xhr.send(body);
  });
}

/** Build the multipart body shared by both upload views. */
function uploadBody(file: File, name?: string): FormData {
  const body = new FormData();
  body.append('file', file, file.name);
  if (name) body.append('name', name);
  return body;
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
  opts?: UploadOptions,
): Promise<Asset> {
  const res = await postUpload<{ asset: Asset }>(
    `/api/home_keeper/document/${assetId}/${documentId}`,
    hass.auth?.data?.access_token,
    uploadBody(file, name),
    opts,
  );
  return res.asset;
}

/**
 * Upload (or replace) a part's single attached file via the Home Keeper HTTP view.
 * The binary can't ride the websocket, so this POSTs multipart with the auth token —
 * same shape as `uploadAssetDocument`, keyed by the part's own id instead of a
 * client-minted document id (a part has exactly one file slot).
 *
 * Returns just the updated **part** (not the whole asset): the caller has an
 * in-progress edit draft covering every part in the form, and syncing the whole
 * `parts` array from the server would stomp any unsaved edits to sibling parts. The
 * caller grafts only this part's `file_*` fields into its draft by id.
 */
export async function uploadPartFile(
  hass: Hass,
  assetId: string,
  partId: string,
  file: File,
  name?: string,
  opts?: UploadOptions,
): Promise<Part> {
  const res = await postUpload<{ part: Part }>(
    `/api/home_keeper/part_document/${assetId}/${partId}`,
    hass.auth?.data?.access_token,
    uploadBody(file, name),
    opts,
  );
  return res.part;
}

/** Detach a part's attached file; its on-disk blob is deleted. */
export async function removePartFile(
  hass: Hass,
  assetId: string,
  partId: string,
): Promise<Asset> {
  const res = await hass.callWS<{ asset: Asset }>({
    type: 'home_keeper/remove_part_file',
    asset_id: assetId,
    part_id: partId,
  });
  return res.asset;
}

/** Mint a short-lived signed URL the browser can open for a part's attached file. */
export async function signPartFileUrl(
  hass: Hass,
  assetId: string,
  partId: string,
): Promise<string> {
  const res = await hass.callWS<{ url: string }>({
    type: 'home_keeper/sign_part_file_url',
    asset_id: assetId,
    part_id: partId,
  });
  return res.url;
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
