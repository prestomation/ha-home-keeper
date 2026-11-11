import { describe, expect, it } from 'vitest';
import {
  PARTS_FILTERS,
  PARTS_GROUPS,
  PARTS_SORTS,
  buyTaskForPart,
  collectParts,
  countParts,
  filterParts,
  groupParts,
  isLowPart,
  isUncountedPart,
  parsePartsFilter,
  parsePartsGroup,
  parsePartsMode,
  parsePartsSort,
  partMatchesQuery,
  replaceTaskForPart,
  sortParts,
  useTaskForPart,
} from '../src/parts-overview.ts';

const part = (over = {}) => ({ id: 'p', name: 'Part', type: 'consumable', ...over });
const asset = (id, name, parts, over = {}) => ({ id, name, parts, ...over });
const titleOf = (a) => a.name;
const rowOf = (a, p) => ({ asset: a, part: p, title: a.name });

describe('isLowPart', () => {
  it('is low at or below the reorder point', () => {
    expect(isLowPart(part({ stock: 2, reorder_at: 2 }))).toBe(true);
    expect(isLowPart(part({ stock: 1, reorder_at: 2 }))).toBe(true);
    expect(isLowPart(part({ stock: 3, reorder_at: 2 }))).toBe(false);
  });
  it('treats zero as a real count', () => {
    expect(isLowPart(part({ stock: 0, reorder_at: 0 }))).toBe(true);
    expect(isLowPart(part({ stock: 0, reorder_at: 1 }))).toBe(true);
  });
  it('is never low without a count or without a reorder point', () => {
    expect(isLowPart(part({ stock: null, reorder_at: 2 }))).toBe(false);
    expect(isLowPart(part({ reorder_at: 2 }))).toBe(false);
    expect(isLowPart(part({ stock: 0, reorder_at: null }))).toBe(false);
    expect(isLowPart(part({ stock: 0 }))).toBe(false);
  });
  it('compares decimals', () => {
    expect(isLowPart(part({ stock: 0.25, reorder_at: 0.5 }))).toBe(true);
    expect(isLowPart(part({ stock: 0.75, reorder_at: 0.5 }))).toBe(false);
  });
});

describe('isUncountedPart', () => {
  it('is true for null or absent stock only', () => {
    expect(isUncountedPart(part({ stock: null }))).toBe(true);
    expect(isUncountedPart(part())).toBe(true);
    expect(isUncountedPart(part({ stock: 0 }))).toBe(false);
    expect(isUncountedPart(part({ stock: 4 }))).toBe(false);
  });
});

describe('collectParts', () => {
  const live = asset('a1', 'Furnace', [part({ id: 'f1', name: 'Filter' })]);
  const old = asset('a2', 'Old fridge', [part({ id: 'o1', name: 'Seal' })], {
    archived_at: '2026-01-01T00:00:00+00:00',
  });
  const bare = asset('a3', 'Lamp', undefined);
  it('lists the parts of active appliances by default', () => {
    const rows = collectParts([live, old, bare], false, titleOf);
    expect(rows.map((r) => r.part.id)).toEqual(['f1']);
    expect(rows[0].asset).toBe(live);
    expect(rows[0].title).toBe('Furnace');
  });
  it('lists only archived appliances when the scope is archived', () => {
    const rows = collectParts([live, old], true, titleOf);
    expect(rows.map((r) => r.part.id)).toEqual(['o1']);
  });
  it('skips a part that has no id, because it cannot be changed', () => {
    const a = asset('a4', 'Pump', [part({ id: undefined, name: 'Seal' }), part({ id: 'x' })]);
    expect(collectParts([a], false, titleOf).map((r) => r.part.id)).toEqual(['x']);
  });
  it('keeps the parts of an appliance that an integration owns', () => {
    const pool = asset('a5', 'Battery pool', [part({ id: 'b1', name: 'AA' })], {
      managed_by: { domain: 'x', display_name: 'X', locked_fields: ['name'] },
    });
    expect(collectParts([pool], false, titleOf)).toHaveLength(1);
  });
});

describe('partMatchesQuery', () => {
  const r = rowOf(
    asset('a1', 'Furnace', []),
    part({ name: 'Filter 16x25', part_number: 'MERV 11', vendor: 'Home Depot' }),
  );
  it('matches an empty query', () => {
    expect(partMatchesQuery(r, '')).toBe(true);
    expect(partMatchesQuery(r, '   ')).toBe(true);
  });
  it('matches name, part number and vendor, ignoring case', () => {
    expect(partMatchesQuery(r, 'filter')).toBe(true);
    expect(partMatchesQuery(r, 'merv')).toBe(true);
    expect(partMatchesQuery(r, 'DEPOT')).toBe(true);
  });
  it('needs every word to match', () => {
    expect(partMatchesQuery(r, 'filter depot')).toBe(true);
    expect(partMatchesQuery(r, 'filter amazon')).toBe(false);
  });
  it('also matches the appliance title', () => {
    expect(partMatchesQuery(r, 'furnace')).toBe(true);
  });
  it('does not match across fields', () => {
    expect(partMatchesQuery(r, '16x25merv')).toBe(false);
  });
  it('tolerates missing fields', () => {
    expect(partMatchesQuery(rowOf(asset('a', 'A', []), part({ name: 'Bolt' })), 'bolt')).toBe(true);
  });
});

describe('countParts and filterParts', () => {
  const rows = [
    rowOf(asset('a', 'A', []), part({ id: '1', type: 'wear', stock: 1, reorder_at: 2 })),
    rowOf(asset('a', 'A', []), part({ id: '2', type: 'wear', stock: 5, reorder_at: 2 })),
    rowOf(asset('a', 'A', []), part({ id: '3', type: 'consumable', stock: 0, reorder_at: 1 })),
    rowOf(asset('a', 'A', []), part({ id: '4', type: 'wear', stock: null })),
    rowOf(asset('a', 'A', []), part({ id: '5', type: 'consumable' })),
  ];
  it('counts each chip', () => {
    expect(countParts(rows)).toEqual({ all: 5, low: 2, wear: 3, uncounted: 2 });
  });
  it('counts nothing for no rows', () => {
    expect(countParts([])).toEqual({ all: 0, low: 0, wear: 0, uncounted: 0 });
  });
  it('filters by each chip', () => {
    const ids = (f) => filterParts(rows, f).map((r) => r.part.id);
    expect(ids('all')).toEqual(['1', '2', '3', '4', '5']);
    expect(ids('low')).toEqual(['1', '3']);
    expect(ids('wear')).toEqual(['1', '2', '4']);
    expect(ids('uncounted')).toEqual(['4', '5']);
  });
  it('lets a count equal the length of its filter', () => {
    const c = countParts(rows);
    for (const f of PARTS_FILTERS) expect(filterParts(rows, f)).toHaveLength(c[f]);
  });
});

describe('sortParts', () => {
  const a = asset('a', 'Alpha', []);
  const b = asset('b', 'Beta', []);
  const rows = [
    rowOf(b, part({ id: '1', name: 'Zip', stock: 3, last_replaced: '2026-03-01' })),
    rowOf(a, part({ id: '2', name: 'Bolt', stock: null, last_replaced: null })),
    rowOf(a, part({ id: '3', name: 'bolt', stock: 1, last_replaced: '2026-01-15' })),
    rowOf(a, part({ id: '4', name: 'Nut', stock: 3 })),
  ];
  const ids = (s) => sortParts(rows, s).map((r) => r.part.id);
  it('sorts by name without case, then by appliance', () => {
    expect(ids('name')).toEqual(['2', '3', '4', '1']);
  });
  it('sorts by stock, lowest first, with uncounted last', () => {
    expect(ids('stock')).toEqual(['3', '4', '1', '2']);
  });
  it('sorts by last replaced, oldest first, with never replaced last', () => {
    expect(ids('replaced')).toEqual(['3', '1', '2', '4']);
  });
  it('does not change its input', () => {
    const before = rows.map((r) => r.part.id);
    sortParts(rows, 'stock');
    expect(rows.map((r) => r.part.id)).toEqual(before);
  });
  it('breaks a tie with the appliance title', () => {
    const t = [
      rowOf(b, part({ id: 'x', name: 'Same' })),
      rowOf(a, part({ id: 'y', name: 'Same' })),
    ];
    expect(sortParts(t, 'name').map((r) => r.part.id)).toEqual(['y', 'x']);
  });
  it('orders decimal stock by value', () => {
    const d = [
      rowOf(a, part({ id: 'p', name: 'P', stock: 10 })),
      rowOf(a, part({ id: 'q', name: 'Q', stock: 2.5 })),
    ];
    expect(sortParts(d, 'stock').map((r) => r.part.id)).toEqual(['q', 'p']);
  });
});

describe('sortParts over every input order', () => {
  const a = asset('a', 'Alpha', []);
  const mk = (id, name, extra) => rowOf(a, part({ id, name, ...extra }));
  const permutations = (list) =>
    list.length <= 1
      ? [list]
      : list.flatMap((x, i) =>
          permutations([...list.slice(0, i), ...list.slice(i + 1)]).map((rest) => [x, ...rest]),
        );
  const check = (rows, sort, expected) => {
    for (const order of permutations(rows)) {
      expect(sortParts(order, sort).map((r) => r.part.id)).toEqual(expected);
    }
  };
  it('puts uncounted parts last and orders them by name', () => {
    check(
      [mk('1', 'D', { stock: 1 }), mk('2', 'C', { stock: 4 }), mk('3', 'B'), mk('4', 'A', { stock: null })],
      'stock',
      ['1', '2', '4', '3'],
    );
  });
  it('puts never replaced parts last and orders them by name', () => {
    check(
      [
        mk('1', 'D', { last_replaced: '2026-02-01' }),
        mk('2', 'C', { last_replaced: '2026-01-01' }),
        mk('3', 'B', { last_replaced: '' }),
        mk('4', 'A'),
      ],
      'replaced',
      ['2', '1', '4', '3'],
    );
  });
  it('ignores stock and dates when the order is by name', () => {
    check(
      [mk('1', 'C', { stock: 1, last_replaced: '2026-03-01' }), mk('2', 'B', { stock: 9 }), mk('3', 'A', { last_replaced: '2026-01-01' })],
      'name',
      ['3', '2', '1'],
    );
  });
});

describe('groupParts', () => {
  const a = asset('a', 'Alpha', []);
  const b = asset('b', 'beta', []);
  const rows = [
    rowOf(b, part({ id: '1', name: 'B1', type: 'wear' })),
    rowOf(a, part({ id: '2', name: 'A2', type: 'consumable' })),
    rowOf(a, part({ id: '3', name: 'A1', type: 'wear' })),
  ];
  const labels = { wear: 'Wear', consumable: 'Consumable' };
  it('groups by appliance in title order, with sorted rows', () => {
    const g = groupParts(rows, 'appliance', 'name', labels);
    expect(g.map((x) => x.label)).toEqual(['Alpha', 'beta']);
    expect(g[0].rows.map((r) => r.part.id)).toEqual(['3', '2']);
    expect(g[0].key).toBe('a');
  });
  it('groups by type, wear first', () => {
    const g = groupParts(rows, 'type', 'name', labels);
    expect(g.map((x) => x.label)).toEqual(['Wear', 'Consumable']);
    expect(g[0].rows.map((r) => r.part.id)).toEqual(['3', '1']);
    expect(g[0].key).toBe('wear');
  });
  it('drops a type group with no rows', () => {
    const only = rows.filter((r) => r.part.type === 'wear');
    expect(groupParts(only, 'type', 'name', labels).map((x) => x.key)).toEqual(['wear']);
  });
  it('gives no groups for no rows', () => {
    expect(groupParts([], 'appliance', 'name', labels)).toEqual([]);
    expect(groupParts([], 'type', 'name', labels)).toEqual([]);
  });
  it('does not merge two appliances with the same title', () => {
    const c = asset('c', 'Alpha', []);
    const g = groupParts(
      [rowOf(a, part({ id: '1' })), rowOf(c, part({ id: '2' }))],
      'appliance',
      'name',
      labels,
    );
    expect(g).toHaveLength(2);
  });
});

describe('task lookups', () => {
  const buy = {
    id: 't1',
    name: 'Buy filter',
    source: { buy: { asset_id: 'a', part_id: 'p' } },
  };
  const wear = {
    id: 't2',
    name: 'Replace filter',
    source: { part: { asset_id: 'a', part_id: 'p', role: 'replace' } },
  };
  const wearNoRole = {
    id: 't3',
    name: 'Replace x',
    source: { part: { asset_id: 'a', part_id: 'q' } },
  };
  const use = {
    id: 't4',
    name: 'Use',
    recurrence_type: 'use',
    source: { part: { asset_id: 'a', part_id: 'p', role: 'use' } },
  };
  const manual = {
    id: 't5',
    name: 'Manual',
    source: { part: { asset_id: 'a', part_id: 'm', manual: true } },
  };
  const bare = { id: 'bare', name: 'No source' };
  const emptySource = { id: 'empty', name: 'Empty source', source: {} };
  // The same part id on another appliance: a lookup must read the appliance too.
  const otherBuy = { id: 'o1', name: 'Buy', source: { buy: { asset_id: 'z', part_id: 'p' } } };
  const otherWear = { id: 'o2', name: 'Replace', source: { part: { asset_id: 'z', part_id: 'p' } } };
  const otherUse = {
    id: 'o3',
    name: 'Use',
    recurrence_type: 'use',
    source: { part: { asset_id: 'z', part_id: 'p', role: 'use' } },
  };
  const tasks = [bare, emptySource, otherBuy, otherWear, otherUse, buy, wear, wearNoRole, use, manual];
  it('finds the buy task of a part', () => {
    expect(buyTaskForPart(tasks, 'a', 'p')).toBe(buy);
    expect(buyTaskForPart(tasks, 'a', 'q')).toBeUndefined();
    expect(buyTaskForPart(tasks, 'y', 'p')).toBeUndefined();
    expect(buyTaskForPart(tasks, 'z', 'p')).toBe(otherBuy);
  });
  it('ignores a buy task that is already done', () => {
    const done = {
      ...buy,
      recurrence_type: 'one-off',
      next_due: null,
      last_completed: '2026-01-01T00:00:00+00:00',
    };
    expect(buyTaskForPart([done], 'a', 'p')).toBeUndefined();
  });
  it('finds the replace task, and reads a missing role as replace', () => {
    expect(replaceTaskForPart(tasks, 'a', 'p')).toBe(wear);
    expect(replaceTaskForPart(tasks, 'a', 'q')).toBe(wearNoRole);
    expect(replaceTaskForPart(tasks, 'z', 'p')).toBe(otherWear);
  });
  it('does not take the use task or a manual link for the replace task', () => {
    expect(replaceTaskForPart([use], 'a', 'p')).toBeUndefined();
    expect(replaceTaskForPart([manual], 'a', 'm')).toBeUndefined();
  });
  it('finds the use task of a counted part', () => {
    expect(useTaskForPart(tasks, 'a', 'p')).toBe(use);
    expect(useTaskForPart(tasks, 'a', 'q')).toBeUndefined();
    expect(useTaskForPart(tasks, 'z', 'p')).toBe(otherUse);
  });
});

describe('stored choices', () => {
  it('reads a known value and anything else as the default', () => {
    expect(parsePartsFilter('low')).toBe('low');
    expect(parsePartsFilter('nope')).toBe('all');
    expect(parsePartsFilter(null)).toBe('all');
    expect(parsePartsGroup('type')).toBe('type');
    expect(parsePartsGroup('x')).toBe('appliance');
    expect(parsePartsSort('replaced')).toBe('replaced');
    expect(parsePartsSort('')).toBe('name');
    expect(parsePartsMode('parts')).toBe('parts');
    expect(parsePartsMode('appliances')).toBe('appliances');
    expect(parsePartsMode('x')).toBe('appliances');
    expect(parsePartsMode(null)).toBe('appliances');
  });
  it('accepts every listed value', () => {
    for (const f of PARTS_FILTERS) expect(parsePartsFilter(f)).toBe(f);
    for (const g of PARTS_GROUPS) expect(parsePartsGroup(g)).toBe(g);
    for (const s of PARTS_SORTS) expect(parsePartsSort(s)).toBe(s);
  });
});
