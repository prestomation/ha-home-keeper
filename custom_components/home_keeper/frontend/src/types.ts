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
}

export interface Hass {
  callWS<T = unknown>(msg: Record<string, unknown>): Promise<T>;
  devices?: Record<string, HassDevice>;
  language?: string;
}

export interface PanelInfo {
  config?: Record<string, unknown>;
}
