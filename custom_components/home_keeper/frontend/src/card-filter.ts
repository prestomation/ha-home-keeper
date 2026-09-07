import { t } from './i18n';
import type { Asset, HassArea, HassDevice, RecurrenceType, Task } from './types';
import { areaName, deviceName, groupableDeviceId, isBuyTask } from './utils';

/**
 * Pure (DOM-free) filtering / sorting / grouping for the dashboard card, and the
 * parts of it the panel shares — `statusBucket`, `bucketByKey`, `profileMatches`,
 * and the text filter both lists search with. Kept separate from the custom
 * elements so the list-shaping logic — the part with the interesting edge cases —
 * is unit-testable in node without a DOM.
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
  /** Show only tasks matching this saved **profile** (id or name). When set, the
   *  profile's own filter decides which tasks show; the card's `groups` and its
   *  `filter` field are ignored. See profileMatches. */
  profile?: string;
  /** The card's own selection, as an OR of **filter groups** — the same rule a
   *  profile applies, read by the same `groupMatches`. Each group is an AND of the
   *  include lists it carries, minus its own exclusions, so one card can say "the
   *  dog's jobs OR anything in the garage". A group that constrains nothing is
   *  dropped rather than widening the card back to everything (`groupActive`), and a
   *  card with no active group filters by status and horizon alone. Ignored when
   *  `profile` is set. */
  groups?: Partial<FilterGroup>[];
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
 * A card config as a dashboard may still hold it: the flat `labels`/`areas`/`devices`
 * fields the card selected with before filter groups existed.
 *
 * The only input `liftLegacyCardConfig` takes, and the only place these four keys are
 * named. Everything downstream — `filterTasks`, the card, its editor — reads `groups`
 * and has no idea the old spelling ever existed.
 */
export type LegacyCardConfig = HomeKeeperCardConfig & {
  labels?: string[];
  label_match?: 'any' | 'all';
  areas?: string[];
  devices?: string[];
};

/**
 * Rewrite a stored card config in the current spelling: the legacy `labels`/
 * `label_match`/`areas`/`devices` fields become one filter group.
 *
 * One group, not three: the old fields were ANDed with each other (a task had to be in
 * an allowed area *and* on an allowed device), and that is exactly what one group
 * means, so the lift preserves which tasks the card selects.
 *
 * Silent by design — no notice, no "your card was migrated" alert. The lift is
 * idempotent, a config that already carries `groups` keeps them, and the four keys are
 * dropped either way so nothing downstream has to keep reading both spellings.
 *
 * The input is never mutated: a Lovelace config object is shared with the dashboard
 * that owns it.
 */
export function liftLegacyCardConfig(config: LegacyCardConfig): HomeKeeperCardConfig {
  const { labels = [], label_match, areas = [], devices = [], ...rest } = config;
  // A config that already speaks groups is already current; the four keys still go.
  if (Array.isArray(config.groups)) return rest;
  if (!labels.length && !areas.length && !devices.length) return rest;
  return {
    ...rest,
    groups: [
      {
        ...emptyGroup(),
        labels: [...labels],
        labels_match: label_match === 'all' ? 'all' : 'any',
        areas: [...areas],
        devices: [...devices],
      },
    ],
  };
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

/**
 * One **group** of a saved filter: a single "these AND these, minus those" rule.
 *
 * Every include list that carries a value must be satisfied, and no exclude list may
 * hit — so a group is an AND of its own fields. A profile holds a list of them and
 * ORs the results, which is what lets one profile say "the dog's jobs OR anything
 * overdue in the garage" without two profiles and two notifications.
 *
 * Every key is required. A group is built by `emptyGroup` or normalized by
 * `forms.toFilterGroup`, so nothing downstream has to re-decide what an absent key
 * means; the matchers still read a `Partial` tolerantly, because a group also arrives
 * straight off a stored profile.
 */
export interface FilterGroup {
  labels: string[];
  /** Whether a task needs ANY of `labels` (the default) or ALL of them. Per group:
   *  "all" is how one group says "the dog's *outdoor* jobs" with two labels. */
  labels_match: 'any' | 'all';
  areas: string[];
  devices: string[];
  /** Integration domains from a task's `managed_by.integration` — the companion that
   *  owns it. Scopes a group to one source ("just the battery tasks") without every
   *  companion having to learn to apply a label. */
  companions: string[];
  /** Ids that disqualify a task even when it cleared every include list above.
   *  Empty excludes nothing. Scoped to this group: an exclusion in one group never
   *  touches what another group selects. */
  exclude_labels: string[];
  exclude_areas: string[];
  exclude_devices: string[];
  exclude_companions: string[];
  /** Drop the auto-created "Buy {part}" reminders. Excludes by *kind*, not by id:
   *  a buy reminder has no label or area of its own to name. */
  exclude_shopping: boolean;
}

/**
 * A saved profile's filter (mirrors the backend `profiles.py` shape): one status
 * window for the whole profile, then the groups it ORs together.
 *
 * Both keys are optional so a filter read straight off a stored profile can be passed
 * in as it stands. There are no top-level `labels`/`areas`/`devices` keys and nothing
 * reads them: a filter's selection lives entirely in its `groups`.
 */
export interface ProfileFilter {
  status?: 'all' | 'overdue' | 'due_soon';
  groups?: Partial<FilterGroup>[];
}

/** The eight id lists a group can carry, in the order the editor shows them. */
const GROUP_LISTS = [
  'labels',
  'areas',
  'devices',
  'companions',
  'exclude_labels',
  'exclude_areas',
  'exclude_devices',
  'exclude_companions',
] as const;

/** A group with nothing set — what the editor seeds a new group with, and what a
 *  profile with no groups at all is rebuilt around. It selects everything, so a
 *  profile is never accidentally emptied by adding a group to it. */
export function emptyGroup(): FilterGroup {
  return {
    labels: [],
    labels_match: 'any',
    areas: [],
    devices: [],
    companions: [],
    exclude_labels: [],
    exclude_areas: [],
    exclude_devices: [],
    exclude_companions: [],
    exclude_shopping: false,
  };
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
 * Whether *group* constrains anything at all.
 *
 * An untouched group — the one every new profile starts with — selects every task, so
 * ORing it with a real group would quietly widen the profile to everything. Inactive
 * groups are dropped before the OR instead, which is what lets the editor always show
 * a group to fill in without that empty row changing what the profile selects.
 *
 * `exclude_shopping` counts: a group that only drops the buy reminders is a real rule.
 * `labels_match` does not — it says how to read `labels`, and on its own says nothing.
 */
export function groupActive(group: Partial<FilterGroup>): boolean {
  if (group.exclude_shopping) return true;
  return GROUP_LISTS.some((key) => Boolean(group[key]?.length));
}

/**
 * Whether *task* satisfies one group: every include list that carries a value, and no
 * exclude list hit.
 *
 * Resolves the task's **effective** labels and area itself (own ids plus those
 * inherited via its device and area) so every caller — `profileMatches` here, the
 * card's own `filterTasks` — asks the question the same way, off the same registries.
 *
 * An empty include list means "no constraint", not "match nothing": that is what makes
 * a group of only exclusions ("everything except the call-outs") a group. An empty
 * exclude list excludes nothing, so a group saved with none behaves as it always did.
 */
export function groupMatches(
  group: Partial<FilterGroup>,
  task: Task,
  devices?: Record<string, HassDevice>,
  areas?: Record<string, HassArea>,
): boolean {
  const taskLabels = taskLabelIds(task, devices, areas);
  const areaId = taskAreaId(task, devices);
  // The owning integration, from the `managed_by` block a companion sets on
  // `add_task`. A task nobody claims has none, so `listHas` rejects it from a
  // non-empty include list and spares it from every exclude list.
  const companion = task.managed_by?.integration;
  const labels = group.labels ?? [];
  // Stryker disable next-line StringLiteral: equivalent — `matchesLabels` only asks
  // whether the mode is 'all', so every other string takes the ANY branch anyway. The
  // literal is here to name the mode for a reader.
  const mode = group.labels_match === 'all' ? 'all' : 'any';
  if (labels.length && !matchesLabels(taskLabels, new Set(labels), mode)) return false;
  const wantAreas = group.areas ?? [];
  if (wantAreas.length && !listHas(wantAreas, areaId)) return false;
  const wantDevices = group.devices ?? [];
  if (wantDevices.length && !listHas(wantDevices, task.device_id)) return false;
  const wantCompanions = group.companions ?? [];
  if (wantCompanions.length && !listHas(wantCompanions, companion)) return false;
  // Exclusions subtract, and win over the include lists above — inside this group.
  if (group.exclude_labels?.some((id) => taskLabels.has(id))) return false;
  if (listHas(group.exclude_areas, areaId)) return false;
  if (listHas(group.exclude_devices, task.device_id)) return false;
  // By kind rather than by id — a buy reminder has none of its own to name.
  if (group.exclude_shopping && isBuyTask(task)) return false;
  return !listHas(group.exclude_companions, companion);
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
 * The shape is a status gate, then an **OR of groups**. The status window is the
 * profile's, so every group answers the same "which tasks are in season" question;
 * everything else lives in the groups, and a task is in the profile when *any* active
 * group takes it (`groupMatches` — an AND of that group's own include lists and
 * exclusions). This is what makes "the dog's jobs OR anything overdue in the garage"
 * one profile: two rules that share nothing but the status could not be written as one
 * flat list of ids at all.
 *
 * An **inactive** group — one with nothing set — is dropped before the OR, and a filter
 * left with no active group matches every task the gates let through. Both follow from
 * the same rule: a group that constrains nothing must not widen the profile, and the
 * editor always shows one empty group waiting to be filled in.
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
  // Stryker disable next-line ArrayDeclaration: equivalent — the fallback stands in for
  // "this filter has no groups", and any element a non-empty one could hold constrains
  // nothing, so `groupActive` filters it straight back out.
  const active = (filter.groups ?? []).filter(groupActive);
  return active.length === 0 || active.some((group) => groupMatches(group, task, devices, areas));
}

/**
 * Whether *filter* selects at least one of *tasks* right now, **ignoring its status**.
 *
 * A different question from `profileMatches`, and deliberately so. The Settings →
 * Notifications footer asks "is there anything here to send a real card about?", which
 * a profile set to Overdue answers `true` on a quiet day: it still owns tasks, none of
 * them is late yet. That is why the Test button sends `status: 'all'` — the status the
 * profile *saves* decides what it delivers on a schedule, not what a test can reach.
 *
 * Answered from the panel's own task list rather than by asking the backend, so the
 * button can repaint on every profile change in the form without a round trip.
 */
export function profileHasAnyTask(
  tasks: Task[],
  filter: ProfileFilter,
  devices?: Record<string, HassDevice>,
  areas?: Record<string, HassArea>,
  now = Date.now(),
): boolean {
  return tasks.some((task) =>
    profileMatches(task, { ...filter, status: 'all' }, devices, areas, now),
  );
}

/**
 * Fold a string to the form the panel's text filter compares on: no diacritics,
 * lower case, single spaces, and no space at either end.
 *
 * `toLowerCase` and not `toLocaleLowerCase`. The locale-sensitive form maps a
 * Turkish capital "I" to a dotless "ı", so two people reading the same list would
 * fold it two ways. The diacritic strip is what lets someone type "cistic" and find
 * "Čistič"; it changes nothing for Cyrillic or Han, where the marks are not
 * separable.
 */
export function normalizeSearch(value: string | null | undefined): string {
  return String(value ?? '')
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Whether every word of *query* is somewhere in *fields*.
 *
 * Word by word rather than one substring, so "water filter" finds the task
 * "Replace filter" on the appliance "Water heater". Which order the words come out
 * in is not something the reader must guess.
 *
 * A query with no words matches everything, which is what makes an empty box show
 * the whole list. That case is carried by `every` on an empty array rather than by
 * an early return: an early return here is true whichever way it is written, so it
 * would be a mutant no test could kill.
 */
export function matchesQuery(fields: (string | null | undefined)[], query: string): boolean {
  // Stryker disable next-line MethodExpression: equivalent — `normalizeSearch` has
  // already trimmed and collapsed, so the split can only yield an empty segment for
  // an empty query, and `includes('')` is true anyway. The filter states the intent.
  const terms = normalizeSearch(query).split(' ').filter(Boolean);
  // Joined with a space so a word can never match across two fields' contents.
  // Stryker disable next-line MethodExpression: equivalent — dropping the filter only
  // doubles a separator, and a term never holds a space, so nothing can match across
  // one. The filter keeps the haystack readable when it is inspected.
  const haystack = fields.map(normalizeSearch).filter(Boolean).join(' ');
  return terms.every((term) => haystack.includes(term));
}

/**
 * Whether *task* matches the panel's text filter.
 *
 * The fields are what identifies a task to the person looking for it: what it is
 * called, what they wrote on it, where it is, and which integration supplied it.
 * The integration name is the one that answers the reason this filter exists — a
 * household running several companions gets many generated tasks, and their owner
 * is what separates them (#297).
 */
export function taskMatchesQuery(
  task: Task,
  query: string,
  devices?: Record<string, HassDevice>,
  areas?: Record<string, HassArea>,
): boolean {
  return matchesQuery(
    [
      task.name,
      task.notes,
      deviceName(devices, task.device_id),
      // The effective area: a task with none of its own is placed by its device.
      areaName(areas, taskAreaId(task, devices)),
      task.managed_by?.display_name,
      // Stryker disable next-line ArrayDeclaration: equivalent — any element the
      // fallback could hold instead carries no `label`, which normalizes to '' and is
      // dropped from the haystack, so the empty array cannot be told from a full one.
      ...(task.task_chips ?? []).map((chip) => chip.label),
    ],
    query,
  );
}

/**
 * Whether *asset* matches the panel's text filter.
 *
 * The device name is not optional here: an appliance with no name of its own is
 * titled from its device in the list, so leaving it out would fail to match a row
 * on the very word that row shows.
 */
export function assetMatchesQuery(
  asset: Asset,
  query: string,
  devices?: Record<string, HassDevice>,
  areas?: Record<string, HassArea>,
): boolean {
  return matchesQuery(
    [
      asset.name,
      asset.notes,
      asset.manufacturer,
      asset.model,
      asset.serial_number,
      deviceName(devices, asset.device_id),
      areaName(areas, asset.area_id),
    ],
    query,
  );
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
 * Selection is an **OR of the card's filter groups**, the same rule a profile applies
 * (`groupMatches`) — so "the dog's jobs OR anything in the garage" is one card. A group
 * that constrains nothing is dropped first (`groupActive`), and a card left with no
 * active group selects every task the status, recurrence and horizon gates let through.
 * The status/recurrence/horizon gates are the card's own and apply to every group.
 *
 * `areas` is the HA area registry (passed last to stay backward-compatible with
 * existing positional callers); it's only needed so a group's label or area list can
 * match a task via the labels on its effective area.
 */
export function filterTasks(
  tasks: Task[],
  config: HomeKeeperCardConfig,
  devices?: Record<string, HassDevice>,
  now = Date.now(),
  areas?: Record<string, HassArea>,
): Task[] {
  // Stryker disable next-line ArrayDeclaration: equivalent — the fallback stands in for
  // "this card has no groups", and any element a non-empty one could hold constrains
  // nothing, so `groupActive` filters it straight back out.
  const active = (config.groups ?? []).filter(groupActive);
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
    if (active.length && !active.some((g) => groupMatches(g, task, devices, areas))) return false;
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
