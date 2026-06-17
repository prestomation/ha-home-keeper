// `triggered` is a condition-driven task with no schedule: its `next_due` is its
// state (absent/null = dormant, a timestamp = armed/due-now). Owned by another
// integration; rendered read-only in the panel. See docs/INTEGRATING.md.
export type RecurrenceType = 'floating' | 'fixed' | 'triggered';
export type Unit = 'days' | 'weeks' | 'months';
export type Freq = 'DAILY' | 'WEEKLY' | 'MONTHLY';

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
  device_id?: string | null;
  area_id?: string | null;
  enabled?: boolean;
  last_completed?: string | null;
  next_due?: string;
  completions?: { ts: string }[];
  // Provenance for tasks derived/owned by another source (e.g. an appliance wear
  // part). Such tasks are managed by their source, so the panel hides edit/delete.
  source?: { part?: { asset_id: string; part_id: string } } | null;
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
}

export interface HassArea {
  area_id: string;
  name: string;
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
  states?: Record<string, HassEntity>;
  language?: string;
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
