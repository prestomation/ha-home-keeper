import { t, tn } from './i18n';
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
    const base = (task.unit || 'days').replace(/s$/, ''); // day / week / month
    const unit = tn(`recurrence.unit.${base}`, n);
    return tn('recurrence.floating', n, { unit });
  }
  const freqBase: Record<string, string> = {
    DAILY: 'day',
    WEEKLY: 'week',
    MONTHLY: 'month',
  };
  const base = freqBase[task.freq || 'DAILY'] || 'day';
  const unit = tn(`recurrence.unit.${base}`, n);
  return tn('recurrence.fixed', n, { unit });
}

/** True when the task's next due date is at or before now. */
export function isOverdue(task: Task, now: Date = new Date()): boolean {
  if (!task.next_due) return false;
  return new Date(task.next_due).getTime() <= now.getTime();
}

/** Compact relative description of a due date, e.g. "in 3 days" / "2 days ago". */
export function dueLabel(task: Task, now: Date = new Date()): string {
  if (!task.next_due) return t('due.none');
  const due = new Date(task.next_due);
  const diffMs = due.getTime() - now.getTime();
  const days = Math.round(diffMs / 86_400_000);
  if (days === 0) return t('due.today');
  if (days > 0) return days === 1 ? t('due.tomorrow') : tn('due.in_days', days);
  const ago = Math.abs(days);
  return ago === 1 ? t('due.yesterday') : tn('due.days_ago', ago);
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

/** Resolve a device to its integration domain via the config-entry → domain map. */
export function deviceDomain(
  device: { primary_config_entry?: string | null; config_entries?: string[] } | undefined,
  entryDomains: Record<string, string> | undefined,
): string | undefined {
  if (!device || !entryDomains) return undefined;
  const entryId = device.primary_config_entry || device.config_entries?.[0];
  return entryId ? entryDomains[entryId] : undefined;
}

/**
 * Brand logo URL for an integration domain. The `_/` fallback path serves a
 * generic logo when the integration ships no brand image of its own.
 */
export function brandLogoUrl(domain: string, fallback = false): string {
  return `https://brands.home-assistant.io/${fallback ? '_/' : ''}${domain}/icon.png`;
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
  const bits: string[] = [];
  const makeModel = [asset.manufacturer, asset.model].filter(Boolean).join(' ');
  if (makeModel) bits.push(makeModel);
  const area = areaName(areas, asset.area_id);
  if (area) bits.push(area);
  if (asset.warranty_expiry) {
    bits.push(t('asset.warrantyTo', { date: asset.warranty_expiry }));
  }
  const partCount = asset.parts?.length ?? 0;
  if (partCount) bits.push(tn('asset.parts', partCount));
  return bits.length ? bits.join(' · ') : t('asset.noDetails');
}
