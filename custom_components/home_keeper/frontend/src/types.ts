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
}

export interface HassDevice {
  id: string;
  name?: string;
  name_by_user?: string | null;
  manufacturer?: string | null;
  model?: string | null;
  area_id?: string | null;
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
}

export interface PanelInfo {
  config?: Record<string, unknown>;
}
