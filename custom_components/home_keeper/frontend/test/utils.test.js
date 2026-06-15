import { describe, it, expect } from 'vitest';
import {
  escapeHTML,
  recurrenceSummary,
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
} from '../src/utils.ts';

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
  it('joins make/model, area and warranty', () => {
    expect(
      assetSummary(
        {
          id: 'a',
          kind: 'virtual',
          name: 'Fridge',
          manufacturer: 'LG',
          model: 'X1',
          area_id: 'kitchen',
          warranty_expiry: '2030-01-01',
        },
        areas,
      ),
    ).toBe('LG X1 · Kitchen · warranty to 2030-01-01');
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
