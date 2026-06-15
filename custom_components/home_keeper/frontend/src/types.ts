export type RecurrenceType = 'floating' | 'fixed';
export type Unit = 'days' | 'weeks' | 'months';
export type Freq = 'DAILY' | 'WEEKLY' | 'MONTHLY';

export interface Task {
  id: string;
  name: string;
  notes?: string;
  recurrence_type: RecurrenceType;
  interval: number;
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

export interface Hass {
  callWS<T = unknown>(msg: Record<string, unknown>): Promise<T>;
  devices?: Record<string, HassDevice>;
  areas?: Record<string, HassArea>;
  language?: string;
}

export type AssetKind = 'virtual' | 'existing';
export type PartType = 'consumable' | 'wear';

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
  serial_number: string;
  purchase_date?: string | null;
  install_date?: string | null;
  warranty_expiry?: string | null;
  warranty_active?: boolean | null;
  warranty_provider: string;
  vendor: string;
  cost?: number | null;
  spares_value: number;
  part_count: number;
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

/** An appliance/asset: a virtual device we own, or metadata on an existing one. */
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
  manufacture_date?: string | null;
  purchase_date?: string | null;
  install_date?: string | null;
  warranty_expiry?: string | null;
  warranty_provider?: string;
  vendor?: string;
  cost?: number | null;
  manual_url?: string;
  notes?: string;
  parts?: Part[];
  parent_asset_id?: string | null;
  related_device_ids?: string[];
  task_history?: TaskHistoryEntry[];
}

export interface PanelInfo {
  config?: Record<string, unknown>;
}
