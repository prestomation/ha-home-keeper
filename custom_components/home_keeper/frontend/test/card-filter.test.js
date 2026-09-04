import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it } from 'vitest';
import { setLanguage } from '../src/i18n.ts';
import {
  DAY_MS,
  SOON_DAYS,
  bucketByKey,
  filterTasks,
  groupTasks,
  profileMatches,
  sortTasks,
  statusBucket,
} from '../src/card-filter.ts';

afterEach(() => setLanguage('en'));

// Shared cross-language conformance fixture (also run by the Python matcher in
// tests/unit/test_profiles.py) — a Profile must select the same tasks here as it does
// server-side in a notification.
// vitest runs from the repo root (see CI + the project vitest config), so resolve the
// shared fixture from there.
const CONFORMANCE = JSON.parse(
  readFileSync('tests/fixtures/profile_filter_cases.json', 'utf8'),
);

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

  it('treats a dormant sensor task as monitored', () => {
    const sensorDormant = task({ id: 'sd', name: 'Sensor', recurrence_type: 'sensor' });
    expect(statusBucket(sensorDormant, NOW)).toBe('monitored');
  });

  it('buckets a malformed next_due as none rather than falling through to later', () => {
    const bad = task({ id: 'b', name: 'Bad date', next_due: 'not-a-date' });
    expect(statusBucket(bad, NOW)).toBe('none');
  });
});

// A buy reminder is minted as a dateless one-off, which is due *now*, so it is
// overdue from birth. Without its own bucket it lands beside genuinely late
// maintenance for as long as the part stays low.
describe('statusBucket: auto-buy reminders', () => {
  const buy = (extra = {}) =>
    task({
      id: 'buy',
      name: 'Buy filter',
      recurrence_type: 'one-off',
      next_due: new Date(NOW - 3 * DAY).toISOString(),
      source: { buy: { asset_id: 'a1', part_id: 'p1' } },
      ...extra,
    });

  it('buckets an open buy reminder as shopping, not overdue', () => {
    expect(statusBucket(buy(), NOW)).toBe('shopping');
    expect(statusBucket(buy(), NOW, { today: false, completed: true })).toBe('shopping');
  });

  it('leaves an ordinary overdue task alone', () => {
    expect(statusBucket(overdue, NOW)).toBe('overdue');
  });

  it('does not claim a task whose source is something else', () => {
    expect(statusBucket(buy({ source: { part: { asset_id: 'a1' } } }), NOW)).toBe('overdue');
    expect(statusBucket(buy({ source: {} }), NOW)).toBe('overdue');
  });

  it('lets a bought reminder reach the completed section on the panel', () => {
    // Ordering matters: the completed check runs first, so a one-off that has been
    // bought reads as done rather than sitting in Shopping forever.
    const bought = buy({ next_due: null, last_completed: new Date(NOW - DAY).toISOString() });
    expect(statusBucket(bought, NOW, { today: false, completed: true })).toBe('completed');
    // …and on the card, which has no completed section, it is simply undated.
    expect(statusBucket(bought, NOW)).toBe('none');
  });

  it('sends a dateless buy reminder to none rather than shopping', () => {
    expect(statusBucket(buy({ next_due: null }), NOW)).toBe('none');
  });
});

// The card and the panel share this bucketing but differ on two sections; the
// defaults are the card's, and { today: false, completed: true } is the panel's.
describe('statusBucket per-surface options', () => {
  // A do-once task that has been done: no next_due left, a completion behind it.
  const doneOneOff = task({
    id: 'do',
    name: 'Done once',
    recurrence_type: 'one-off',
    last_completed: new Date(NOW - DAY).toISOString(),
  });
  const openOneOff = task({ id: 'oo', name: 'Never done', recurrence_type: 'one-off' });

  it('defaults reproduce the card: a today section, and no completed section', () => {
    expect(statusBucket(today, NOW)).toBe('today');
    expect(statusBucket(today, NOW, {})).toBe('today');
    expect(statusBucket(doneOneOff, NOW)).toBe('none');
    expect(statusBucket(doneOneOff, NOW, {})).toBe('none');
  });

  it('today:false folds a task due later today into soon (the panel)', () => {
    expect(statusBucket(today, NOW, { today: false })).toBe('soon');
    expect(statusBucket(today, NOW, { today: false, completed: true })).toBe('soon');
    // The sections either side of it are untouched by the option.
    expect(statusBucket(overdue, NOW, { today: false })).toBe('overdue');
    expect(statusBucket(later, NOW, { today: false })).toBe('later');
    expect(statusBucket(undated, NOW, { today: false })).toBe('none');
  });

  it('completed:true gives a finished one-off its own bucket, and only it', () => {
    expect(statusBucket(doneOneOff, NOW, { completed: true })).toBe('completed');
    // Never completed: nothing has been done, so the generic no-schedule bucket.
    expect(statusBucket(openOneOff, NOW, { completed: true })).toBe('none');
    // Still armed: it buckets on its due date like any other dated task.
    const armed = task({
      id: 'ao',
      recurrence_type: 'one-off',
      next_due: new Date(NOW - DAY).toISOString(),
      last_completed: new Date(NOW - 30 * DAY).toISOString(),
    });
    expect(statusBucket(armed, NOW, { completed: true })).toBe('overdue');
    // A recurring task with completions behind it is not "completed" — it recurs.
    const recurring = task({
      id: 'rc',
      recurrence_type: 'floating',
      last_completed: new Date(NOW - DAY).toISOString(),
    });
    expect(statusBucket(recurring, NOW, { completed: true })).toBe('none');
    // A dormant triggered task stays monitored, whichever sections are on.
    expect(statusBucket(monitored, NOW, { completed: true })).toBe('monitored');
  });

  it('brackets the day and the soon window at their exact edges', () => {
    const endOfDay = new Date(NOW);
    endOfDay.setHours(23, 59, 59, 999);
    const atMidnight = task({ id: 'eod', next_due: endOfDay.toISOString() });
    const justAfter = task({
      id: 'eod2',
      next_due: new Date(endOfDay.getTime() + 1).toISOString(),
    });
    expect(statusBucket(atMidnight, NOW)).toBe('today');
    expect(statusBucket(justAfter, NOW)).toBe('soon');
    // Due at exactly "now" is already overdue, not today.
    expect(statusBucket(task({ id: 'nw', next_due: new Date(NOW).toISOString() }), NOW)).toBe(
      'overdue',
    );
    // SOON_DAYS away to the millisecond is still soon; a millisecond past it is later.
    const soonEdge = task({ id: 'se', next_due: new Date(NOW + SOON_DAYS * DAY).toISOString() });
    const pastEdge = task({
      id: 'pe',
      next_due: new Date(NOW + SOON_DAYS * DAY + 1).toISOString(),
    });
    expect(statusBucket(soonEdge, NOW)).toBe('soon');
    expect(statusBucket(pastEdge, NOW)).toBe('later');
  });

  it('counts a day in milliseconds', () => {
    expect(DAY_MS).toBe(86_400_000);
    expect(SOON_DAYS).toBe(7);
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

  it('shopping keeps only tasks with source.buy', () => {
    const buyTask = task({ id: 'b', name: 'Buy filter', recurrence_type: 'one-off', source: { buy: { asset_id: 'a1', part_id: 'p1' } } });
    const list = [...all, buyTask];
    const ids = filterTasks(list, { type: '', filter: 'shopping' }, {}, NOW).map((t) => t.id);
    expect(ids).toEqual(['b']);
  });

  it('ignores horizon_days for the shopping filter', () => {
    const datedBuy = task({ id: 'db', name: 'Buy dated', next_due: new Date(NOW + DAY).toISOString(), source: { buy: { asset_id: 'a1', part_id: 'p1' } } });
    const undatedBuy = task({ id: 'ub', name: 'Buy undated', source: { buy: { asset_id: 'a1', part_id: 'p1' } } });
    const ids = filterTasks([...all, datedBuy, undatedBuy], { type: '', filter: 'shopping', horizon_days: 1 }, {}, NOW)
      .map((t) => t.id)
      .sort();
    expect(ids).toEqual(['db', 'ub']);
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

  it('gives buy reminders a Shopping section, right under Overdue', () => {
    setLanguage('en');
    const buy = task({
      id: 'buy',
      name: 'Buy filter',
      recurrence_type: 'one-off',
      next_due: new Date(NOW - 3 * DAY).toISOString(),
      source: { buy: { asset_id: 'a1', part_id: 'p1' } },
    });
    const groups = groupTasks([later, overdue, buy, soon], 'status', {}, {}, NOW);
    expect(groups.map((g) => g.key)).toEqual([
      'status:overdue',
      'status:shopping',
      'status:soon',
      'status:later',
    ]);
    expect(groups.find((g) => g.key === 'status:shopping').label).toBe('Shopping');
    // The point of the change: it is no longer sitting in Overdue.
    expect(groups.find((g) => g.key === 'status:overdue').items.map((t) => t.id)).toEqual([
      overdue.id,
    ]);
    expect(groups.find((g) => g.key === 'status:shopping').items.map((t) => t.id)).toEqual([
      'buy',
    ]);
  });

  it('groups by device, and sinks a device the registry lost into "No device" (#262)', () => {
    setLanguage('en');
    const devices = { d1: { id: 'd1', name: 'Water heater' } };
    const known = { ...overdue, id: 'k', device_id: 'd1' };
    // The card renders a task whose device has left the registry — a removed
    // integration, a deleted device. It used to head a section with the raw id.
    const lost = { ...soon, id: 'l', device_id: 'ffffffffffffffffffffffffffffffff' };
    const none = { ...later, id: 'n', device_id: null };
    // Present in the registry but with no name at all — an empty label would head a
    // section with nothing in it, so this belongs in the fallback too.
    const nameless = { ...later, id: 'm', device_id: 'd2' };
    devices.d2 = { id: 'd2' };

    const groups = groupTasks([known, lost, none, nameless], 'device', {}, devices, NOW);
    const byKey = Object.fromEntries(groups.map((g) => [g.key, g]));

    expect(byKey['device:d1'].label).toBe('Water heater');
    expect(byKey['device:d1'].items.map((t) => t.id)).toEqual(['k']);
    // The unknown device, the nameless one and the no-device task share the fallback,
    // and no section is headed by an id or by nothing.
    expect(byKey['device:none'].items.map((t) => t.id).sort()).toEqual(['l', 'm', 'n']);
    for (const g of groups) expect(g.label).not.toBe('');
    expect(groups.map((g) => g.label)).not.toContain('ffffffffffffffffffffffffffffffff');
    for (const g of groups) expect(g.label).not.toMatch(/[0-9a-f]{32}/);
  });

  it('groups by area with a fallback bucket sunk to the bottom', () => {
    const areas = { kitchen: { area_id: 'kitchen', name: 'Kitchen' } };
    const k = task({ id: 'k', area_id: 'kitchen', next_due: new Date(NOW + DAY).toISOString() });
    const groups = groupTasks([k, undated], 'area', areas, {}, NOW);
    expect(groups[0].label).toBe('Kitchen');
    expect(groups[groups.length - 1].key).toBe('area:none');
  });
});

// The generic bucketing primitive under groupTasks — and under the panel's own
// grouping, which buckets appliances (not tasks) with it.
describe('bucketByKey', () => {
  const rows = [
    { id: 'a', room: 'kitchen' },
    { id: 'b', room: 'attic' },
    { id: 'c' }, // no key at all
    { id: 'd', room: '' }, // an empty key is the same "no key" case
    { id: 'e', room: 'kitchen' },
  ];

  it('namespaces keys, labels each section and keeps arrival order within a bucket', () => {
    const groups = bucketByKey(rows, (r) => r.room, (k) => `Room ${k}`, 'No room', 'room');
    expect(groups.map((g) => g.key)).toEqual(['room:attic', 'room:kitchen', 'room:none']);
    expect(groups.map((g) => g.label)).toEqual(['Room attic', 'Room kitchen', 'No room']);
    // Both the undefined key and the empty one land in the fallback bucket.
    expect(groups.map((g) => g.items.map((r) => r.id))).toEqual([['b'], ['a', 'e'], ['c', 'd']]);
  });

  it('sorts sections alphabetically with the fallback last, whatever order they arrive in', () => {
    const groups = bucketByKey(
      [{ k: 'zebra' }, { k: undefined }, { k: 'apple' }],
      (r) => r.k,
      (k) => k,
      'None',
      'x',
    );
    expect(groups.map((g) => g.key)).toEqual(['x:apple', 'x:zebra', 'x:none']);
    expect(groups.map((g) => g.label)).toEqual(['apple', 'zebra', 'None']);
  });

  it('returns no sections for no items', () => {
    expect(bucketByKey([], () => undefined, (k) => k, 'None', 'x')).toEqual([]);
  });
});

describe('groupTasks (area fallback)', () => {
  it('groups by area with a fallback bucket sunk to the bottom', () => {
    const areas = { kitchen: { area_id: 'kitchen', name: 'Kitchen' } };
    const k = task({ id: 'k', area_id: 'kitchen', next_due: new Date(NOW + DAY).toISOString() });
    const groups = groupTasks([k, undated], 'area', areas, {}, NOW);
    expect(groups[0].label).toBe('Kitchen');
    expect(groups[groups.length - 1].key).toBe('area:none');
  });
});

describe('profileMatches (saved-filter predicate)', () => {
  const F = (over = {}) => ({ status: 'overdue', labels: [], areas: [], devices: [], ...over });

  it('honors status: overdue / due_soon / all', () => {
    expect(profileMatches(overdue, F({ status: 'overdue' }), {}, {}, NOW)).toBe(true);
    expect(profileMatches(soon, F({ status: 'overdue' }), {}, {}, NOW)).toBe(false);
    expect(profileMatches(soon, F({ status: 'due_soon' }), {}, {}, NOW)).toBe(true);
    expect(profileMatches(overdue, F({ status: 'due_soon' }), {}, {}, NOW)).toBe(true);
    expect(profileMatches(later, F({ status: 'due_soon' }), {}, {}, NOW)).toBe(false);
    expect(profileMatches(later, F({ status: 'all' }), {}, {}, NOW)).toBe(true);
  });

  it('excludes disabled and dormant tasks, but not an armed problem sensor (#248)', () => {
    expect(profileMatches(task({ next_due: new Date(NOW - DAY).toISOString(), enabled: false }), F({ status: 'all' }), {}, {}, NOW)).toBe(false);
    expect(profileMatches(task({ next_due: null }), F({ status: 'all' }), {}, {}, NOW)).toBe(false);
    expect(profileMatches(task({ next_due: new Date(NOW - DAY).toISOString(), source: { problem_sensor: { entity_id: 'x' } } }), F({ status: 'all' }), {}, {}, NOW)).toBe(true);
    // Dormant (sensor back to OK) is undated, so the rule above still drops it.
    expect(profileMatches(task({ next_due: null, source: { problem_sensor: { entity_id: 'x' } } }), F({ status: 'all' }), {}, {}, NOW)).toBe(false);
  });

  it('matches own labels and inherited (device/area) labels', () => {
    const own = task({ next_due: new Date(NOW - DAY).toISOString(), labels: ['dog'] });
    expect(profileMatches(own, F({ status: 'all', labels: ['dog'] }), {}, {}, NOW)).toBe(true);
    expect(profileMatches(own, F({ status: 'all', labels: ['cat'] }), {}, {}, NOW)).toBe(false);
    // Inherited from the task's device label.
    const viaDevice = task({ next_due: new Date(NOW - DAY).toISOString(), device_id: 'd1' });
    const devices = { d1: { area_id: 'kitchen', labels: ['dog'] } };
    expect(profileMatches(viaDevice, F({ status: 'all', labels: ['dog'] }), devices, {}, NOW)).toBe(true);
    expect(profileMatches(viaDevice, F({ status: 'all', areas: ['kitchen'] }), devices, {}, NOW)).toBe(true);
  });
});

describe('profileMatches conformance (shared backend/frontend fixture)', () => {
  const defaultNow = new Date(CONFORMANCE.now).getTime();
  for (const c of CONFORMANCE.cases) {
    it(c.name, () => {
      const now = c.now ? new Date(c.now).getTime() : defaultNow;
      // Empty registries: tasks carry their effective ids directly, matching how the
      // backend enriches before calling the pure matcher.
      expect(profileMatches(c.task, c.filter, {}, {}, now)).toBe(c.expected);
    });
  }
});
