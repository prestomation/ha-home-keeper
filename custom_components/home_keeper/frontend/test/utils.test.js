import { afterEach, describe, it, expect, vi } from 'vitest';
import {
  escapeHTML,
  randomId,
  recurrenceSummary,
  isArmedTriggered,
  isOverdue,
  dueLabel,
  deviceName,
  deviceDomain,
  brandLogoUrl,
  areaName,
  assetSummary,
  sortedCompletions,
  completionStats,
  taskRelatesToAsset,
  tasksForAsset,
  parseRoute,
  buildPath,
} from '../src/utils.ts';

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('randomId', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses crypto.randomUUID when available (secure context)', () => {
    const fake = '11111111-2222-4333-8444-555555555555';
    vi.stubGlobal('crypto', { randomUUID: () => fake });
    expect(randomId()).toBe(fake);
  });

  it('falls back to a v4 uuid when randomUUID is absent (plain-HTTP LAN)', () => {
    // Over a non-secure origin (http://192.168.x.x) crypto.randomUUID is undefined;
    // getRandomValues still exists, so we build a valid v4 instead of throwing.
    vi.stubGlobal('crypto', {
      getRandomValues: (arr) => {
        for (let i = 0; i < arr.length; i += 1) arr[i] = (i * 37 + 11) & 0xff;
        return arr;
      },
    });
    const id = randomId();
    expect(id).toMatch(UUID_V4);
  });

  it('falls back to Math.random when crypto is entirely absent', () => {
    vi.stubGlobal('crypto', undefined);
    expect(randomId()).toMatch(UUID_V4);
  });
});

describe('escapeHTML', () => {
  it('escapes HTML-significant characters', () => {
    expect(escapeHTML('<b>"x" & \'y\'</b>')).toBe(
      '&lt;b&gt;&quot;x&quot; &amp; &#39;y&#39;&lt;/b&gt;',
    );
  });
  it('handles null/undefined', () => {
    expect(escapeHTML(null)).toBe('');
    expect(escapeHTML(undefined)).toBe('');
  });
});

describe('recurrenceSummary', () => {
  it('describes floating tasks relative to completion', () => {
    expect(
      recurrenceSummary({ recurrence_type: 'floating', interval: 1, unit: 'months' }),
    ).toBe('every month after completion');
    expect(
      recurrenceSummary({ recurrence_type: 'floating', interval: 3, unit: 'months' }),
    ).toBe('every 3 months after completion');
  });
  it('describes fixed tasks by frequency', () => {
    expect(recurrenceSummary({ recurrence_type: 'fixed', interval: 1, freq: 'DAILY' })).toBe(
      'every day',
    );
    expect(recurrenceSummary({ recurrence_type: 'fixed', interval: 2, freq: 'WEEKLY' })).toBe(
      'every 2 weeks',
    );
  });
  it('describes triggered tasks as monitored (no schedule)', () => {
    // Both armed and dormant triggered tasks summarize the same way — they have
    // no recurrence rule, only a monitored condition.
    expect(recurrenceSummary({ recurrence_type: 'triggered' })).toBe(
      'Monitored (condition-driven)',
    );
    expect(
      recurrenceSummary({ recurrence_type: 'triggered', next_due: '2026-06-01T00:00:00Z' }),
    ).toBe('Monitored (condition-driven)');
  });
});

describe('isArmedTriggered', () => {
  it('is true only for a triggered task with a next_due (armed/due)', () => {
    expect(isArmedTriggered({ recurrence_type: 'triggered', next_due: '2026-06-01T00:00:00Z' })).toBe(
      true,
    );
  });
  it('is false for a dormant triggered task and for non-triggered tasks', () => {
    expect(isArmedTriggered({ recurrence_type: 'triggered' })).toBe(false);
    expect(isArmedTriggered({ recurrence_type: 'triggered', next_due: null })).toBe(false);
    expect(isArmedTriggered({ recurrence_type: 'floating', next_due: '2026-06-01T00:00:00Z' })).toBe(
      false,
    );
  });
});

describe('isOverdue', () => {
  const now = new Date('2026-06-13T12:00:00Z');
  it('is true when next_due is in the past', () => {
    expect(isOverdue({ next_due: '2026-06-01T00:00:00Z' }, now)).toBe(true);
  });
  it('is false when next_due is in the future', () => {
    expect(isOverdue({ next_due: '2026-07-01T00:00:00Z' }, now)).toBe(false);
  });
  it('is false when next_due missing', () => {
    expect(isOverdue({}, now)).toBe(false);
  });
});

describe('dueLabel', () => {
  const now = new Date('2026-06-13T12:00:00Z');
  it('renders relative day labels', () => {
    expect(dueLabel({ next_due: '2026-06-13T18:00:00Z' }, now)).toBe('today');
    expect(dueLabel({ next_due: '2026-06-14T12:00:00Z' }, now)).toBe('tomorrow');
    expect(dueLabel({ next_due: '2026-06-16T12:00:00Z' }, now)).toBe('in 3 days');
    expect(dueLabel({ next_due: '2026-06-12T12:00:00Z' }, now)).toBe('yesterday');
  });
  it('labels a dormant triggered task as Monitored', () => {
    expect(dueLabel({ recurrence_type: 'triggered' }, now)).toBe('Monitored');
    expect(dueLabel({ recurrence_type: 'triggered', next_due: null }, now)).toBe('Monitored');
  });
});

describe('deviceName', () => {
  const devices = {
    abc: { id: 'abc', name: 'Fridge', name_by_user: 'Kitchen fridge' },
    def: { id: 'def', name: 'Furnace', name_by_user: null },
  };
  it('prefers name_by_user', () => {
    expect(deviceName(devices, 'abc')).toBe('Kitchen fridge');
  });
  it('falls back to name', () => {
    expect(deviceName(devices, 'def')).toBe('Furnace');
  });
  it('returns id for unknown device, empty for none', () => {
    expect(deviceName(devices, 'zzz')).toBe('zzz');
    expect(deviceName(devices, null)).toBe('');
  });
});

describe('deviceDomain', () => {
  const entryDomains = { e1: 'hue', e2: 'mqtt' };
  it('resolves via primary_config_entry', () => {
    expect(deviceDomain({ primary_config_entry: 'e1' }, entryDomains)).toBe('hue');
  });
  it('falls back to the first config entry', () => {
    expect(deviceDomain({ config_entries: ['e2'] }, entryDomains)).toBe('mqtt');
  });
  it('returns undefined when unresolvable', () => {
    expect(deviceDomain({ primary_config_entry: 'zzz' }, entryDomains)).toBeUndefined();
    expect(deviceDomain(undefined, entryDomains)).toBeUndefined();
    expect(deviceDomain({ primary_config_entry: 'e1' }, undefined)).toBeUndefined();
  });
});

describe('brandLogoUrl', () => {
  it('builds the brand icon URL for a domain', () => {
    expect(brandLogoUrl('hue')).toBe('https://brands.home-assistant.io/hue/icon.png');
  });
  it('uses the generic fallback path', () => {
    expect(brandLogoUrl('hue', true)).toBe('https://brands.home-assistant.io/_/hue/icon.png');
  });
});

describe('areaName', () => {
  const areas = { kitchen: { area_id: 'kitchen', name: 'Kitchen' } };
  it('resolves an area name', () => {
    expect(areaName(areas, 'kitchen')).toBe('Kitchen');
  });
  it('returns the id for an unknown area and empty for none', () => {
    expect(areaName(areas, 'garage')).toBe('garage');
    expect(areaName(areas, null)).toBe('');
  });
});

describe('assetSummary', () => {
  const areas = { kitchen: { area_id: 'kitchen', name: 'Kitchen' } };
  it('joins make/model and area', () => {
    expect(
      assetSummary(
        {
          id: 'a',
          kind: 'virtual',
          name: 'Fridge',
          manufacturer: 'LG',
          model: 'X1',
          area_id: 'kitchen',
        },
        areas,
      ),
    ).toBe('LG X1 · Kitchen');
  });
  it('falls back when there are no details', () => {
    expect(assetSummary({ id: 'a', kind: 'virtual', name: 'Fridge' })).toBe('No details yet');
  });
});

describe('sortedCompletions', () => {
  it('parses and sorts timestamps newest-first, dropping invalid ones', () => {
    const out = sortedCompletions([
      { ts: '2026-01-01T00:00:00Z' },
      { ts: 'not-a-date' },
      { ts: '2026-03-01T00:00:00Z' },
      { ts: '2026-02-01T00:00:00Z' },
    ]);
    expect(out.map((d) => d.toISOString().slice(0, 10))).toEqual([
      '2026-03-01',
      '2026-02-01',
      '2026-01-01',
    ]);
  });
  it('handles empty/undefined', () => {
    expect(sortedCompletions()).toEqual([]);
    expect(sortedCompletions([])).toEqual([]);
  });
});

describe('completionStats', () => {
  it('reports count, last, and average cadence in days', () => {
    const s = completionStats([
      { ts: '2026-01-01T00:00:00Z' },
      { ts: '2026-01-31T00:00:00Z' },
      { ts: '2026-03-02T00:00:00Z' },
    ]);
    expect(s.count).toBe(3);
    expect(s.last.toISOString().slice(0, 10)).toBe('2026-03-02');
    expect(s.avgIntervalDays).toBe(30); // (30 + 30) / 2
  });
  it('omits cadence for a single completion', () => {
    const s = completionStats([{ ts: '2026-01-01T00:00:00Z' }]);
    expect(s.count).toBe(1);
    expect(s.avgIntervalDays).toBeUndefined();
  });
  it('reports zero for no completions', () => {
    expect(completionStats([]).count).toBe(0);
  });
});

describe('taskRelatesToAsset / tasksForAsset', () => {
  const asset = {
    id: 'asset1',
    kind: 'virtual',
    name: 'Heater',
    device_id: 'dev1',
    related_device_ids: ['dev2'],
  };
  it('matches a part-derived task by asset id', () => {
    const task = { id: 't', name: 'x', source: { part: { asset_id: 'asset1', part_id: 'p' } } };
    expect(taskRelatesToAsset(task, asset)).toBe(true);
  });
  it("matches a task attached to the appliance's device", () => {
    expect(taskRelatesToAsset({ id: 't', name: 'x', device_id: 'dev1' }, asset)).toBe(true);
  });
  it('matches a task on a related device', () => {
    expect(taskRelatesToAsset({ id: 't', name: 'x', device_id: 'dev2' }, asset)).toBe(true);
  });
  it('does not match an unrelated standalone task', () => {
    expect(taskRelatesToAsset({ id: 't', name: 'x', device_id: 'other' }, asset)).toBe(false);
    expect(taskRelatesToAsset({ id: 't', name: 'x' }, asset)).toBe(false);
  });
  it('tasksForAsset filters the list', () => {
    const tasks = [
      { id: 'a', name: 'a', device_id: 'dev1' },
      { id: 'b', name: 'b', device_id: 'nope' },
      { id: 'c', name: 'c', source: { part: { asset_id: 'asset1', part_id: 'p' } } },
    ];
    expect(tasksForAsset(asset, tasks).map((t) => t.id)).toEqual(['a', 'c']);
  });
});

describe('parseRoute', () => {
  it('defaults empty/unknown paths to the tasks list', () => {
    for (const p of ['', '/', undefined, null, '/bogus']) {
      expect(parseRoute(p)).toEqual({ view: 'tasks', detail: null });
    }
  });
  it('parses the appliances list', () => {
    expect(parseRoute('/appliances')).toEqual({ view: 'appliances', detail: null });
  });
  it('parses a task detail', () => {
    expect(parseRoute('/tasks/abc')).toEqual({
      view: 'tasks',
      detail: { kind: 'task', id: 'abc' },
    });
  });
  it('parses an asset detail under the appliances segment', () => {
    expect(parseRoute('/appliances/xyz')).toEqual({
      view: 'appliances',
      detail: { kind: 'asset', id: 'xyz' },
    });
  });
  it('decodes percent-encoded ids and tolerates trailing slashes', () => {
    expect(parseRoute('/tasks/a%2Fb/')).toEqual({
      view: 'tasks',
      detail: { kind: 'task', id: 'a/b' },
    });
  });
});

describe('buildPath', () => {
  it('builds list paths', () => {
    expect(buildPath({ view: 'tasks', detail: null })).toBe('/tasks');
    expect(buildPath({ view: 'appliances', detail: null })).toBe('/appliances');
  });
  it('builds detail paths and encodes the id', () => {
    expect(buildPath({ view: 'tasks', detail: { kind: 'task', id: 'a/b' } })).toBe('/tasks/a%2Fb');
    expect(buildPath({ view: 'appliances', detail: { kind: 'asset', id: 'x' } })).toBe(
      '/appliances/x',
    );
  });
  it('round-trips with parseRoute', () => {
    const locs = [
      { view: 'tasks', detail: null },
      { view: 'appliances', detail: null },
      { view: 'tasks', detail: { kind: 'task', id: 'task-1' } },
      { view: 'appliances', detail: { kind: 'asset', id: 'asset-9' } },
    ];
    for (const loc of locs) {
      expect(parseRoute(buildPath(loc))).toEqual(loc);
    }
  });
});
