import { t } from './i18n';
import type { HassArea, HassDevice, RecurrenceType, Task } from './types';
import { areaName, deviceName } from './utils';

/**
 * Pure (DOM-free) filtering / sorting / grouping for the dashboard card. Kept
 * separate from the custom element so the list-shaping logic — the part with
 * the interesting edge cases — is unit-testable in node without a DOM.
 */

export type CardFilter = 'all' | 'overdue' | 'soon' | 'today' | 'no_due';
export type CardSort = 'due' | 'name' | 'recent' | 'area';
export type CardGroupBy = 'none' | 'status' | 'area' | 'device';
export type StatusBucket = 'overdue' | 'soon' | 'today' | 'later' | 'monitored' | 'none';

/** Lovelace config for `custom:home-keeper-card`. */
export interface HomeKeeperCardConfig {
  type: string;
  /** Card header; omit or set to '' to hide the header entirely. */
  title?: string;
  /** Which tasks to show by due status. Default 'all'. */
  filter?: CardFilter;
  /** Row order. Default 'due'. */
  sort?: CardSort;
  /** Collapsible section grouping. Default 'none'. */
  group_by?: CardGroupBy;
  /** Restrict to these areas (a task's own area, else its device's area). */
  areas?: string[];
  /** Restrict to tasks attached to these devices. */
  devices?: string[];
  /** Restrict to these recurrence types. */
  recurrence_types?: RecurrenceType[];
  /** Only show dated tasks due within this many days (0 = no limit). */
  horizon_days?: number;
  /** Cap the number of rows shown (0 = unlimited). */
  max_items?: number;
  /** Hide tasks owned by another integration (managed_by). */
  hide_managed?: boolean;
  /** Include tasks that are disabled (enabled === false). Default false. */
  show_disabled?: boolean;
  /** Show the "+ Add task" affordance in the header. Default true. */
  show_add?: boolean;
  /** Show each task's notes under its name. Default false. */
  show_notes?: boolean;
  /** Show the task's area/device chip. Default true. */
  show_area?: boolean;
  /** Ask for confirmation before completing a task. Default false. */
  confirm_complete?: boolean;
}

/** Tasks due within this many days (and not overdue) count as "due soon". */
export const SOON_DAYS = 7;
const DAY_MS = 86_400_000;

/** End of the local calendar day containing `now` (23:59:59.999). */
function endOfToday(now: number): number {
  const d = new Date(now);
  d.setHours(23, 59, 59, 999);
  return d.getTime();
}

/** Which status section a task belongs to (mirrors the panel's bucketing). */
export function statusBucket(task: Task, now = Date.now()): StatusBucket {
  // A dormant triggered task is "monitored" — armed-but-not-due.
  if (task.recurrence_type === 'triggered' && !task.next_due) return 'monitored';
  if (!task.next_due) return 'none';
  const due = new Date(task.next_due).getTime();
  if (Number.isNaN(due)) return 'none';
  if (due <= now) return 'overdue';
  if (due <= endOfToday(now)) return 'today';
  if (due - now <= SOON_DAYS * DAY_MS) return 'soon';
  return 'later';
}

/** A task's effective area: its own, else its attached device's. */
export function taskAreaId(
  task: Task,
  devices?: Record<string, HassDevice>,
): string | undefined {
  if (task.area_id) return task.area_id;
  const dev = task.device_id ? devices?.[task.device_id] : undefined;
  return dev?.area_id ?? undefined;
}

function matchesFilter(task: Task, filter: CardFilter, now: number): boolean {
  const due = task.next_due ? new Date(task.next_due).getTime() : NaN;
  const dated = !Number.isNaN(due);
  switch (filter) {
    case 'overdue':
      return dated && due <= now;
    case 'soon':
      return statusBucket(task, now) === 'soon';
    case 'today':
      // Everything actionable today: overdue plus anything due before midnight.
      return dated && due <= endOfToday(now);
    case 'no_due':
      return !dated;
    case 'all':
    default:
      return true;
  }
}

/** Apply every configured filter, returning the surviving tasks (unsorted). */
export function filterTasks(
  tasks: Task[],
  config: HomeKeeperCardConfig,
  devices?: Record<string, HassDevice>,
  now = Date.now(),
): Task[] {
  const areas = config.areas?.length ? new Set(config.areas) : null;
  const devSet = config.devices?.length ? new Set(config.devices) : null;
  const recTypes = config.recurrence_types?.length ? new Set(config.recurrence_types) : null;
  const filter = config.filter ?? 'all';
  const horizon = Math.max(0, Number(config.horizon_days) || 0);
  const horizonCutoff = horizon > 0 ? now + horizon * DAY_MS : 0;

  return tasks.filter((task) => {
    if (!config.show_disabled && task.enabled === false) return false;
    if (config.hide_managed && task.managed_by) return false;
    if (areas && !areas.has(taskAreaId(task, devices) ?? '')) return false;
    if (devSet && !devSet.has(task.device_id ?? '')) return false;
    if (recTypes && !recTypes.has(task.recurrence_type)) return false;
    if (!matchesFilter(task, filter, now)) return false;
    if (horizonCutoff) {
      // Window view: keep overdue + anything due within the horizon; drop undated.
      const due = task.next_due ? new Date(task.next_due).getTime() : NaN;
      if (Number.isNaN(due) || due > horizonCutoff) return false;
    }
    return true;
  });
}

/** Sort a copy of `tasks` by the configured order. */
export function sortTasks(
  tasks: Task[],
  sort: CardSort = 'due',
  areas?: Record<string, HassArea>,
  devices?: Record<string, HassDevice>,
): Task[] {
  const copy = [...tasks];
  const dueOf = (task: Task): number =>
    task.next_due ? new Date(task.next_due).getTime() || Infinity : Infinity;
  const lastOf = (task: Task): number =>
    task.last_completed ? new Date(task.last_completed).getTime() || 0 : 0;
  switch (sort) {
    case 'name':
      copy.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
      break;
    case 'recent':
      // Most recently completed first; never-completed sink to the bottom.
      copy.sort((a, b) => lastOf(b) - lastOf(a) || dueOf(a) - dueOf(b));
      break;
    case 'area':
      copy.sort((a, b) => {
        const an = areaName(areas, taskAreaId(a, devices));
        const bn = areaName(areas, taskAreaId(b, devices));
        return an.localeCompare(bn) || dueOf(a) - dueOf(b);
      });
      break;
    case 'due':
    default:
      copy.sort((a, b) => dueOf(a) - dueOf(b));
  }
  return copy;
}

export interface Group {
  /** Stable key for remembering collapse state, e.g. "status:overdue". */
  key: string;
  /** Section header text. */
  label: string;
  items: Task[];
}

const STATUS_ORDER: { bucket: StatusBucket; labelKey: string }[] = [
  { bucket: 'overdue', labelKey: 'chip.overdue' },
  { bucket: 'today', labelKey: 'due.today' },
  { bucket: 'soon', labelKey: 'filter.soon' },
  { bucket: 'later', labelKey: 'section.later' },
  { bucket: 'monitored', labelKey: 'section.monitored' },
  { bucket: 'none', labelKey: 'section.noSchedule' },
];

/**
 * Bucket the (already sorted) tasks into labelled sections. `none` returns a
 * single unlabelled group so the caller can render rows flat.
 */
export function groupTasks(
  tasks: Task[],
  groupBy: CardGroupBy = 'none',
  areas?: Record<string, HassArea>,
  devices?: Record<string, HassDevice>,
  now = Date.now(),
): Group[] {
  if (groupBy === 'status') {
    return STATUS_ORDER.map(({ bucket, labelKey }) => ({
      key: `status:${bucket}`,
      label: bucket === 'today' ? capitalize(t(labelKey)) : t(labelKey),
      items: tasks.filter((task) => statusBucket(task, now) === bucket),
    })).filter((g) => g.items.length);
  }
  if (groupBy === 'area') {
    return bucketByKey(
      tasks,
      (task) => taskAreaId(task, devices),
      (id) => areaName(areas, id),
      t('section.unassigned'),
      'area',
    );
  }
  if (groupBy === 'device') {
    return bucketByKey(
      tasks,
      (task) => task.device_id ?? undefined,
      (id) => deviceName(devices, id),
      t('section.noDevice'),
      'device',
    );
  }
  return [{ key: '', label: '', items: tasks }];
}

function capitalize(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function bucketByKey(
  items: Task[],
  keyOf: (task: Task) => string | undefined,
  labelOf: (key: string) => string,
  fallbackLabel: string,
  prefix: string,
): Group[] {
  const buckets = new Map<string, Task[]>();
  for (const item of items) {
    const k = keyOf(item) || '';
    const arr = buckets.get(k);
    if (arr) arr.push(item);
    else buckets.set(k, [item]);
  }
  const fallbackKey = `${prefix}:none`;
  const groups: Group[] = [];
  for (const [k, arr] of buckets) {
    groups.push({
      key: k ? `${prefix}:${k}` : fallbackKey,
      label: k ? labelOf(k) : fallbackLabel,
      items: arr,
    });
  }
  // Alphabetical sections, with the "no key" fallback sunk to the bottom.
  groups.sort((a, b) => {
    const af = a.key === fallbackKey;
    const bf = b.key === fallbackKey;
    if (af !== bf) return af ? 1 : -1;
    return a.label.localeCompare(b.label);
  });
  return groups;
}
