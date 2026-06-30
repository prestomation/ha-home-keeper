// `triggered` is a condition-driven task with no schedule: its `next_due` is its
// state (absent/null = dormant, a timestamp = armed/due-now). Owned by another
// integration; rendered read-only in the panel. See docs/INTEGRATING.md.
// `one-off` is a user-scheduled do-once task: it carries a `due` date and goes
// dormant (next_due null) once completed, landing in the panel's Completed section.
// `sensor` is a sensor-based task: Home Keeper derives its armed/dormant state from
// a bound numeric sensor (see `SensorBinding`). Like `triggered`, its `next_due` is
// its state; the user creates it and the backend watcher arms it.
export type RecurrenceType = 'floating' | 'fixed' | 'triggered' | 'one-off' | 'sensor';
export type Unit = 'days' | 'weeks' | 'months';
export type Freq = 'DAILY' | 'WEEKLY' | 'MONTHLY';
export type SensorMode = 'usage' | 'threshold';
export type SensorComparison = '>=' | '<=' | '>' | '<' | '==' | '!=';

/** The numeric-sensor binding of a sensor-based task. Only the keys relevant to
 *  `mode` are present: `target` for usage; `comparison`/`value`/`for_seconds` for
 *  threshold. `baseline` (usage) is the reading at creation / last completion,
 *  stamped by the backend watcher. `attribute` reads an entity attribute instead
 *  of the state. */
export interface SensorBinding {
  entity_id: string;
  mode: SensorMode;
  attribute?: string;
  target?: number;
  baseline?: number;
  comparison?: SensorComparison;
  value?: number;
  for_seconds?: number;
}

/** How a task captures per-completion detail when marked done:
 *  `none` = one-tap; `optional` = a details dialog, all fields optional;
 *  `required` = the dialog with `completion_required_fields` mandatory. */
export type CompletionDetail = 'none' | 'optional' | 'required';

/** One recorded completion. `ts` is the identity (ISO timestamp); the rest is the
 *  optional per-completion metadata (note / cost / photo id / who — a person id). */
export interface Completion {
  ts: string;
  note?: string;
  cost?: number;
  photo?: string;
  who?: string;
}

/** Ownership block set by an integration at task-creation time. Home Keeper
 *  inspects this (unlike the opaque `source`) to enforce UI behavior. */
export interface ManagedBy {
  integration: string;
  display_name: string;
  icon?: string;
  locked_fields?: string[];
  config_entry_id?: string;
  completion_prompt?: string;
  deletion_protected?: boolean;
  // The task can't be completed from Home Keeper (it's cleared by its source). The
  // panel hides the "Done" action and shows `completion_prompt` to explain. Used by
  // problem-sensor-synced tasks, which clear when the originating integration
  // resolves the underlying problem.
  completion_blocked?: boolean;
}

export interface Task {
  id: string;
  name: string;
  notes?: string;
  recurrence_type: RecurrenceType;
  // Absent on triggered tasks (no schedule). Present for floating/fixed.
  interval?: number;
  unit?: Unit;
  freq?: Freq;
  anchor?: string;
  // The chosen due date for a one-off task (absent on other kinds).
  due?: string;
  // The numeric-sensor binding for a sensor-based task (absent on other kinds).
  sensor?: SensorBinding | null;
  device_id?: string | null;
  area_id?: string | null;
  enabled?: boolean;
  last_completed?: string | null;
  next_due?: string;
  completions?: Completion[];
  // Per-task completion-capture mode (default `none` = one-tap done).
  completion_detail?: CompletionDetail;
  // Which metadata fields a `required` task makes mandatory. The panel gates a
  // required completion by reading this list (not a hard-coded field), so a future
  // per-field editor only needs to populate it.
  completion_required_fields?: string[];
  // HA label-registry ids attached directly to this task. The dashboard card can
  // filter by label, matching a task via its own labels or those on its device/area.
  labels?: string[];
  // References to appliance links the dashboard card surfaces on this task's row:
  // each pair points at an appliance document of kind `link` or a metadata entry of
  // type `link`. The card resolves them to a live name/URL and silently drops any
  // that no longer exist. Empty / absent = show none (the default).
  card_links?: { asset_id: string; entry_id: string }[];
  // Integration-provided metadata chips rendered in both the panel task list and the
  // dashboard card. Each chip has a label (required), an optional mdi: icon, and an
  // optional http(s) URL (clickable if present). Set by integrations via add_task /
  // update_task; not user-editable in the panel.
  task_chips?: { label: string; icon?: string; url?: string }[];
  // Provenance for tasks derived/owned by another source (e.g. an appliance wear
  // part, or a synced `device_class: problem` binary sensor). Such tasks are managed
  // by their source, so the panel hides edit/delete — EXCEPT a manual consumable
  // link (`part.manual`), which the user owns: completing it consumes a spare, but it
  // stays fully editable/deletable like any user task.
  source?: {
    part?: { asset_id: string; part_id: string; manual?: boolean };
    problem_sensor?: { entity_id: string };
  } | null;
  // Well-known ownership block that Home Keeper inspects. See docs/INTEGRATING.md §6.
  managed_by?: ManagedBy | null;
}

export interface HassDevice {
  id: string;
  name?: string;
  name_by_user?: string | null;
  manufacturer?: string | null;
  model?: string | null;
  area_id?: string | null;
  primary_config_entry?: string | null;
  config_entries?: string[];
  // HA label-registry ids applied to this device (Settings → Devices). A task
  // attached to a labelled device inherits the device's labels for card filtering.
  labels?: string[];
}

export interface HassArea {
  area_id: string;
  name: string;
  // HA label-registry ids applied to this area; inherited by a task's effective area.
  labels?: string[];
}

/** Minimal shape of a Home Assistant label-registry entry (only what the card reads). */
export interface HassLabel {
  label_id: string;
  name: string;
  color?: string | null;
  icon?: string | null;
}

/** Minimal shape of a Home Assistant entity state (only what the card reads). */
export interface HassEntity {
  entity_id: string;
  state: string;
  last_updated: string;
  attributes: Record<string, unknown>;
}

export interface Hass {
  callWS<T = unknown>(msg: Record<string, unknown>): Promise<T>;
  devices?: Record<string, HassDevice>;
  areas?: Record<string, HassArea>;
  labels?: Record<string, HassLabel>;
  states?: Record<string, HassEntity>;
  language?: string;
  // The instance's configured currency, used to format a completion's cost.
  config?: { currency?: string };
  // Auth token, used to POST a document upload to the Home Keeper HTTP view with an
  // Authorization header (the real `hass` object exposes this; we under-declare it).
  auth?: { data?: { access_token?: string } };
  // The live websocket connection; used by the card to subscribe to the
  // `home_keeper_task_completed` event so it refreshes when a task is completed
  // from another surface (the panel, a device button, or an automation).
  connection?: {
    subscribeEvents<T = unknown>(
      callback: (event: T) => void,
      eventType: string,
    ): Promise<() => void>;
  };
}

export type AssetKind = 'virtual' | 'existing';
export type PartType = 'consumable' | 'wear';
export type MetadataType = 'text' | 'link' | 'date';
export type DocumentKind = 'link' | 'file';

/** A document attached to an appliance: an external `link` (a URL) or an uploaded
 *  `file` (PDF/image) stored locally and served back through the document HTTP view.
 *  For a `file`, `filename`/`content_type`/`size` are backend-managed and the bytes
 *  are opened via a short-lived signed URL (see api.signDocumentUrl). */
interface AssetDocumentBase {
  id?: string;
  name: string;
  created?: string;
}
/** An external link document — points at a URL the browser opens directly. */
export interface AssetLinkDocument extends AssetDocumentBase {
  kind: 'link';
  url?: string;
}
/** An uploaded file document — a stored blob opened via a short-lived signed URL. */
export interface AssetFileDocument extends AssetDocumentBase {
  kind: 'file';
  filename?: string;
  content_type?: string;
  size?: number;
}
/**
 * An appliance document. A **discriminated union** on `kind` so the compiler forces
 * every consumer to branch before touching a kind-specific field (`url` vs
 * `filename`/`size`/`content_type`) — a missed kind is a build error, not a runtime
 * gap. See `documents.ts` for the shared display/open helpers.
 */
export type AssetDocument = AssetLinkDocument | AssetFileDocument;

/** A free-form metadata entry on an appliance: a typed label/value pair. A `date`
 *  entry with `track` set also becomes a date sensor on the device (opt-in). */
export interface MetadataEntry {
  id?: string;
  type: MetadataType;
  label: string;
  value: string;
  // Only meaningful for `date`: surface this date as a tracked sensor for automations.
  track?: boolean;
}

/** A structured part / wear item belonging to an appliance. */
export interface Part {
  id?: string;
  name: string;
  part_number?: string;
  type: PartType;
  vendor?: string;
  cost?: number | null;
  notes?: string;
  replace_interval?: number | null;
  replace_unit?: Unit | null;
  last_replaced?: string | null;
  // Spare-inventory tracking. `stock` is how many spares are on hand (decremented
  // when a wear-part replacement is completed); `reorder_at` is the low-stock
  // threshold at/below which a low-stock event fires. Both optional / untracked.
  stock?: number | null;
  reorder_at?: number | null;
}

/** One appliance row in the insurance/home-inventory export. */
export interface InventoryRow {
  id: string;
  name: string;
  kind: AssetKind;
  area?: string | null;
  manufacturer: string;
  model: string;
  cost?: number | null;
  spares_value: number;
  part_count: number;
  // Free-form metadata flattened to "label: value; …" for the export.
  details: string;
}

export interface Inventory {
  assets: InventoryRow[];
  totals: {
    asset_count: number;
    total_cost: number;
    spares_value: number;
    grand_total: number;
  };
}

/**
 * A deleted task's completion history, preserved on the appliance it belonged to.
 * Written by the backend when a task assigned to an appliance is removed, so the
 * appliance's maintenance history survives the task (reference-counting retention).
 */
export interface TaskHistoryEntry {
  task_id: string;
  task_name: string;
  part_id?: string | null;
  completions: { ts: string }[];
  archived_at?: string;
}

/** An appliance/asset: a virtual device we own, or metadata on an existing one.
 *  Only the fields that wire into Home Assistant stay structured (manufacturer /
 *  model -> device card, cost -> inventory value); all other descriptive/temporal
 *  facts live in the free-form `metadata` list, and manuals/warranties/receipts in
 *  the `documents` list. */
export interface Asset {
  id: string;
  kind: AssetKind;
  name: string;
  device_id?: string | null;
  area_id?: string | null;
  icon?: string;
  manufacturer?: string;
  model?: string;
  serial_number?: string;
  cost?: number | null;
  documents?: AssetDocument[];
  metadata?: MetadataEntry[];
  parts?: Part[];
  parent_asset_id?: string | null;
  related_device_ids?: string[];
  task_history?: TaskHistoryEntry[];
}

export interface PanelInfo {
  config?: Record<string, unknown>;
}

export type NotifyStatus = 'all' | 'overdue' | 'due_soon';
export type NotifyAction = 'complete' | 'snooze' | 'skip' | 'open';
export type NotifyStyle = 'walk' | 'digest';

/** Which tasks a profile surfaces (a saved filter). */
export interface NotifyFilter {
  labels: string[];
  areas: string[];
  devices: string[];
  status: NotifyStatus;
}

/** A named, reusable saved filter — consumed by notifications, the admin list, and
 *  the dashboard card (see backend profiles.py). */
export interface Profile {
  id: string;
  name: string;
  filter: NotifyFilter;
}

/** A delivery binding that references a Profile and adds how to deliver it (see
 *  backend notifications.py). */
export interface Notification {
  id: string;
  name: string;
  profile_id: string | null;
  targets: string[];
  actions: NotifyAction[];
  snooze_hours: number;
  style: NotifyStyle;
  auto: { overdue: boolean; due_soon: boolean };
}

/** Integration-wide options, edited from the panel's Settings tab (and mirrored by
 *  the options flow + the `home_keeper.set_options` service). */
export interface HomeKeeperOptions {
  sync_problem_sensors: boolean;
  problem_sensor_exclude_entities: string[];
  problem_sensor_exclude_devices: string[];
  problem_sensor_exclude_areas: string[];
  problem_sensor_exclude_labels: string[];
  // Auto-delete a completed one-off this many days after completion; 0 = keep forever.
  one_off_retention_days: number;
  // Catalog glue domains dismissed from the Companions "Suggested" list.
  dismissed_companions?: string[];
  // Saved filters and the notifications that consume them.
  profiles: Profile[];
  notifications: Notification[];
}

/**
 * A companion integration shown in Settings → Companions. Either *connected*
 * (self-registered, or a known glue that's installed) or *suggested* (a popular
 * upstream is installed but its glue isn't). See the backend `companions.py`.
 */
export interface Companion {
  domain: string;
  name: string;
  icon?: string;
  description?: string;
  status: 'connected' | 'suggested';
  // Connected rows: the integration domain whose options page "Configure" opens.
  configure_domain?: string;
  config_entry_id?: string | null;
  docs_url?: string | null;
  capabilities?: string[];
  // Suggested rows: where to install the glue, and which upstream triggered it.
  install_url?: string;
  upstream_domain?: string;
}
