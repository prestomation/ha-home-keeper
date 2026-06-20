import { afterEach, describe, expect, it } from 'vitest';
import { setLanguage } from '../src/i18n.ts';
import {
  filterTasks,
  groupTasks,
  sortTasks,
  statusBucket,
} from '../src/card-filter.ts';

afterEach(() => setLanguage('en'));

// A fixed "now" so relative date math is deterministic.
const NOW = new Date('2026-06-16T12:00:00Z').getTime();
const DAY = 86_400_000;

/** Build a task with sensible defaults. */
function task(over = {}) {
  return {
    id: over.id ?? Math.random().toString(36).slice(2),
    name: over.name ?? 'Task',
    recurrence_type: over.recurrence_type ?? 'floating',
    ...over,
  };
}

const overdue = task({ id: 'o', name: 'Overdue', next_due: new Date(NOW - 3 * DAY).toISOString() });
const today = task({ id: 't', name: 'Today', next_due: new Date(NOW + 2 * 3600_000).toISOString() });
const soon = task({ id: 's', name: 'Soon', next_due: new Date(NOW + 3 * DAY).toISOString() });
const later = task({ id: 'l', name: 'Later', next_due: new Date(NOW + 30 * DAY).toISOString() });
const monitored = task({ id: 'm', name: 'Battery', recurrence_type: 'triggered' });
const undated = task({ id: 'n', name: 'No schedule' });

describe('statusBucket', () => {
  it('classifies by due date relative to now', () => {
    expect(statusBucket(overdue, NOW)).toBe('overdue');
    expect(statusBucket(today, NOW)).toBe('today');
    expect(statusBucket(soon, NOW)).toBe('soon');
    expect(statusBucket(later, NOW)).toBe('later');
  });

  it('treats a dormant triggered task as monitored, an undated one as none', () => {
    expect(statusBucket(monitored, NOW)).toBe('monitored');
    expect(statusBucket(undated, NOW)).toBe('none');
  });
});

describe('filterTasks', () => {
  const all = [overdue, today, soon, later, monitored, undated];

  it('returns everything for the default/all filter', () => {
    expect(filterTasks(all, { type: '' }, {}, NOW)).toHaveLength(all.length);
  });

  it('overdue keeps only past-due tasks', () => {
    expect(filterTasks(all, { type: '', filter: 'overdue' }, {}, NOW).map((t) => t.id)).toEqual(['o']);
  });

  it('today includes overdue plus anything due before midnight', () => {
    const ids = filterTasks(all, { type: '', filter: 'today' }, {}, NOW).map((t) => t.id);
    expect(ids).toEqual(['o', 't']);
  });

  it('no_due keeps undated and dormant triggered tasks', () => {
    const ids = filterTasks(all, { type: '', filter: 'no_due' }, {}, NOW)
      .map((t) => t.id)
      .sort();
    expect(ids).toEqual(['m', 'n']);
  });

  it('hides disabled tasks unless show_disabled is set', () => {
    const disabled = task({ id: 'd', enabled: false, next_due: new Date(NOW + DAY).toISOString() });
    const list = [...all, disabled];
    expect(filterTasks(list, { type: '' }, {}, NOW).find((t) => t.id === 'd')).toBeUndefined();
    expect(filterTasks(list, { type: '', show_disabled: true }, {}, NOW).find((t) => t.id === 'd')).toBeTruthy();
  });

  it('hides managed tasks when hide_managed is set', () => {
    const managed = task({ id: 'g', managed_by: { integration: 'x', display_name: 'X' }, next_due: new Date(NOW + DAY).toISOString() });
    const list = [...all, managed];
    expect(filterTasks(list, { type: '', hide_managed: true }, {}, NOW).find((t) => t.id === 'g')).toBeUndefined();
  });

  it('horizon_days keeps overdue + within-window dated tasks, drops undated', () => {
    const ids = filterTasks(all, { type: '', horizon_days: 7 }, {}, NOW)
      .map((t) => t.id)
      .sort();
    // overdue, today, soon are within 7 days; later/monitored/undated dropped.
    expect(ids).toEqual(['o', 's', 't']);
  });

  it('ignores horizon_days for the no_due filter (keeps undated tasks)', () => {
    const ids = filterTasks(all, { type: '', filter: 'no_due', horizon_days: 7 }, {}, NOW)
      .map((t) => t.id)
      .sort();
    expect(ids).toEqual(['m', 'n']);
  });

  it('filters by area, resolving a task to its device area', () => {
    const devices = { dev1: { id: 'dev1', area_id: 'kitchen' } };
    const inKitchenDirect = task({ id: 'k1', area_id: 'kitchen', next_due: new Date(NOW + DAY).toISOString() });
    const inKitchenViaDevice = task({ id: 'k2', device_id: 'dev1', next_due: new Date(NOW + DAY).toISOString() });
    const elsewhere = task({ id: 'k3', area_id: 'garage', next_due: new Date(NOW + DAY).toISOString() });
    const ids = filterTasks(
      [inKitchenDirect, inKitchenViaDevice, elsewhere],
      { type: '', areas: ['kitchen'] },
      devices,
      NOW,
    )
      .map((t) => t.id)
      .sort();
    expect(ids).toEqual(['k1', 'k2']);
  });

  it('filters by recurrence type', () => {
    const ids = filterTasks(all, { type: '', recurrence_types: ['triggered'] }, {}, NOW).map((t) => t.id);
    expect(ids).toEqual(['m']);
  });

  describe('label filter', () => {
    const due = (over) => task({ next_due: new Date(NOW + DAY).toISOString(), ...over });
    const tagged = due({ id: 'tg', labels: ['dog'] });
    const viaDevice = due({ id: 'vd', device_id: 'dev1' });
    const viaArea = due({ id: 'va', area_id: 'yard' });
    const untagged = due({ id: 'ut' });
    const devices = { dev1: { id: 'dev1', labels: ['dog'] } };
    const areas = { yard: { area_id: 'yard', name: 'Yard', labels: ['dog'] } };
    const list = [tagged, viaDevice, viaArea, untagged];

    it("matches a task's own label, plus labels via its device and effective area", () => {
      const ids = filterTasks(list, { type: '', labels: ['dog'] }, devices, NOW, areas)
        .map((t) => t.id)
        .sort();
      expect(ids).toEqual(['tg', 'va', 'vd']);
    });

    it('defaults to ANY: a task with one of several configured labels survives', () => {
      const ids = filterTasks(
        [due({ id: 'a', labels: ['dog'] }), due({ id: 'b', labels: ['car'] }), untagged],
        { type: '', labels: ['dog', 'car'] },
        {},
        NOW,
        {},
      )
        .map((t) => t.id)
        .sort();
      expect(ids).toEqual(['a', 'b']);
    });

    it('label_match=all requires every configured label', () => {
      const both = due({ id: 'both', labels: ['dog', 'vet'] });
      const one = due({ id: 'one', labels: ['dog'] });
      const ids = filterTasks(
        [both, one],
        { type: '', labels: ['dog', 'vet'], label_match: 'all' },
        {},
        NOW,
        {},
      ).map((t) => t.id);
      expect(ids).toEqual(['both']);
    });
  });
});

describe('sortTasks', () => {
  it('sorts by due date ascending by default, undated last', () => {
    const ids = sortTasks([later, undated, overdue, soon], 'due').map((t) => t.id);
    expect(ids).toEqual(['o', 's', 'l', 'n']);
  });

  it('sorts by name', () => {
    const ids = sortTasks([soon, overdue, later], 'name').map((t) => t.name);
    expect(ids).toEqual(['Later', 'Overdue', 'Soon']);
  });

  it('sorts by most recently completed first', () => {
    const a = task({ id: 'a', last_completed: new Date(NOW - 10 * DAY).toISOString() });
    const b = task({ id: 'b', last_completed: new Date(NOW - 1 * DAY).toISOString() });
    const c = task({ id: 'c' }); // never completed -> last
    expect(sortTasks([a, b, c], 'recent').map((t) => t.id)).toEqual(['b', 'a', 'c']);
  });
});

describe('groupTasks', () => {
  it('returns a single unlabelled group when grouping is none', () => {
    const groups = groupTasks([overdue, soon], 'none', {}, {}, NOW);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe('');
    expect(groups[0].items).toHaveLength(2);
  });

  it('buckets by status in a stable order, dropping empty buckets', () => {
    setLanguage('en');
    const groups = groupTasks([later, overdue, today, soon, monitored], 'status', {}, {}, NOW);
    expect(groups.map((g) => g.key)).toEqual([
      'status:overdue',
      'status:today',
      'status:soon',
      'status:later',
      'status:monitored',
    ]);
  });

  it('groups by area with a fallback bucket sunk to the bottom', () => {
    const areas = { kitchen: { area_id: 'kitchen', name: 'Kitchen' } };
    const k = task({ id: 'k', area_id: 'kitchen', next_due: new Date(NOW + DAY).toISOString() });
    const groups = groupTasks([k, undated], 'area', areas, {}, NOW);
    expect(groups[0].label).toBe('Kitchen');
    expect(groups[groups.length - 1].key).toBe('area:none');
  });
});
