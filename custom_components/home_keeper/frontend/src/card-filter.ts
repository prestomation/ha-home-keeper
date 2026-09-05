import { t } from './i18n';
import type { HassArea, HassDevice, RecurrenceType, Task } from './types';
import { areaName, deviceName, groupableDeviceId, isBuyTask } from './utils';

/**
 * Pure (DOM-free) filtering / sorting / grouping for the dashboard card. Kept
 * separate from the custom element so the list-shaping logic — the part with
 * the interesting edge cases — is unit-testable in node without a DOM.
 */

export type CardFilter = 'all' | 'overdue' | 'soon' | 'today' | 'no_due' | 'shopping';
export type CardSort = 'due' | 'name' | 'recent' | 'area';
export type CardGroupBy = 'none' | 'status' | 'area' | 'device';
export type StatusBucket =
  | 'overdue'
  | 'shopping'
  | 'soon'
  | 'today'
  | 'later'
  | 'monitored'
  | 'completed'
  | 'none';

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
  /** Show only tasks matching this saved **profile** (id or name). When set, the
   *  profile's filter (status + labels/areas/devices) decides which tasks show; the
   *  card's own labels/areas/devices/filter fields are ignored. See profileMatches. */
  profile?: string;
  /** Restrict to tasks carrying these HA labels — on the task itself, its device,
   *  or its effective area. The backbone of per-subject cards (one per dog/car/kid). */
  labels?: string[];
  /** When several labels are configured: match a task carrying ANY of them
   *  (default) or only one carrying ALL of them. */
  label_match?: 'any' | 'all';
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
  /** Show the task's own label chips. Default false. */
  show_labels?: boolean;
  /** Ask for confirmation before completing a task. Default false. */
  confirm_complete?: boolean;
  /** Hide the entire card (header included) instead of showing "No tasks match
   *  this filter." when nothing matches. Default false. Handy for a dashboard
   *  built from several per-subject cards where only the ones with something due
   *  should show. */
  hide_when_empty?: boolean;
}

/**
 * Whether *task* is one of Home Keeper's auto-created "Buy {part}" reminders.
 *
 * Defined in `utils.ts`, beside `isOverdue` and the `statusChipHtml` that reads both,
 * and re-exported here so the pure list-shaping code keeps importing it from one
 * place. See that definition for why both ids are required.
 */
export { isBuyTask };

/** Tasks due within this many days (and not overdue) count as "due soon". */
export const SOON_DAYS = 7;

/**
 * A saved Profile's `due_soon` window, in days. This deliberately differs from the
 * card's 7-day `soon` status bucket: it mirrors the backend `transitions.DUE_SOON_WINDOW`
 * (3 days) so a Profile with `status: due_soon` selects the SAME tasks here as a
 * notification using that Profile does server-side. Keep the two in lockstep.
 */
export const DUE_SOON_DAYS = 3;

/** One day in milliseconds — the unit every "due in N days" window is counted in. */
export const DAY_MS = 86_400_000;

/** End of the local calendar day containing `now` (23:59:59.999). */
function endOfToday(now: number): number {
  const d = new Date(now);
  d.setHours(23, 59, 59, 999);
  return d.getTime();
}

/**
 * The two sections the card and the panel disagree about. Everything else —
 * overdue / soon / later / monitored / none, and the NaN guard for a malformed due
 * date — is common to both surfaces; these two are the per-surface product decision,
 * and the defaults are the card's.
 */
export interface StatusBucketOptions {
  /** Give a task due before midnight its own `today` section, between overdue and
   *  soon. The card does; the panel folds it into `soon`. Default true. */
  today?: boolean;
  /** Give a completed one-off (do-once, now dormant) its own `completed` section
   *  rather than the generic `none`. The panel does; the card doesn't. Default false. */
  completed?: boolean;
}

/** Which status section a task belongs to. See `StatusBucketOptions` for the two
 *  sections that are a per-surface choice. */
export function statusBucket(
  task: Task,
  now = Date.now(),
  opts: StatusBucketOptions = {},
): StatusBucket {
  const { today = true, completed = false } = opts;
  // A dormant triggered/sensor task is "monitored" — armed-but-not-due. An armed one
  // (next_due set) flows through the normal overdue/soon/later logic below.
  if (
    (task.recurrence_type === 'triggered' || task.recurrence_type === 'sensor') &&
    !task.next_due
  )
    return 'monitored';
  if (completed && task.recurrence_type === 'one-off' && !task.next_due && task.last_completed)
    return 'completed';
  if (!task.next_due) return 'none';
  const due = new Date(task.next_due).getTime();
  if (Number.isNaN(due)) return 'none';
  // An auto-created buy reminder gets its own section rather than joining the
  // overdue pile. It is minted as a one-off with no due date, and a dateless
  // one-off is due *now*, so it reads as overdue from the moment a part goes low
  // — sitting beside genuinely late maintenance while nothing is actually late.
  // Only the sections move: it still counts as overdue for the filter pills, the
  // per-task binary sensors and any Profile, so no surface contradicts another.
  // Below the `completed` check so a reminder that was bought still lands there.
  if (isBuyTask(task)) return 'shopping';
  if (due <= now) return 'overdue';
  if (today && due <= endOfToday(now)) return 'today';
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

/**
 * Every HA label that scopes a task: its own labels, plus those on its attached
 * device and its effective area. This union is what makes a "label = dog" card
 * pick up both a task tagged `dog` directly and a task on a device labelled `dog`
 * (a Home Keeper virtual-asset device can be labelled in Settings → Devices like
 * any other), so a subject doesn't have to map onto an HA area or device.
 */
export function taskLabelIds(
  task: Task,
  devices?: Record<string, HassDevice>,
  areas?: Record<string, HassArea>,
): Set<string> {
  const ids = new Set<string>(task.labels ?? []);
  const dev = task.device_id ? devices?.[task.device_id] : undefined;
  for (const id of dev?.labels ?? []) ids.add(id);
  const areaId = taskAreaId(task, devices);
  const area = areaId ? areas?.[areaId] : undefined;
  for (const id of area?.labels ?? []) ids.add(id);
  return ids;
}

/** A saved profile's filter (mirrors the backend `profiles.py` shape). */
export interface ProfileFilter {
  status: 'all' | 'overdue' | 'due_soon';
  labels: string[];
  areas: string[];
  devices: string[];
  /** Integration domains from a task's `managed_by.integration` — the companion that
   *  owns it. Scopes a profile to one source ("just the battery tasks") without every
   *  companion having to learn to apply a label. */
  companions?: string[];
  /** Ids that disqualify a task even when it cleared every include list above.
   *  Empty (or absent, on a profile saved before these existed) excludes nothing. */
  exclude_labels?: string[];
  exclude_areas?: string[];
  exclude_devices?: string[];
  exclude_companions?: string[];
  /** Drop the auto-created "Buy {part}" reminders. Excludes by *kind*, not by id:
   *  a buy reminder has no label or area of its own to name. Absent means off. */
  exclude_shopping?: boolean;
}

/**
 * Whether a configured id list names `id`. A task with no area or no device has no id
 * to name, so it matches no list — which is what keeps a non-empty exclude list from
 * sweeping up every unattached task. An absent list names nothing.
 */
function listHas(list: string[] | undefined, id: string | null | undefined): boolean {
  // Stryker disable next-line ConditionalExpression: equivalent — this guard narrows
  // `id` to a string for `includes`; a list of real ids can never contain null,
  // undefined or '', so falling through would return false for those anyway.
  if (!id) return false;
  return list?.includes(id) ?? false;
}

/**
 * Whether *task* matches a saved profile's *filter*. Mirrors the backend
 * `profiles.matches_filter` so a Profile selects the same tasks here (card / admin
 * list) as a notification using it does server-side: the same 3-day `due_soon` window
 * (`DUE_SOON_DAYS` ↔ `transitions.DUE_SOON_WINDOW`) and the same **effective**
 * label/area resolution — own ids plus those inherited via the task's device and area.
 * The backend reaches parity by enriching tasks with their effective ids before
 * matching (`notifier.effective_filter_tasks`); here we resolve them inline via
 * `taskLabelIds`/`taskAreaId`.
 *
 * The `exclude_*` lists subtract after the include lists and win over them, so
 * "everything except the jobs that need a tradesperson" is one profile rather than a
 * label on every task that isn't one. They read the same effective ids, so excluding a
 * label also drops a task that only inherits it from its device or area.
 * `exclude_shopping` subtracts beside them but by *kind*, dropping the auto-created
 * buy reminders — they carry no id of their own, only the appliance's.
 *
 * `companions` scopes by the integration that owns a task (`managed_by.integration`),
 * which is how "a card of just the battery tasks" stays one saved profile instead of a
 * setting each companion has to grow.
 *
 * A `problem`-sensor-synced task is an ordinary member of the set. It carries a
 * `next_due` of the moment its sensor went bad while the problem stands, so it reads as
 * overdue, and drops back to `next_due: null` (excluded below) once the sensor clears.
 * Dropping the armed ones outright hid every synced problem from every Profile, under
 * every status (#248). Walk notifications still leave them out, but that is a delivery
 * rule in `notifications.is_walkable`, not part of the filter.
 */
export function profileMatches(
  task: Task,
  filter: ProfileFilter,
  devices?: Record<string, HassDevice>,
  areas?: Record<string, HassArea>,
  now = Date.now(),
): boolean {
  if (task.enabled === false) return false;
  if (!task.next_due) return false;
  // Status windows match the backend exactly: overdue = due at/before now; due_soon =
  // overdue or due within DUE_SOON_DAYS; all = any dated, enabled task.
  const due = new Date(task.next_due).getTime();
  const status = filter.status || 'overdue';
  if (status === 'overdue' && due > now) return false;
  if (status === 'due_soon' && due > now + DUE_SOON_DAYS * DAY_MS) return false;
  const taskLabels = taskLabelIds(task, devices, areas);
  const areaId = taskAreaId(task, devices);
  const labels = filter.labels ?? [];
  if (labels.length && !labels.some((id) => taskLabels.has(id))) return false;
  const wantAreas = filter.areas ?? [];
  if (wantAreas.length && !listHas(wantAreas, areaId)) return false;
  const wantDevices = filter.devices ?? [];
  if (wantDevices.length && !listHas(wantDevices, task.device_id)) return false;
  // The owning integration, from the `managed_by` block a companion sets on
  // `add_task`. A task nobody claims has none, so `listHas` rejects it from a
  // non-empty include list and spares it from every exclude list.
  const companion = task.managed_by?.integration;
  const wantCompanions = filter.companions ?? [];
  if (wantCompanions.length && !listHas(wantCompanions, companion)) return false;
  // Exclusions subtract, and win over the include lists above.
  if (filter.exclude_labels?.some((id) => taskLabels.has(id))) return false;
  if (listHas(filter.exclude_areas, areaId)) return false;
  if (listHas(filter.exclude_devices, task.device_id)) return false;
  // By kind rather than by id — a buy reminder has none of its own to name.
  if (filter.exclude_shopping && isBuyTask(task)) return false;
  return !listHas(filter.exclude_companions, companion);
}

function matchesLabels(
  taskLabels: Set<string>,
  wanted: Set<string>,
  mode: 'any' | 'all',
): boolean {
  if (mode === 'all') {
    for (const id of wanted) if (!taskLabels.has(id)) return false;
    return true;
  }
  for (const id of wanted) if (taskLabels.has(id)) return true;
  return false;
}

function matchesFilter(task: Task, filter: CardFilter, now: number): boolean {
  const due = task.next_due ? new Date(task.next_due).getTime() : NaN;
  const dated = !Number.isNaN(due);
  switch (filter) {
    case 'overdue':
      // Late work only. A buy reminder is overdue by the clock — dateless one-off,
      // therefore due now — but `filter: shopping` is how a card asks for those, and a
      // card set to `overdue` with `group_by: status` otherwise drew a Shopping section
      // under an Overdue filter. Matches the panel's own Overdue pill: the two describe
      // one idea and must not disagree about which tasks it holds.
      return dated && due <= now && !isBuyTask(task);
    case 'soon':
      return statusBucket(task, now) === 'soon';
    case 'today':
      // Everything actionable today: overdue plus anything due before midnight.
      return dated && due <= endOfToday(now);
    case 'no_due':
      return !dated;
    case 'shopping':
      return isBuyTask(task);
    case 'all':
    default:
      return true;
  }
}

/**
 * Apply every configured filter, returning the surviving tasks (unsorted).
 *
 * `areas` is the HA area registry (passed last to stay backward-compatible with
 * existing positional callers); it's only needed so a label filter can match a
 * task via the labels on its effective area.
 */
export function filterTasks(
  tasks: Task[],
  config: HomeKeeperCardConfig,
  devices?: Record<string, HassDevice>,
  now = Date.now(),
  areas?: Record<string, HassArea>,
): Task[] {
  const areaSet = config.areas?.length ? new Set(config.areas) : null;
  const devSet = config.devices?.length ? new Set(config.devices) : null;
  const labelSet = config.labels?.length ? new Set(config.labels) : null;
  const labelMode = config.label_match === 'all' ? 'all' : 'any';
  const recTypes = config.recurrence_types?.length ? new Set(config.recurrence_types) : null;
  const filter = config.filter ?? 'all';
  const horizon = Math.max(0, Number(config.horizon_days) || 0);
  // The horizon is an "upcoming dated window"; it's meaningless for the
  // explicitly-undated `no_due` filter, so skip it there (else the list is
  // always empty — undated tasks have no date to fall within the window).
  const horizonCutoff = horizon > 0 && filter !== 'no_due' && filter !== 'shopping' ? now + horizon * DAY_MS : 0;

  return tasks.filter((task) => {
    if (!config.show_disabled && task.enabled === false) return false;
    if (config.hide_managed && task.managed_by) return false;
    if (areaSet && !areaSet.has(taskAreaId(task, devices) ?? '')) return false;
    if (devSet && !devSet.has(task.device_id ?? '')) return false;
    if (labelSet && !matchesLabels(taskLabelIds(task, devices, areas), labelSet, labelMode))
      return false;
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

/** One bucket of rows rendered under a collapsible section header. Defaults to a
 *  group of tasks — the panel groups appliances with the same primitive. */
export interface Group<T = Task> {
  /** Stable key for remembering collapse state, e.g. "status:overdue". */
  key: string;
  /** Section header text; empty string renders the rows ungrouped. */
  label: string;
  items: T[];
}

const STATUS_ORDER: { bucket: StatusBucket; labelKey: string }[] = [
  { bucket: 'overdue', labelKey: 'chip.overdue' },
  { bucket: 'shopping', labelKey: 'filter.shopping' },
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
      // A device with no name to head a section with — gone from the registry, or
      // present but nameless — sends its tasks to "No device" rather than under a bare
      // id or an empty heading.
      (task) => groupableDeviceId(devices, task.device_id),
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

/**
 * Bucket items by a key, label each section, sort sections alphabetically and sink
 * the "no key" fallback bucket to the bottom. Keys are namespaced by *prefix* so
 * collapse state never collides between grouping modes. Generic over the item type:
 * the card groups tasks, the panel also groups appliances.
 */
export function bucketByKey<T>(
  items: T[],
  keyOf: (item: T) => string | undefined,
  labelOf: (key: string) => string,
  fallbackLabel: string,
  prefix: string,
): Group<T>[] {
  const buckets = new Map<string, T[]>();
  for (const item of items) {
    const k = keyOf(item) || '';
    const arr = buckets.get(k);
    if (arr) arr.push(item);
    else buckets.set(k, [item]);
  }
  const fallbackKey = `${prefix}:none`;
  const groups: Group<T>[] = [];
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
