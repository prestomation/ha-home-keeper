import { afterEach, describe, it, expect, vi } from 'vitest';
import {
  escapeHTML,
  formatQuantity,
  isHttpUrl,
  isSafeImageUrl,
  safeFileHref,
  safeHref,
  randomId,
  recurrenceSummary,
  isArmedTriggered,
  isOverdue,
  dueLabel,
  meterRemaining,
  taskRecordsReading,
  readingUnit,
  btnAttrs,
  deviceName,
  formatDate,
  formatDateTime,
  setBtnWeight,
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
  buildAssetTree,
  ASSET_TABS,
  DEFAULT_ASSET_TAB,
  SETTINGS_SECTIONS,
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

describe('href/image URL guards', () => {
  it('isHttpUrl accepts only http(s)', () => {
    expect(isHttpUrl('http://x')).toBe(true);
    expect(isHttpUrl('https://x')).toBe(true);
    expect(isHttpUrl('javascript:alert(1)')).toBe(false);
    expect(isHttpUrl('/api/image/serve/a')).toBe(false);
    expect(isHttpUrl(undefined)).toBe(false);
  });

  it('safeHref returns escaped http(s) or empty for unsafe', () => {
    expect(safeHref('https://x/a?b=1&c=2')).toBe('https://x/a?b=1&amp;c=2');
    expect(safeHref('javascript:alert(1)')).toBe('');
    expect(safeHref('data:text/html,<script>')).toBe('');
  });

  it('isSafeImageUrl allows http(s) and site-relative, blocks scripts', () => {
    expect(isSafeImageUrl('https://x/y.jpg')).toBe(true);
    expect(isSafeImageUrl('/api/image/serve/abc/original')).toBe(true);
    expect(isSafeImageUrl('javascript:alert(1)')).toBe(false);
    expect(isSafeImageUrl('data:text/html,<script>')).toBe(false);
    expect(isSafeImageUrl('//evil.com/x')).toBe(false); // protocol-relative
  });

  it('safeFileHref keeps signed site-relative URLs that safeHref would blank', () => {
    // Document and part-file anchors carry a server-minted signed path; the
    // http(s)-only guard would render every one of them inert.
    const signed = '/api/home_keeper/document/a1/d2?authSig=abc.def';
    expect(safeFileHref(signed)).toBe(signed);
    expect(safeHref(signed)).toBe('');
    expect(safeFileHref('https://example.com/manual.pdf')).toBe(
      'https://example.com/manual.pdf',
    );
  });

  it('safeFileHref still blanks script and protocol-relative URLs', () => {
    expect(safeFileHref('javascript:alert(1)')).toBe('');
    expect(safeFileHref('data:text/html,<script>')).toBe('');
    expect(safeFileHref('vbscript:msgbox(1)')).toBe('');
    expect(safeFileHref('//evil.com/x')).toBe('');
    expect(safeFileHref(undefined)).toBe('');
  });

  it('safeFileHref escapes the value it returns', () => {
    // A quote that survived into an href would let the attribute be closed early.
    expect(safeFileHref('/api/f?a=1&b="x"')).toBe('/api/f?a=1&amp;b=&quot;x&quot;');
  });
});

describe('formatQuantity', () => {
  it('keeps a whole count bare', () => {
    expect(formatQuantity(3)).toBe('3');
    expect(formatQuantity(3, '')).toBe('3');
    expect(formatQuantity(3, null)).toBe('3');
    expect(formatQuantity(0)).toBe('0');
  });

  it('appends the part unit when it has one', () => {
    expect(formatQuantity(250, 'ml')).toBe('250 ml');
    expect(formatQuantity(0.5, ' bottles ')).toBe('0.5 bottles');
  });

  it('drops trailing zeros and float noise', () => {
    expect(formatQuantity(1.5)).toBe('1.5');
    expect(formatQuantity(2.0)).toBe('2');
    expect(formatQuantity(0.1 + 0.2)).toBe('0.3');
    expect(formatQuantity(1.23456)).toBe('1.235');
  });
});

describe('recurrenceSummary', () => {
  it('describes floating tasks relative to completion', () => {
    expect(
      recurrenceSummary({ recurrence_type: 'floating', interval: 1, unit: 'months' }),
    ).toBe('Every month after completion');
    expect(
      recurrenceSummary({ recurrence_type: 'floating', interval: 3, unit: 'months' }),
    ).toBe('Every 3 months after completion');
  });
  it('describes fixed tasks by frequency', () => {
    expect(recurrenceSummary({ recurrence_type: 'fixed', interval: 1, freq: 'DAILY' })).toBe(
      'Every day',
    );
    expect(recurrenceSummary({ recurrence_type: 'fixed', interval: 2, freq: 'WEEKLY' })).toBe(
      'Every 2 weeks',
    );
  });
  it('describes triggered tasks as monitored (no schedule)', () => {
    // Both armed and dormant triggered tasks summarize the same way — they have
    // no recurrence rule, only a monitored condition.
    expect(recurrenceSummary({ recurrence_type: 'triggered' })).toBe('Monitored');
    expect(
      recurrenceSummary({ recurrence_type: 'triggered', next_due: '2026-06-01T00:00:00Z' }),
    ).toBe('Monitored');
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
  it('reads a dormant usage meter as a live countdown "in X units"', () => {
    // 45,000-start, every 10,000 mi, odometer now at 48,000 → 7,000 to go.
    const task = {
      recurrence_type: 'sensor',
      sensor: {
        entity_id: 'sensor.odometer',
        mode: 'usage',
        target: 10000,
        baseline: 45000,
        unit: 'miles',
      },
    };
    const hass = { states: { 'sensor.odometer': { state: '48000' } } };
    expect(dueLabel(task, now, hass)).toBe('in 7000 miles');
  });
  it('falls back to the entity unit_of_measurement when the binding has no unit', () => {
    const task = {
      recurrence_type: 'sensor',
      sensor: { entity_id: 'sensor.hours', mode: 'usage', target: 300, baseline: 100 },
    };
    const hass = {
      states: { 'sensor.hours': { state: '150', attributes: { unit_of_measurement: 'h' } } },
    };
    expect(dueLabel(task, now, hass)).toBe('in 250 h');
  });
  it('omits the unit entirely when neither the binding nor the entity supplies one', () => {
    const task = {
      recurrence_type: 'sensor',
      sensor: { entity_id: 'sensor.bare', mode: 'usage', target: 300, baseline: 100 },
    };
    const hass = { states: { 'sensor.bare': { state: '150' } } };
    expect(dueLabel(task, now, hass)).toBe('in 250');
  });
  it('stays Monitored for a usage meter with no live reading or no hass', () => {
    const task = {
      recurrence_type: 'sensor',
      sensor: { entity_id: 'sensor.odometer', mode: 'usage', target: 10000, baseline: 45000 },
    };
    expect(dueLabel(task, now)).toBe('Monitored');
    expect(dueLabel(task, now, { states: {} })).toBe('Monitored');
    expect(
      dueLabel(task, now, { states: { 'sensor.odometer': { state: 'unavailable' } } }),
    ).toBe('Monitored');
  });
  it('stays Monitored for a threshold/state sensor task or an un-anchored meter', () => {
    const hass = { states: { 'sensor.x': { state: '95' } } };
    expect(
      dueLabel(
        { recurrence_type: 'sensor', sensor: { entity_id: 'sensor.x', mode: 'threshold' } },
        now,
        hass,
      ),
    ).toBe('Monitored');
    // usage mode but no baseline yet (freshly created, watcher hasn't anchored).
    expect(
      dueLabel(
        { recurrence_type: 'sensor', sensor: { entity_id: 'sensor.x', mode: 'usage', target: 50 } },
        now,
        hass,
      ),
    ).toBe('Monitored');
  });
  it('counts calendar days, not rolling 24h windows, at time-of-day boundaries', () => {
    // Local dates so the assertion holds regardless of the test runner's timezone
    // (dueLabel's day diff is computed from local midnights).
    const evening = new Date(2026, 5, 13, 20, 0, 0); // 8pm June 13, local
    // Due 8am the *next* calendar day is only 12h out — a rolling-24h round would
    // read "today"; a calendar-day diff correctly reads "tomorrow".
    expect(dueLabel({ next_due: new Date(2026, 5, 14, 8, 0, 0).toISOString() }, evening)).toBe(
      'tomorrow',
    );
    // Still the same calendar day → "today".
    expect(dueLabel({ next_due: new Date(2026, 5, 13, 23, 0, 0).toISOString() }, evening)).toBe(
      'today',
    );
    // Yesterday evening from this morning is <24h ago but a day earlier → "yesterday".
    const morning = new Date(2026, 5, 13, 8, 0, 0);
    expect(dueLabel({ next_due: new Date(2026, 5, 12, 20, 0, 0).toISOString() }, morning)).toBe(
      'yesterday',
    );
  });
});

describe('meterRemaining', () => {
  const usage = (over = {}) => ({
    recurrence_type: 'sensor',
    sensor: { entity_id: 'sensor.m', mode: 'usage', target: 100, baseline: 20, ...over },
  });
  const at = (v) => ({ states: { 'sensor.m': { state: String(v) } } });

  it('returns target minus consumed', () => {
    expect(meterRemaining(usage(), at(50))).toBe(70); // 100 - (50 - 20)
  });
  it('clamps consumed at 0 when the reading is below the baseline (meter reset)', () => {
    expect(meterRemaining(usage(), at(10))).toBe(100); // consumed can't go negative
  });
  it('clamps remaining at 0 when consumption has passed the target', () => {
    expect(meterRemaining(usage(), at(200))).toBe(0);
  });
  it('reads an attribute when the binding names one', () => {
    const task = usage({ attribute: 'liters' });
    const hass = { states: { 'sensor.m': { state: '5', attributes: { liters: 60 } } } };
    expect(meterRemaining(task, hass)).toBe(60); // 100 - (60 - 20)
  });
  it('is null when the named attribute is absent', () => {
    const task = usage({ attribute: 'liters' });
    const hass = { states: { 'sensor.m': { state: '5', attributes: {} } } };
    expect(meterRemaining(task, hass)).toBeNull();
  });
  it('is null for a non-sensor task even if it carries a sensor binding', () => {
    // Exercises the recurrence_type guard specifically (the binding is present).
    expect(meterRemaining({ ...usage(), recurrence_type: 'floating' }, at(50))).toBeNull();
  });
  it('is null for a threshold-mode sensor task', () => {
    expect(meterRemaining(usage({ mode: 'threshold' }), at(50))).toBeNull();
  });
  it('is null for a null task or an absent binding', () => {
    expect(meterRemaining(null, at(50))).toBeNull();
    expect(meterRemaining({ recurrence_type: 'sensor' }, at(50))).toBeNull();
  });
  it('is null without a numeric target or a numeric baseline', () => {
    expect(meterRemaining(usage({ target: undefined }), at(50))).toBeNull();
    expect(meterRemaining(usage({ baseline: undefined }), at(50))).toBeNull();
  });
  it('is null when hass, its states map, or the entity are missing', () => {
    expect(meterRemaining(usage())).toBeNull(); // no hass at all
    expect(meterRemaining(usage(), {})).toBeNull(); // hass but no states map
    expect(meterRemaining(usage(), { states: {} })).toBeNull(); // entity not in states
  });
  it('is null when the reading is empty, absent, or non-numeric', () => {
    expect(meterRemaining(usage(), at(''))).toBeNull(); // empty-string state
    expect(meterRemaining(usage(), { states: { 'sensor.m': {} } })).toBeNull(); // no state prop
    expect(meterRemaining(usage(), at('unavailable'))).toBeNull(); // non-numeric
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
  it('is empty for an unknown device and for none (#262)', () => {
    expect(deviceName(devices, 'zzz')).toBe('');
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
    // No sub-tab in the URL resolves to the default one, so every `/appliances/<id>`
    // link minted before sub-tabs existed — including the `configuration_url` already
    // written onto registered appliance devices — still lands somewhere real.
    expect(parseRoute('/appliances/xyz')).toEqual({
      view: 'appliances',
      detail: { kind: 'asset', id: 'xyz', tab: 'parts' },
    });
  });
  it('parses each appliance sub-tab from the third segment', () => {
    for (const tab of ASSET_TABS) {
      expect(parseRoute(`/appliances/xyz/${tab}`)).toEqual({
        view: 'appliances',
        detail: { kind: 'asset', id: 'xyz', tab },
      });
    }
  });
  it('falls back to the default sub-tab for an unknown one', () => {
    // A hand-typed or stale URL should open the appliance, not nothing.
    for (const bogus of ['nope', 'PARTS', '', 'documents2']) {
      expect(parseRoute(`/appliances/xyz/${bogus}`).detail).toEqual({
        kind: 'asset',
        id: 'xyz',
        tab: DEFAULT_ASSET_TAB,
      });
    }
  });
  it('does not give a task detail a sub-tab', () => {
    // Only appliances have sub-tabs; a third segment on a task path is not one.
    expect(parseRoute('/tasks/abc/documents')).toEqual({
      view: 'tasks',
      detail: { kind: 'task', id: 'abc' },
    });
  });
  it('decodes percent-encoded ids and tolerates trailing slashes', () => {
    expect(parseRoute('/tasks/a%2Fb/')).toEqual({
      view: 'tasks',
      detail: { kind: 'task', id: 'a/b' },
    });
  });
  it('decodes a percent-encoded section or sub-tab before matching it', () => {
    // The segment is decoded and *then* matched, so an encoder that escaped a letter
    // still lands on the section it named rather than silently on the fallback.
    expect(parseRoute('/settings/%70rofiles').section).toBe('profiles');
    expect(parseRoute('/appliances/x/%68istory').detail).toEqual({
      kind: 'asset',
      id: 'x',
      tab: 'history',
    });
  });
  it('trims whitespace around every segment', () => {
    // A hand-typed or copy-pasted URL can carry stray space around a segment, and a
    // segment that only looks like `settings` resolves to nothing at all.
    expect(parseRoute(' /settings / problem ')).toEqual({
      view: 'settings',
      detail: null,
      section: 'problem',
    });
    expect(parseRoute('/ appliances / xyz / history ').detail).toEqual({
      kind: 'asset',
      id: 'xyz',
      tab: 'history',
    });
  });
  it('parses each settings section from the second segment', () => {
    for (const section of SETTINGS_SECTIONS) {
      expect(parseRoute(`/settings/${section}`)).toEqual({
        view: 'settings',
        detail: null,
        section,
      });
    }
  });
  it('reads a bare /settings as the section index, with no section', () => {
    // Unlike an appliance sub-tab there is no default: the index is a destination in
    // its own right, so no section is a state rather than a gap to fill in.
    expect(parseRoute('/settings')).toEqual({ view: 'settings', detail: null });
  });
  it('falls back to the section index for an unknown section', () => {
    for (const bogus of ['nope', 'General', 'profiles2', 'tasks']) {
      expect(parseRoute(`/settings/${bogus}`)).toEqual({ view: 'settings', detail: null });
    }
  });
  it('never gives settings a detail page', () => {
    // Settings has sections, not records; a deeper path is still just a section.
    expect(parseRoute('/settings/profiles/abc').detail).toBeNull();
    expect(parseRoute('/settings/profiles/abc').section).toBe('profiles');
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
  it('names a sub-tab in the path, but leaves the default one implicit', () => {
    // `/appliances/x` and `/appliances/x/parts` are the same page, and a link to an
    // appliance should be the short one.
    expect(buildPath({ view: 'appliances', detail: { kind: 'asset', id: 'x', tab: 'parts' } })).toBe(
      '/appliances/x',
    );
    for (const tab of ASSET_TABS.filter((t) => t !== DEFAULT_ASSET_TAB)) {
      expect(
        buildPath({ view: 'appliances', detail: { kind: 'asset', id: 'x', tab } }),
      ).toBe(`/appliances/x/${tab}`);
    }
  });
  it('encodes the id even with a sub-tab after it', () => {
    expect(
      buildPath({ view: 'appliances', detail: { kind: 'asset', id: 'a/b', tab: 'history' } }),
    ).toBe('/appliances/a%2Fb/history');
  });
  it('names a settings section in the path, and the index when there is none', () => {
    expect(buildPath({ view: 'settings', detail: null })).toBe('/settings');
    for (const section of SETTINGS_SECTIONS) {
      expect(buildPath({ view: 'settings', detail: null, section })).toBe(`/settings/${section}`);
    }
  });
  it('round-trips with parseRoute', () => {
    const locs = [
      { view: 'tasks', detail: null },
      { view: 'appliances', detail: null },
      { view: 'settings', detail: null },
      ...SETTINGS_SECTIONS.map((section) => ({ view: 'settings', detail: null, section })),
      { view: 'tasks', detail: { kind: 'task', id: 'task-1' } },
      // An appliance always resolves with a sub-tab, so that is the shape a
      // round-trip has to come back as.
      { view: 'appliances', detail: { kind: 'asset', id: 'asset-9', tab: 'parts' } },
      ...ASSET_TABS.map((tab) => ({
        view: 'appliances',
        detail: { kind: 'asset', id: 'asset-9', tab },
      })),
    ];
    for (const loc of locs) {
      expect(parseRoute(buildPath(loc))).toEqual(loc);
    }
  });
});

// ── the meter-reading helpers (issue #235) ───────────────────────────────────

describe('taskRecordsReading', () => {
  const sensor = (mode, over = {}) => ({
    recurrence_type: 'sensor',
    sensor: { entity_id: 'sensor.odo', mode, ...over },
  });

  it('is true for the numeric modes', () => {
    expect(taskRecordsReading(sensor('usage'))).toBe(true);
    expect(taskRecordsReading(sensor('threshold'))).toBe(true);
  });

  it('is false for state mode — "on" is not a number to log', () => {
    expect(taskRecordsReading(sensor('state'))).toBe(false);
  });

  it('defaults a binding with no mode to usage, matching normalize_sensor', () => {
    expect(taskRecordsReading({ recurrence_type: 'sensor', sensor: { entity_id: 'x' } })).toBe(
      true,
    );
  });

  it('is false for every non-sensor task and for missing input', () => {
    for (const rec of ['floating', 'fixed', 'one-off', 'triggered']) {
      expect(taskRecordsReading({ recurrence_type: rec }), rec).toBe(false);
    }
    expect(taskRecordsReading({ recurrence_type: 'sensor' })).toBe(false);
    expect(taskRecordsReading(null)).toBe(false);
    expect(taskRecordsReading(undefined)).toBe(false);
  });
});

describe('readingUnit', () => {
  const hass = {
    states: {
      'sensor.coolant': { state: '94', attributes: { unit_of_measurement: '°C' } },
      'sensor.bare': { state: '5', attributes: {} },
    },
  };

  it("prefers the usage binding's own unit label", () => {
    const task = {
      sensor: { entity_id: 'sensor.coolant', mode: 'usage', unit: 'h' },
    };
    // The label the user typed wins over the entity's — that is the whole point of
    // the field, and the meter arithmetic is unit-agnostic anyway.
    expect(readingUnit(task, hass)).toBe('h');
  });

  it("falls back to the entity's unit when the binding has none", () => {
    // A threshold binding carries no `unit` at all — it is usage-only in the model.
    const task = { sensor: { entity_id: 'sensor.coolant', mode: 'threshold' } };
    expect(readingUnit(task, hass)).toBe('°C');
  });

  it('returns nothing for an attribute binding', () => {
    // An arbitrary attribute's unit is not described by the entity's own
    // unit_of_measurement, so borrowing it would label the number wrongly.
    const task = {
      sensor: { entity_id: 'sensor.coolant', mode: 'threshold', attribute: 'humidity' },
    };
    expect(readingUnit(task, hass)).toBe('');
  });

  it('returns nothing when there is no task, binding, entity or unit', () => {
    expect(readingUnit(undefined, hass)).toBe('');
    expect(readingUnit({}, hass)).toBe('');
    expect(readingUnit({ sensor: { entity_id: 'sensor.gone' } }, hass)).toBe('');
    expect(readingUnit({ sensor: { entity_id: 'sensor.bare' } }, hass)).toBe('');
    expect(readingUnit({ sensor: { entity_id: 'sensor.coolant' } }, undefined)).toBe('');
  });
});

describe('readingUnit — entities without attributes', () => {
  it('returns nothing when the entity carries no attributes at all', () => {
    const hass = { states: { 'sensor.x': { state: '5' } } };
    expect(readingUnit({ sensor: { entity_id: 'sensor.x' } }, hass)).toBe('');
  });

  it('returns nothing when hass has no states map', () => {
    expect(readingUnit({ sensor: { entity_id: 'sensor.x' } }, {})).toBe('');
  });
});

describe('buildAssetTree', () => {
  const cmp = (a, b) => (a.name || '').localeCompare(b.name || '');
  const asset = (id, name, parent_asset_id = null) => ({ id, name, parent_asset_id });

  it('returns an empty array for empty input', () => {
    expect(buildAssetTree([], cmp)).toEqual([]);
  });

  it('puts all parentless assets at depth 0, sorted', () => {
    const result = buildAssetTree(
      [asset('c', 'Cherry'), asset('a', 'Apple'), asset('b', 'Banana')],
      cmp,
    );
    expect(result.map((e) => [e.item.name, e.depth])).toEqual([
      ['Apple', 0],
      ['Banana', 0],
      ['Cherry', 0],
    ]);
  });

  it('nests a child under its parent', () => {
    const result = buildAssetTree(
      [asset('p', 'Parent'), asset('c', 'Child', 'p')],
      cmp,
    );
    expect(result.map((e) => [e.item.name, e.depth])).toEqual([
      ['Parent', 0],
      ['Child', 1],
    ]);
  });

  it('handles multi-level nesting', () => {
    const result = buildAssetTree(
      [asset('g', 'Grandchild', 'c'), asset('p', 'Parent'), asset('c', 'Child', 'p')],
      cmp,
    );
    expect(result.map((e) => [e.item.name, e.depth])).toEqual([
      ['Parent', 0],
      ['Child', 1],
      ['Grandchild', 2],
    ]);
  });

  it('sorts siblings alphabetically within each level', () => {
    const result = buildAssetTree(
      [asset('p', 'Parent'), asset('d', 'Delta', 'p'), asset('a', 'Alpha', 'p'), asset('b', 'Bravo', 'p')],
      cmp,
    );
    expect(result.map((e) => [e.item.name, e.depth])).toEqual([
      ['Parent', 0],
      ['Alpha', 1],
      ['Bravo', 1],
      ['Delta', 1],
    ]);
  });

  it('interleaves multiple root trees', () => {
    const result = buildAssetTree(
      [asset('x', 'Xray'), asset('x1', 'Xchild', 'x'), asset('a', 'Alpha'), asset('a1', 'Achild', 'a')],
      cmp,
    );
    expect(result.map((e) => [e.item.name, e.depth])).toEqual([
      ['Alpha', 0],
      ['Achild', 1],
      ['Xray', 0],
      ['Xchild', 1],
    ]);
  });

  it('promotes a child to root when its parent is absent', () => {
    const result = buildAssetTree(
      [asset('c', 'Child', 'missing'), asset('r', 'Root')],
      cmp,
    );
    expect(result.map((e) => [e.item.name, e.depth])).toEqual([
      ['Child', 0],
      ['Root', 0],
    ]);
  });

  it('handles mixed present and absent parents', () => {
    const result = buildAssetTree(
      [asset('a', 'Alpha'), asset('b', 'Bravo', 'a'), asset('c', 'Charlie', 'gone')],
      cmp,
    );
    expect(result.map((e) => [e.item.name, e.depth])).toEqual([
      ['Alpha', 0],
      ['Bravo', 1],
      ['Charlie', 0],
    ]);
  });

  it('respects a custom comparator', () => {
    const reverse = (a, b) => b.name.localeCompare(a.name);
    const result = buildAssetTree(
      [asset('a', 'Alpha'), asset('b', 'Bravo'), asset('c', 'Charlie')],
      reverse,
    );
    expect(result.map((e) => e.item.name)).toEqual(['Charlie', 'Bravo', 'Alpha']);
  });

  it('terminates on a hypothetical cycle without infinite loop', () => {
    const result = buildAssetTree(
      [asset('a', 'A', 'b'), asset('b', 'B', 'a')],
      cmp,
    );
    expect(result.length).toBe(2);
    expect(result.every((e) => e.depth >= 0)).toBe(true);
  });
});

describe('formatDate / formatDateTime (#262)', () => {
  const ISO = '2026-07-01T13:00:00Z';

  it('writes a date as a month name, not a numeric US-order string', () => {
    // "7/1/2026" is ambiguous outside the US and was one of three different date
    // shapes the panel used. Pin the shape, not just that a string comes back.
    const out = formatDate(ISO, 'en-GB');
    expect(out).toContain('2026');
    expect(out).toMatch(/Jul/);
    expect(out).not.toMatch(/\d+\/\d+\/\d+/);
  });

  it('drops seconds from a date-time', () => {
    // The whole point: toLocaleString() gives "7/1/2026, 1:00:00 PM". A completion is
    // something a person did on an afternoon, not a log line.
    const out = formatDateTime(ISO, 'en-GB');
    expect(out).toMatch(/Jul/);
    expect(out).toMatch(/\d{1,2}:\d{2}/);
    expect(out).not.toMatch(/\d{1,2}:\d{2}:\d{2}/);
  });

  it('honours the language it is given rather than the runtime default', () => {
    // Both formatters, and both directions: a mutant that drops the language and
    // always falls back to the runtime locale still produces a plausible-looking
    // string, so the assertion has to be that two languages differ.
    expect(formatDate(ISO, 'de-DE')).toMatch(/Juli|Jul/);
    expect(formatDate(ISO, 'en-GB')).toMatch(/Jul/);
    expect(formatDate(ISO, 'de-DE')).not.toBe(formatDate(ISO, 'en-GB'));
    expect(formatDateTime(ISO, 'de-DE')).not.toBe(formatDateTime(ISO, 'en-GB'));
    expect(formatDateTime(ISO, 'ja-JP')).not.toBe(formatDateTime(ISO, 'en-GB'));
  });

  it('falls back to the runtime locale when given no language', () => {
    // `lang || undefined` — an empty string must mean "no preference", not a locale.
    expect(formatDate(ISO)).toBe(formatDate(ISO, undefined));
    expect(formatDate(ISO, '')).toBe(formatDate(ISO, undefined));
    expect(formatDateTime(ISO)).toBe(formatDateTime(ISO, undefined));
    expect(formatDateTime(ISO, '')).toBe(formatDateTime(ISO, undefined));
  });

  it('accepts a Date as well as an ISO string', () => {
    expect(formatDate(new Date(ISO), 'en-GB')).toBe(formatDate(ISO, 'en-GB'));
    expect(formatDateTime(new Date(ISO), 'en-GB')).toBe(formatDateTime(ISO, 'en-GB'));
  });

  it('is empty for nothing and for an unparseable value', () => {
    for (const bad of [null, undefined, '', 'not a date']) {
      expect(formatDate(bad, 'en-GB'), String(bad)).toBe('');
      expect(formatDateTime(bad, 'en-GB'), String(bad)).toBe('');
    }
  });
});

describe('button weights (#262)', () => {
  it('primary adds no appearance or variant — it is the element default', () => {
    expect(btnAttrs('primary')).toBe('data-hk-weight="primary"');
  });

  it('spells each other weight in ha-button’s own vocabulary', () => {
    expect(btnAttrs('secondary')).toBe('appearance="filled" data-hk-weight="secondary"');
    // Neutral, not brand: plain-brand paints the label accent-coloured, which is
    // 3.26:1 on a card and makes Cancel argue with the action beside it.
    expect(btnAttrs('tertiary')).toBe(
      'appearance="plain" variant="neutral" data-hk-weight="tertiary"',
    );
    expect(btnAttrs('danger')).toBe('appearance="plain" variant="danger" data-hk-weight="danger"');
    expect(btnAttrs('danger-primary')).toBe('variant="danger" data-hk-weight="danger-primary"');
  });

  it('never emits the two attributes ha-button stopped reading', () => {
    for (const weight of ['primary', 'secondary', 'tertiary', 'danger', 'danger-primary']) {
      expect(btnAttrs(weight)).not.toMatch(/raised|destructive/);
    }
  });

  it('setBtnWeight clears the attributes the new weight does not set', () => {
    const el = document.createElement('span');
    setBtnWeight(el, 'danger');
    expect(el.getAttribute('appearance')).toBe('plain');
    expect(el.getAttribute('variant')).toBe('danger');
    // Re-weighting must not leave the old weight's attributes behind — a danger
    // button re-weighted to primary would otherwise stay red.
    setBtnWeight(el, 'primary');
    expect(el.hasAttribute('appearance')).toBe(false);
    expect(el.hasAttribute('variant')).toBe(false);
    expect(el.getAttribute('data-hk-weight')).toBe('primary');
  });

  it('setBtnWeight agrees with btnAttrs for every weight', () => {
    for (const weight of ['primary', 'secondary', 'tertiary', 'danger', 'danger-primary']) {
      const el = document.createElement('span');
      setBtnWeight(el, weight);
      const rendered = [...el.attributes]
        .map((a) => `${a.name}="${a.value}"`)
        .sort()
        .join(' ');
      const expected = btnAttrs(weight).split(' ').sort().join(' ');
      expect(rendered, weight).toBe(expected);
    }
  });
});

describe('recurrenceSummary sentence case (#262)', () => {
  it('capitalises the clock-based fragments, which were written lowercase', () => {
    // "every 12 months after completion" sat beside "Every 300 h of use" and
    // "Monitored" in the same column of the same list.
    expect(recurrenceSummary({ recurrence_type: 'floating', interval: 12, unit: 'months' })).toBe(
      'Every 12 months after completion',
    );
    expect(recurrenceSummary({ recurrence_type: 'fixed', interval: 1, freq: 'MONTHLY' })).toBe(
      'Every month',
    );
  });

  it('leaves the already-capitalised kinds untouched', () => {
    expect(recurrenceSummary({ recurrence_type: 'triggered' })).toBe('Monitored');
    expect(recurrenceSummary({ recurrence_type: 'one-off' })).toBe('One-off');
  });

  it('changes only the first character, never the rest of the sentence', () => {
    // A blanket .toUpperCase() or a title-case pass would also hit the unit and the
    // trailing clause; only the leading letter may move.
    const out = recurrenceSummary({ recurrence_type: 'floating', interval: 3, unit: 'weeks' });
    expect(out).toBe('Every 3 weeks after completion');
    // Everything after the first character is exactly what the strings say — no
    // title-casing of "Weeks", no capital on "After".
    expect(out.slice(1)).toBe('very 3 weeks after completion');
  });
});
