import { matchesQuery } from './card-filter';
import type { Asset, Part, Task } from './types';
import { isBuyTask, isCompletedOneOff, isUseTask } from './utils';

/**
 * The pure logic of the Parts view: which parts it lists, how it filters, counts,
 * sorts and groups them, and which task belongs to a part. It reads no panel state and
 * no clock, so each rule has a direct test.
 */

/** One line of the view: a part and the appliance that holds it. */
export interface PartRow {
  asset: Asset;
  part: Part;
  /** The title that the appliance shows (`assetTitle`). */
  title: string;
}

export const PARTS_FILTERS = ['all', 'low', 'wear', 'uncounted'] as const;
export type PartsFilter = (typeof PARTS_FILTERS)[number];

export const PARTS_GROUPS = ['appliance', 'type'] as const;
export type PartsGroup = (typeof PARTS_GROUPS)[number];

export const PARTS_SORTS = ['name', 'stock', 'replaced'] as const;
export type PartsSort = (typeof PARTS_SORTS)[number];

/** The 2 modes of the Appliances tab. */
export const ASSET_MODES = ['appliances', 'parts'] as const;
export type AssetMode = (typeof ASSET_MODES)[number];

function oneOf<T extends string>(list: readonly T[], value: unknown, fallback: T): T {
  return (list as readonly unknown[]).includes(value) ? (value as T) : fallback;
}

/** A stored choice reads as the default when the value is not a known one. */
export function parsePartsFilter(value: unknown): PartsFilter {
  return oneOf(PARTS_FILTERS, value, 'all');
}
export function parsePartsGroup(value: unknown): PartsGroup {
  return oneOf(PARTS_GROUPS, value, 'appliance');
}
export function parsePartsSort(value: unknown): PartsSort {
  return oneOf(PARTS_SORTS, value, 'name');
}
export function parsePartsMode(value: unknown): AssetMode {
  return oneOf(ASSET_MODES, value, 'appliances');
}

/** Low stock: a count at or below the reorder point. Needs both numbers. */
export function isLowPart(part: Part): boolean {
  return part.stock != null && part.reorder_at != null && part.stock <= part.reorder_at;
}

/** Not counted: the part tracks no stock. */
export function isUncountedPart(part: Part): boolean {
  return part.stock == null;
}

/**
 * The parts to list. Only the appliances of the chosen scope count: active ones, or
 * archived ones when the Archived scope is on. A part with no id is left out, because
 * nothing can change its stock.
 */
export function collectParts(
  assets: Asset[],
  archived: boolean,
  titleOf: (asset: Asset) => string,
): PartRow[] {
  const rows: PartRow[] = [];
  for (const asset of assets) {
    if (Boolean(asset.archived_at) !== archived) continue;
    const title = titleOf(asset);
    for (const part of asset.parts ?? []) {
      if (part.id) rows.push({ asset, part, title });
    }
  }
  return rows;
}

/** The text filter: name, part number, vendor and the appliance title. */
export function partMatchesQuery(row: PartRow, query: string): boolean {
  return matchesQuery([row.part.name, row.part.part_number, row.part.vendor, row.title], query);
}

export interface PartsCounts {
  all: number;
  low: number;
  wear: number;
  uncounted: number;
}

export function countParts(rows: PartRow[]): PartsCounts {
  return {
    all: rows.length,
    low: rows.filter((r) => isLowPart(r.part)).length,
    wear: rows.filter((r) => r.part.type === 'wear').length,
    uncounted: rows.filter((r) => isUncountedPart(r.part)).length,
  };
}

export function filterParts(rows: PartRow[], filter: PartsFilter): PartRow[] {
  switch (filter) {
    case 'low':
      return rows.filter((r) => isLowPart(r.part));
    case 'wear':
      return rows.filter((r) => r.part.type === 'wear');
    case 'uncounted':
      return rows.filter((r) => isUncountedPart(r.part));
    default:
      return rows;
  }
}

const byText = (a: string, b: string): number => a.localeCompare(b, undefined, { sensitivity: 'base' });

/** A value that sorts last when it is missing. */
function lastWhenMissing<T>(a: T | null | undefined, b: T | null | undefined, cmp: (x: T, y: T) => number): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return cmp(a, b);
}

/**
 * Sort a copy of the rows. Name is the tie-break for every order, then the appliance
 * title. Stock goes lowest first with the uncounted last. Last replaced goes oldest
 * first with the never replaced last.
 */
export function sortParts(rows: PartRow[], sort: PartsSort): PartRow[] {
  const name = (a: PartRow, b: PartRow): number =>
    byText(a.part.name, b.part.name) || byText(a.title, b.title);
  const key = (a: PartRow, b: PartRow): number => {
    if (sort === 'stock') {
      return lastWhenMissing(a.part.stock, b.part.stock, (x, y) => x - y);
    }
    if (sort === 'replaced') {
      return lastWhenMissing(a.part.last_replaced || null, b.part.last_replaced || null, byText);
    }
    return 0;
  };
  return [...rows].sort((a, b) => key(a, b) || name(a, b));
}

export interface PartsGroupRows {
  key: string;
  label: string;
  rows: PartRow[];
}

/**
 * Split the rows into groups, each with its rows sorted. By appliance the groups follow
 * the appliance title, and 2 appliances with the same title stay apart. By type the wear
 * group comes first, and an empty group is left out. `typeLabels` holds the heading of
 * each type.
 */
export function groupParts(
  rows: PartRow[],
  group: PartsGroup,
  sort: PartsSort,
  typeLabels: { wear: string; consumable: string },
): PartsGroupRows[] {
  if (group === 'type') {
    return (['wear', 'consumable'] as const)
      .map((type) => ({
        key: type,
        label: typeLabels[type],
        rows: sortParts(
          rows.filter((r) => r.part.type === type),
          sort,
        ),
      }))
      .filter((g) => g.rows.length > 0);
  }
  const byAsset = new Map<string, PartsGroupRows>();
  for (const row of rows) {
    const found = byAsset.get(row.asset.id);
    if (found) found.rows.push(row);
    else byAsset.set(row.asset.id, { key: row.asset.id, label: row.title, rows: [row] });
  }
  return [...byAsset.values()]
    .map((g) => ({ ...g, rows: sortParts(g.rows, sort) }))
    .sort((a, b) => byText(a.label, b.label));
}

/** The Buy task of a part, unless it is already done. */
export function buyTaskForPart(tasks: Task[], assetId: string, partId: string): Task | undefined {
  return tasks.find(
    (task) =>
      isBuyTask(task) &&
      task.source?.buy?.asset_id === assetId &&
      task.source?.buy?.part_id === partId &&
      !isCompletedOneOff(task),
  );
}

function partTask(tasks: Task[], assetId: string, partId: string): Task[] {
  return tasks.filter(
    (task) =>
      !task.source?.part?.manual &&
      task.source?.part?.asset_id === assetId &&
      task.source?.part?.part_id === partId,
  );
}

/** The task that replaces a wear part. A missing role reads as replace. */
export function replaceTaskForPart(tasks: Task[], assetId: string, partId: string): Task | undefined {
  return partTask(tasks, assetId, partId).find((task) => !isUseTask(task));
}

/** The task that counts the uses of a counted wear part. */
export function useTaskForPart(tasks: Task[], assetId: string, partId: string): Task | undefined {
  return partTask(tasks, assetId, partId).find((task) => isUseTask(task));
}
