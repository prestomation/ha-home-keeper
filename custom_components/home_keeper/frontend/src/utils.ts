import { t, tn } from './i18n';
import type { Asset, HassArea, HassLabel, Task } from './types';

/** Escape user-provided text before injecting into innerHTML. */
export function escapeHTML(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * A random UUID-v4 string for client-minted ids (document ids, working-copy entries).
 *
 * `crypto.randomUUID()` only exists in a **secure context** — HTTPS or `localhost`. Over
 * a plain-HTTP LAN address (e.g. `http://192.168.1.x:8123`) it is `undefined`, so calling
 * it directly throws and silently breaks file uploads / link-adds for users on their LAN.
 * Prefer it when present, otherwise build a v4 from `crypto.getRandomValues` (always
 * available), falling back to `Math.random` only if even that is missing.
 */
export function randomId(): string {
  const c: Crypto | undefined = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c?.getRandomValues) c.getRandomValues(bytes);
  else for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // RFC 4122 variant
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'));
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex
    .slice(6, 8)
    .join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`;
}

/** True when a triggered task is currently armed (due-now) vs dormant. */
export function isArmedTriggered(task: Task): boolean {
  return task.recurrence_type === 'triggered' && !!task.next_due;
}

/** Human-readable summary of a task's recurrence rule. */
export function recurrenceSummary(task: Task): string {
  // A triggered task has no schedule — it is "monitored" and only due when its
  // owning integration arms it (e.g. Battery Notes when a battery goes low).
  if (task.recurrence_type === 'triggered') return t('recurrence.triggered');
  // A one-off (do-once) task has no cadence — just a single due date.
  if (task.recurrence_type === 'one-off') return t('recurrence.oneOff');
  // A sensor task is described by its bound numeric condition, not a clock.
  if (task.recurrence_type === 'sensor') {
    const s = task.sensor;
    if (!s) return t('recurrence.sensor');
    if (s.mode === 'threshold') {
      return t('recurrence.sensorThreshold', {
        comparison: s.comparison ?? '',
        value: s.value ?? '',
      });
    }
    return t('recurrence.sensorUsage', { target: s.target ?? '' });
  }
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
  // A dormant triggered/sensor task is armed-but-not-due: show "Monitored", not "no
  // date" — Home Keeper is watching the condition / sensor and will arm it.
  if (
    (task.recurrence_type === 'triggered' || task.recurrence_type === 'sensor') &&
    !task.next_due
  ) {
    return t('due.monitored');
  }
  // A completed one-off (do-once, now dormant) reads as "Completed".
  if (task.recurrence_type === 'one-off' && !task.next_due && task.last_completed) {
    return t('due.completed');
  }
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

/** Resolve a label id to its display name using hass.labels (falls back to the id). */
export function labelName(
  labels: Record<string, HassLabel> | undefined,
  labelId: string | null | undefined,
): string {
  if (!labelId) return '';
  return labels?.[labelId]?.name || labelId;
}

// ── panel routing ────────────────────────────────────────────────────────────

/** The navigable list view; mirrors the panel's two tabs. */
export type PanelView = 'tasks' | 'appliances' | 'settings';

/**
 * A fully-resolved panel location: which tab is shown and, optionally, the
 * detail page open on top of it. This is the panel's entire navigation state —
 * it round-trips losslessly with the URL via {@link parseRoute} / {@link buildPath}
 * so the URL can be the single source of truth (high-fidelity deep linking).
 */
export interface PanelLocation {
  view: PanelView;
  detail: { kind: 'task' | 'asset'; id: string } | null;
}

/**
 * Parse the panel's route path (the part after the `/home-keeper` prefix that HA
 * hands the panel) into a {@link PanelLocation}. Unknown/empty paths fall back to
 * the tasks list. The asset detail lives under the `appliances` segment but keeps
 * the internal `asset` kind.
 */
export function parseRoute(path: string | undefined | null): PanelLocation {
  const parts = String(path ?? '')
    .split('/')
    .map((p) => p.trim())
    .filter(Boolean);
  const view: PanelView =
    parts[0] === 'appliances' ? 'appliances' : parts[0] === 'settings' ? 'settings' : 'tasks';
  // Only the tasks/appliances lists drill into a detail page; settings has none.
  if (parts[1] && view !== 'settings') {
    const kind = view === 'appliances' ? 'asset' : 'task';
    return { view, detail: { kind, id: decodeURIComponent(parts[1]) } };
  }
  return { view, detail: null };
}

/**
 * Build the route path (under the panel prefix) for a {@link PanelLocation} —
 * the inverse of {@link parseRoute}. The detail page's URL segment derives from
 * the view, so a task detail is `/tasks/<id>` and an asset detail is
 * `/appliances/<id>`.
 */
export function buildPath(loc: PanelLocation): string {
  if (loc.detail) return `/${loc.view}/${encodeURIComponent(loc.detail.id)}`;
  return `/${loc.view}`;
}

// ── completion history ───────────────────────────────────────────────────────

/** Parsed, valid completion timestamps sorted newest-first. */
export function sortedCompletions(completions?: { ts: string }[]): Date[] {
  return (completions || [])
    .map((c) => new Date(c.ts))
    .filter((d) => !Number.isNaN(d.getTime()))
    .sort((a, b) => b.getTime() - a.getTime());
}

export interface CompletionStats {
  count: number;
  last?: Date;
  /** Mean days between completions (only when there are at least two). */
  avgIntervalDays?: number;
}

/** Count, most-recent completion, and average cadence for a completion list. */
export function completionStats(completions?: { ts: string }[]): CompletionStats {
  const dates = sortedCompletions(completions);
  const stats: CompletionStats = { count: dates.length };
  if (dates.length) stats.last = dates[0];
  if (dates.length >= 2) {
    const spanMs = dates[0].getTime() - dates[dates.length - 1].getTime();
    stats.avgIntervalDays = Math.round(spanMs / (dates.length - 1) / 86_400_000);
  }
  return stats;
}

/**
 * True when a task is associated with an appliance — mirrors the backend's
 * `assets.task_relates_to_asset` so the panel can group history client-side.
 */
export function taskRelatesToAsset(task: Task, asset: Asset): boolean {
  if (task.source?.part?.asset_id === asset.id) return true;
  const dev = task.device_id;
  if (!dev) return false;
  if (asset.device_id && dev === asset.device_id) return true;
  return (asset.related_device_ids || []).includes(dev);
}

/** Every loaded task associated with an appliance. */
export function tasksForAsset(asset: Asset, tasks: Task[]): Task[] {
  return tasks.filter((task) => taskRelatesToAsset(task, asset));
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
  const partCount = asset.parts?.length ?? 0;
  if (partCount) bits.push(tn('asset.parts', partCount));
  return bits.length ? bits.join(' · ') : t('asset.noDetails');
}
