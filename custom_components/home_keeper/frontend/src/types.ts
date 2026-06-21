// `triggered` is a condition-driven task with no schedule: its `next_due` is its
// state (absent/null = dormant, a timestamp = armed/due-now). Owned by another
// integration; rendered read-only in the panel. See docs/INTEGRATING.md.
// `one-off` is a user-scheduled do-once task: it carries a `due` date and goes
// dormant (next_due null) once completed, landing in the panel's Completed section.
export type RecurrenceType = 'floating' | 'fixed' | 'triggered' | 'one-off';
export type Unit = 'days' | 'weeks' | 'months';
export type Freq = 'DAILY' | 'WEEKLY' | 'MONTHLY';

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
  // Provenance for tasks derived/owned by another source (e.g. an appliance wear
  // part, or a synced `device_class: problem` binary sensor). Such tasks are managed
  // by their source, so the panel hides edit/delete.
  source?: {
    part?: { asset_id: string; part_id: string };
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
 *  model -> device card, manual_url -> configuration_url, cost -> inventory value);
 *  all other descriptive/temporal facts live in the free-form `metadata` list. */
export interface Asset {
  id: string;
  kind: AssetKind;
  name: string;
  device_id?: string | null;
  area_id?: string | null;
  icon?: string;
  manufacturer?: string;
  model?: string;
  cost?: number | null;
  manual_url?: string;
  metadata?: MetadataEntry[];
  parts?: Part[];
  parent_asset_id?: string | null;
  related_device_ids?: string[];
  task_history?: TaskHistoryEntry[];
}

export interface PanelInfo {
  config?: Record<string, unknown>;
}

/** Integration-wide options, edited from the panel's Settings tab (and mirrored by
 *  the options flow + the `home_keeper.set_options` service). */
export interface HomeKeeperOptions {
  sync_problem_sensors: boolean;
  problem_sensor_exclude_entities: string[];
  problem_sensor_exclude_areas: string[];
  problem_sensor_exclude_labels: string[];
  // Auto-delete a completed one-off this many days after completion; 0 = keep forever.
  one_off_retention_days: number;
  // Catalog glue domains dismissed from the Companions "Suggested" list.
  dismissed_companions?: string[];
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
