import { describe, expect, it } from 'vitest';
import {
  EXCLUSION_FIELDS,
  exclusionCount,
  exclusionsSchema,
  filterCount,
  hasMoreFilters,
  idList,
  moreFiltersSchema,
  moreFiltersSummary,
  toggleId,
} from '../src/declarative-filters.ts';

/**
 * The pure half of the recipe dialog's More filters block (#373): the two schemas,
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
  it('offers device class, the two include lists and the regex, in that order', () => {
    expect(moreFiltersSchema()).toEqual([
      { name: 'device_class', selector: { text: {} } },
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
