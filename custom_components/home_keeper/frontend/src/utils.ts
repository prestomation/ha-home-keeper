import type { Asset, HassArea, Task } from './types';

/** Escape user-provided text before injecting into innerHTML. */
export function escapeHTML(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Human-readable summary of a task's recurrence rule. */
export function recurrenceSummary(task: Task): string {
  const n = task.interval || 1;
  if (task.recurrence_type === 'floating') {
    const unit = task.unit || 'days';
    const singular = unit.replace(/s$/, '');
    const label = n === 1 ? `every ${singular}` : `every ${n} ${unit}`;
    return `${label} after completion`;
  }
  const freqWord: Record<string, string> = {
    DAILY: 'day',
    WEEKLY: 'week',
    MONTHLY: 'month',
  };
  const word = freqWord[task.freq || 'DAILY'] || 'day';
  return n === 1 ? `every ${word}` : `every ${n} ${word}s`;
}

/** True when the task's next due date is at or before now. */
export function isOverdue(task: Task, now: Date = new Date()): boolean {
  if (!task.next_due) return false;
  return new Date(task.next_due).getTime() <= now.getTime();
}

/** Compact relative description of a due date, e.g. "in 3 days" / "2 days ago". */
export function dueLabel(task: Task, now: Date = new Date()): string {
  if (!task.next_due) return '—';
  const due = new Date(task.next_due);
  const diffMs = due.getTime() - now.getTime();
  const days = Math.round(diffMs / 86_400_000);
  if (days === 0) return 'today';
  if (days > 0) return days === 1 ? 'tomorrow' : `in ${days} days`;
  const ago = Math.abs(days);
  return ago === 1 ? 'yesterday' : `${ago} days ago`;
}

/** Resolve a device id to its display name using hass.devices. */
export function deviceName(
  devices: Record<string, { name?: string; name_by_user?: string | null }> | undefined,
  deviceId: string | null | undefined,
): string {
  if (!deviceId) return '';
  const dev = devices?.[deviceId];
  if (!dev) return deviceId;
  return dev.name_by_user || dev.name || deviceId;
}

/** Resolve an area id to its name using hass.areas. */
export function areaName(
  areas: Record<string, HassArea> | undefined,
  areaId: string | null | undefined,
): string {
  if (!areaId) return '';
  return areas?.[areaId]?.name || areaId;
}

/** Compact one-line summary of an asset's notable metadata for the card. */
export function assetSummary(
  asset: Asset,
  areas?: Record<string, HassArea>,
): string {
  const parts: string[] = [];
  const makeModel = [asset.manufacturer, asset.model].filter(Boolean).join(' ');
  if (makeModel) parts.push(makeModel);
  const area = areaName(areas, asset.area_id);
  if (area) parts.push(area);
  if (asset.warranty_expiry) parts.push(`warranty to ${asset.warranty_expiry}`);
  return parts.length ? parts.join(' · ') : 'No details yet';
}
