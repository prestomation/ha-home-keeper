import { describe, expect, it } from 'vitest';
import {
  applyKeyRows,
  keyOptions,
  toggleKeyRow,
  EXCLUSION_FIELDS,
  exclusionCount,
  exclusionsSchema,
  filterCount,
  hasMoreFilters,
  idList,
  keyRows,
  moreFiltersSchema,
  moreFiltersSummary,
  toggleId,
} from '../src/declarative-filters.ts';

/**
 * The pure half of the companion dialog's More filters block (#373): the two schemas,
 * the counts behind the closed row's summary, and the list toggle the preview's
 * Exclude and Include buttons share.
 */

const EMPTY = {
  area_ids: [],
  label_ids: [],
  exclude_entity_ids: [],
  exclude_device_ids: [],
  exclude_area_ids: [],
  exclude_label_ids: [],
};

describe('moreFiltersSchema', () => {
  it('offers device class, the three include lists and the regex, in that order', () => {
    expect(moreFiltersSchema()).toEqual([
      { name: 'device_class', selector: { text: {} } },
      { name: 'device_ids', selector: { device: { multiple: true } } },
      { name: 'area_ids', selector: { area: { multiple: true } } },
      { name: 'label_ids', selector: { label: { multiple: true } } },
      { name: 'entity_regex', selector: { text: {} } },
    ]);
  });
});

describe('exclusionsSchema', () => {
  it('offers one multiple picker per exclusion list, with no entity filter', () => {
    expect(exclusionsSchema()).toEqual([
      { name: 'exclude_entity_ids', selector: { entity: { filter: {}, multiple: true } } },
      { name: 'exclude_device_ids', selector: { device: { multiple: true } } },
      { name: 'exclude_area_ids', selector: { area: { multiple: true } } },
      { name: 'exclude_label_ids', selector: { label: { multiple: true } } },
    ]);
  });

  it('names exactly the fields EXCLUSION_FIELDS lists', () => {
    expect(exclusionsSchema().map((f) => f.name)).toEqual([...EXCLUSION_FIELDS]);
  });
});

describe('filterCount', () => {
  it('is 0 for a selection with nothing set', () => {
    expect(filterCount(EMPTY)).toBe(0);
    expect(filterCount({})).toBe(0);
  });

  it('counts each filter once, whatever a list holds', () => {
    expect(filterCount({ ...EMPTY, device_class: 'battery' })).toBe(1);
    expect(filterCount({ ...EMPTY, entity_regex: 'sensor\\..*' })).toBe(1);
    expect(filterCount({ ...EMPTY, area_ids: ['garage', 'hall'] })).toBe(1);
    expect(filterCount({ ...EMPTY, label_ids: ['a'] })).toBe(1);
    expect(filterCount({ ...EMPTY, translation_keys: ['a', 'b'] })).toBe(1);
    expect(filterCount({ ...EMPTY, translation_keys: [] })).toBe(0);
    expect(filterCount({ ...EMPTY, device_ids: ['a', 'b'] })).toBe(1);
    expect(filterCount({ ...EMPTY, device_ids: [] })).toBe(0);
    expect(
      filterCount({
        device_class: 'battery',
        entity_regex: 'x',
        area_ids: ['garage'],
        label_ids: ['a', 'b'],
      }),
    ).toBe(4);
  });

  it('ignores an empty device class and an empty regex', () => {
    expect(filterCount({ ...EMPTY, device_class: '', entity_regex: '' })).toBe(0);
  });

  it('does not count the fields outside More filters', () => {
    expect(filterCount({ ...EMPTY, target_integration: 'zha', domain: 'sensor' })).toBe(0);
  });
});

describe('exclusionCount', () => {
  it('adds up the ids in all four lists', () => {
    expect(
      exclusionCount({
        exclude_entity_ids: ['sensor.a', 'sensor.b'],
        exclude_device_ids: ['d1'],
        exclude_area_ids: ['garage'],
        exclude_label_ids: ['l1', 'l2', 'l3'],
      }),
    ).toBe(7);
  });

  it('treats a missing list as empty', () => {
    expect(exclusionCount({})).toBe(0);
    expect(exclusionCount({ exclude_area_ids: ['garage'] })).toBe(1);
  });
});

describe('hasMoreFilters', () => {
  it('is false when nothing inside More filters is set', () => {
    expect(hasMoreFilters(EMPTY)).toBe(false);
  });

  it('is true for a filter alone and for an exclusion alone', () => {
    expect(hasMoreFilters({ ...EMPTY, device_class: 'battery' })).toBe(true);
    expect(hasMoreFilters({ ...EMPTY, exclude_label_ids: ['l1'] })).toBe(true);
  });
});

describe('moreFiltersSummary', () => {
  it('says none is set when the block is empty', () => {
    expect(moreFiltersSummary(EMPTY)).toBe('No other filters set');
  });

  it('names the filters alone', () => {
    expect(moreFiltersSummary({ ...EMPTY, device_class: 'battery' })).toBe('1 filter');
    expect(moreFiltersSummary({ ...EMPTY, device_class: 'battery', area_ids: ['g'] })).toBe(
      '2 filters',
    );
  });

  it('names the exclusions alone', () => {
    expect(moreFiltersSummary({ ...EMPTY, exclude_entity_ids: ['sensor.a'] })).toBe(
      '1 exclusion',
    );
    expect(
      moreFiltersSummary({ ...EMPTY, exclude_entity_ids: ['sensor.a'], exclude_area_ids: ['g'] }),
    ).toBe('2 exclusions');
  });

  it('joins both with a middle dot, filters first', () => {
    expect(
      moreFiltersSummary({
        ...EMPTY,
        device_class: 'battery',
        exclude_entity_ids: ['sensor.a', 'sensor.b', 'sensor.c'],
      }),
    ).toBe('1 filter · 3 exclusions');
  });
});

describe('toggleId', () => {
  it('adds a missing id at the end', () => {
    expect(toggleId(['a', 'b'], 'c')).toEqual(['a', 'b', 'c']);
  });

  it('removes an id that is there and keeps the order of the rest', () => {
    expect(toggleId(['a', 'b', 'c'], 'b')).toEqual(['a', 'c']);
  });

  it('starts a list from nothing', () => {
    expect(toggleId(undefined, 'a')).toEqual(['a']);
  });

  it('never changes the list it was given', () => {
    const list = ['a'];
    toggleId(list, 'b');
    toggleId(list, 'a');
    expect(list).toEqual(['a']);
  });
});

describe('idList', () => {
  it('reads a list of ids as strings', () => {
    expect(idList(['a', 2])).toEqual(['a', '2']);
  });

  it('reads anything that is not a list as empty', () => {
    expect(idList(undefined)).toEqual([]);
    expect(idList('a')).toEqual([]);
    expect(idList(null)).toEqual([]);
  });
});

describe('keyRows', () => {
  it('gives one row per key, in list order, with its task name', () => {
    expect(keyRows(['b', 'a'], { a: 'Replace A', c: 'Unused' })).toEqual([
      { key: 'b', name: '' },
      { key: 'a', name: 'Replace A' },
    ]);
  });

  it('gives no rows for a missing list, and blank names for a missing table', () => {
    expect(keyRows(undefined, { a: 'x' })).toEqual([]);
    expect(keyRows(['a'], undefined)).toEqual([{ key: 'a', name: '' }]);
  });
});

describe('applyKeyRows', () => {
  it('trims keys and names and keeps only named keys in the table', () => {
    expect(
      applyKeyRows([
        { key: ' filter ', name: ' Replace filter ' },
        { key: 'brush', name: '   ' },
      ]),
    ).toEqual({ translation_keys: ['filter', 'brush'], task_names: { filter: 'Replace filter' } });
  });

  it('skips a row with no key, and keeps the first row of a repeated key', () => {
    expect(
      applyKeyRows([
        { key: '  ', name: 'Orphan' },
        { key: 'a', name: 'First' },
        { key: 'a', name: 'Second' },
      ]),
    ).toEqual({ translation_keys: ['a'], task_names: { a: 'First' } });
  });

  it('gives empty results for no rows', () => {
    expect(applyKeyRows([])).toEqual({ translation_keys: [], task_names: {} });
  });

  // F06-4: a spec made through the service can have names and no key list. The
  // editor shows no rows for those names, and its first change deleted them.
  it('F06-4: keeps the stored names when the rows give no key', () => {
    const stored = { main_brush_time_left: 'Replace main brush', filter_time_left: 'Replace filter' };
    const out = applyKeyRows([{ key: ' ', name: 'Draft' }], stored);
    expect(out).toEqual({ translation_keys: [], task_names: stored });
    expect(out.task_names).not.toBe(stored);
    expect(applyKeyRows([], stored)).toEqual({ translation_keys: [], task_names: stored });
  });

  it('F06-4: takes the names from the rows when they give a key list', () => {
    const stored = { a: 'Stored A', b: 'Stored B' };
    expect(applyKeyRows([{ key: 'a', name: 'Row A' }], stored)).toEqual({
      translation_keys: ['a'],
      task_names: { a: 'Row A' },
    });
  });
});

const KEYS = [
  { key: 'filter_time_left', count: 2, example_entity_id: 'sensor.a', example_name: 'Kitchen Filter' },
  { key: 'main_brush_time_left', count: 1, example_entity_id: 'sensor.b', example_name: 'Kitchen Brush' },
];

describe('keyOptions', () => {
  it('marks the keys already added, and keeps the order', () => {
    expect(keyOptions(KEYS, ['main_brush_time_left'], '')).toEqual([
      { ...KEYS[0], picked: false },
      { ...KEYS[1], picked: true },
    ]);
  });

  it('searches the key and the example name, in any case, after a trim', () => {
    expect(keyOptions(KEYS, [], ' BRUSH ').map((o) => o.key)).toEqual(['main_brush_time_left']);
    expect(keyOptions(KEYS, [], 'kitchen filter').map((o) => o.key)).toEqual(['filter_time_left']);
    expect(keyOptions(KEYS, [], 'nothing')).toEqual([]);
  });

  it('does not match across the key and the example name', () => {
    expect(keyOptions(KEYS, [], 'leftkitchen')).toEqual([]);
  });
});

describe('toggleKeyRow', () => {
  it('adds a key at the end with no task name', () => {
    expect(toggleKeyRow([{ key: 'a', name: 'A' }], 'b')).toEqual([
      { key: 'a', name: 'A' },
      { key: 'b', name: '' },
    ]);
  });

  it('takes out a key that is there, with its task name', () => {
    expect(
      toggleKeyRow(
        [
          { key: 'a', name: 'A' },
          { key: 'b', name: 'B' },
        ],
        'a',
      ),
    ).toEqual([{ key: 'b', name: 'B' }]);
  });

  // F06-5: the key list marks a typed key with a space as picked, so a click must
  // take that row out, not add a second one.
  it('F06-5: takes out a row whose key has spaces around it', () => {
    expect(
      toggleKeyRow(
        [
          { key: 'filter_life ', name: '' },
          { key: 'b', name: 'B' },
        ],
        'filter_life',
      ),
    ).toEqual([{ key: 'b', name: 'B' }]);
  });

  it('F06-4: gives an added key its stored task name', () => {
    const stored = { a: 'Replace A' };
    expect(toggleKeyRow([], 'a', stored)).toEqual([{ key: 'a', name: 'Replace A' }]);
    expect(toggleKeyRow([], 'b', stored)).toEqual([{ key: 'b', name: '' }]);
  });
});
