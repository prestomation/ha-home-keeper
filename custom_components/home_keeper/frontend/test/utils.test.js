import { readFileSync } from 'fs';
import { afterEach, describe, it, expect, vi } from 'vitest';
import {
  ASSET_TABS,
  DEFAULT_ASSET_TAB,
  DEFAULT_TASK_TAB,
  DEFAULT_SNOOZE_PRESET,
  SETTINGS_SECTIONS,
  TASK_TABS,
  SNOOZE_PRESETS,
  areaName,
  assetSummary,
  brandLogoUrl,
  btnAttrs,
  buildAssetTree,
  buildPath,
  completionStats,
  formatReading,
  deviceDomain,
  deviceName,
  dueLabel,
  escapeHTML,
  formatCost,
  formatDate,
  formatDateTime,
  formatQuantity,
  isArmedTriggered,
  isBuyTask,
  isHttpUrl,
  isMonitoredDormant,
  isOverdue,
  isSafeImageUrl,
  meterRemaining,
  navigateTo,
  normalizeIcon,
  notifyRowChip,
  parseRoute,
  partStockButtonStep,
  partStockStep,
  personName,
  randomId,
  readingUnit,
  recurrenceSummary,
  relativeDay,
  resolveSnoozePreset,
  safeFileHref,
  safeHref,
  setBtnWeight,
  snapStock,
  showsUsageIntervals,
  sortedCompletions,
  statusChipHtml,
  taskRecordsReading,
  assetForTask,
  assetsForTask,
  taskRelatesToAsset,
  tasksForAsset,
  toast,
  usageIntervalStats,
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

  // The shared cross-language cases. The same fixture drives the Python formatter
  // (assets.format_quantity, see tests/unit/test_assets.py): a quantity is rendered
  // here for the panel and there for the line Home Keeper puts on a household's
  // shopping list, and "500 ml" in one place must not be "500.0 ml" in the other.
  // Halfway values are the ones that matter — Python's round() breaks a tie to the
  // even digit where toFixed breaks it away from zero.
  describe('conformance fixture', () => {
    const cases = JSON.parse(
      readFileSync('tests/fixtures/quantity_format_cases.json', 'utf8'),
    ).cases;

    it('has cases to run', () => {
      expect(cases.length).toBeGreaterThan(0);
    });

    for (const c of cases) {
      it(c.name, () => {
        expect(formatQuantity(c.value, c.unit)).toBe(c.expected);
      });
    }
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
  it('appends season range for floating tasks with active_season', () => {
    expect(
      recurrenceSummary({
        recurrence_type: 'floating', interval: 2, unit: 'months',
        active_season: { start: '04-01', end: '09-30' },
      }),
    ).toBe('Every 2 months after completion, April 1–September 30');
  });
  it('appends season range for fixed tasks with active_season', () => {
    expect(
      recurrenceSummary({
        recurrence_type: 'fixed', interval: 1, freq: 'MONTHLY',
        active_season: { start: '11-01', end: '03-31' },
      }),
    ).toBe('Every month, November 1–March 31');
  });
  it('omits season range when active_season is null', () => {
    expect(
      recurrenceSummary({
        recurrence_type: 'floating', interval: 1, unit: 'months',
        active_season: null,
      }),
    ).toBe('Every month after completion');
  });
  it('shows multi-window season with ampersand', () => {
    expect(
      recurrenceSummary({
        recurrence_type: 'floating', interval: 1, unit: 'months',
        active_season: [
          { start: '04-01', end: '05-31' },
          { start: '09-01', end: '10-31' },
        ],
      }),
    ).toBe('Every month after completion, April 1–May 31 & September 1–October 31');
  });
  it('defaults to daily when freq is missing for a fixed task', () => {
    expect(
      recurrenceSummary({ recurrence_type: 'fixed', interval: 1 }),
    ).toBe('Every day');
  });

  it('describes an availability task without borrowing the meter’s words', () => {
    // The mode has no `target`, so before it had a case of its own it fell through to
    // the usage branch and rendered "Every of use" — a sentence with a hole in it.
    const summary = recurrenceSummary({
      recurrence_type: 'sensor',
      sensor: { entity_id: 'sensor.hallway_lux', mode: 'availability' },
    });
    expect(summary).not.toContain('of use');
    expect(summary).toContain('unavailable');
  });

  it('still describes the other sensor modes in their own words', () => {
    // The guard above sits between `threshold` and the meter, so it is exactly the
    // kind of edit that can swallow a neighbour.
    expect(
      recurrenceSummary({
        recurrence_type: 'sensor',
        sensor: { entity_id: 'sensor.h', mode: 'threshold', comparison: '>', value: 0 },
      }),
    ).toContain('> 0');
    expect(
      recurrenceSummary({
        recurrence_type: 'sensor',
        sensor: { entity_id: 'sensor.h', mode: 'usage', target: 300 },
      }),
    ).toContain('of use');
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

describe('isMonitoredDormant', () => {
  const sensor = (mode, rest = {}) => ({
    recurrence_type: 'sensor',
    sensor: { entity_id: 'sensor.x', mode },
    ...rest,
  });

  it('is true for a dormant triggered task', () => {
    expect(isMonitoredDormant({ recurrence_type: 'triggered' })).toBe(true);
    expect(isMonitoredDormant({ recurrence_type: 'triggered', next_due: null })).toBe(true);
  });

  // #231: a Device Pulse task sat under the Monitored heading with a live Done
  // button. The three edge modes watch a condition, so a dormant one has no work.
  it('is true for a dormant sensor task in an edge mode', () => {
    expect(isMonitoredDormant(sensor('state'))).toBe(true);
    expect(isMonitoredDormant(sensor('threshold'))).toBe(true);
    expect(isMonitoredDormant(sensor('availability'))).toBe(true);
  });

  // A meter is counting up to its target; completing it early is real work that
  // re-anchors the baseline, so it keeps its Done.
  it('is false for a dormant usage meter, and for a binding with no mode', () => {
    expect(isMonitoredDormant(sensor('usage'))).toBe(false);
    expect(isMonitoredDormant({ recurrence_type: 'sensor', sensor: { entity_id: 'sensor.x' } })).toBe(
      false,
    );
    expect(isMonitoredDormant({ recurrence_type: 'sensor' })).toBe(false);
  });

  it('is false once the task is armed, whatever its mode', () => {
    const due = '2026-06-01T00:00:00Z';
    expect(isMonitoredDormant({ recurrence_type: 'triggered', next_due: due })).toBe(false);
    expect(isMonitoredDormant(sensor('state', { next_due: due }))).toBe(false);
    expect(isMonitoredDormant(sensor('availability', { next_due: due }))).toBe(false);
  });

  it('is false for the clock and one-off shapes, dormant or not', () => {
    expect(isMonitoredDormant({ recurrence_type: 'floating' })).toBe(false);
    expect(isMonitoredDormant({ recurrence_type: 'fixed' })).toBe(false);
    expect(
      isMonitoredDormant({ recurrence_type: 'one-off', last_completed: '2026-05-01T00:00:00Z' }),
    ).toBe(false);
  });

  // The recurrence type decides, not the presence of a binding. A task edited away
  // from `sensor` can keep a stale block, and it is no longer condition-driven.
  it('reads the recurrence type, not a leftover sensor block', () => {
    expect(
      isMonitoredDormant({
        recurrence_type: 'floating',
        sensor: { entity_id: 'sensor.x', mode: 'state' },
      }),
    ).toBe(false);
    expect(
      isMonitoredDormant({
        recurrence_type: 'one-off',
        sensor: { entity_id: 'sensor.x', mode: 'availability' },
      }),
    ).toBe(false);
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

describe('isBuyTask', () => {
  it('needs both ids, because half a pair identifies no part', () => {
    expect(isBuyTask({ source: { buy: { asset_id: 'a1', part_id: 'p1' } } })).toBe(true);
    expect(isBuyTask({ source: { buy: { asset_id: 'a1' } } })).toBe(false);
    expect(isBuyTask({ source: { buy: { part_id: 'p1' } } })).toBe(false);
    expect(isBuyTask({ source: { part: { asset_id: 'a1' } } })).toBe(false);
    expect(isBuyTask({ source: null })).toBe(false);
    expect(isBuyTask({})).toBe(false);
  });
});

describe('statusChipHtml', () => {
  const now = new Date('2026-06-13T12:00:00Z');
  const buy = {
    // Exactly how the reconciler mints one: a one-off whose due date is the moment
    // the part went low, so it is already overdue when it first appears.
    recurrence_type: 'one-off',
    next_due: '2026-06-10T12:00:00Z',
    source: { buy: { asset_id: 'a1', part_id: 'p1' } },
  };

  it('says Low stock on a buy reminder, never Overdue', () => {
    const html = statusChipHtml(buy, undefined, { now });
    expect(html).toContain('label="Low stock"');
    expect(html).toContain('class="hk-shopping"');
    expect(html).not.toContain('Overdue');
    expect(html).not.toContain('hk-overdue');
  });

  it('says Low stock even where the row asks for elapsed days', () => {
    // The list row passes `elapsed`. "3 days overdue" on a buy reminder would read as
    // work three days late, when it means the part has been low for three days.
    const html = statusChipHtml(buy, undefined, { now, elapsed: true });
    expect(html).toContain('label="Low stock"');
    expect(html).not.toContain('3 days overdue');
  });

  it('says Completed once the reminder is bought, matching its section', () => {
    // Buying 2 of a part that wants 5 leaves it low, so the reconciler keeps the row
    // and `statusBucket` files it under Completed. A "Low stock" chip on a row sitting
    // under Completed is the panel arguing with itself.
    const bought = {
      recurrence_type: 'one-off',
      next_due: null,
      last_completed: '2026-06-12T12:00:00Z',
      source: { buy: { asset_id: 'a1', part_id: 'p1' } },
    };
    const html = statusChipHtml(bought, undefined, { now });
    expect(html).toContain('label="Completed"');
    expect(html).not.toContain('Low stock');
  });

  it('needs all three marks of a bought reminder before it stops saying Low stock', () => {
    // "Bought" is the one shape `statusBucket` calls completed: a one-off, with its
    // due date spent, that has a completion on it. Each part is load-bearing — drop
    // any one and the row is an open reminder that must still read Low stock, so each
    // is pinned separately rather than by the happy path alone.
    const bought = {
      recurrence_type: 'one-off',
      next_due: null,
      last_completed: '2026-06-12T12:00:00Z',
      source: { buy: { asset_id: 'a1', part_id: 'p1' } },
    };
    const lowStock = 'label="Low stock"';
    // Not a one-off — a repeating task's completion does not end it.
    expect(statusChipHtml({ ...bought, recurrence_type: 'floating' }, undefined, { now })).toContain(
      lowStock,
    );
    // Still due: bought once before, low again now.
    expect(
      statusChipHtml({ ...bought, next_due: '2026-06-10T12:00:00Z' }, undefined, { now }),
    ).toContain(lowStock);
    // Never completed — a fresh reminder that simply has no due date yet.
    expect(statusChipHtml({ ...bought, last_completed: null }, undefined, { now })).toContain(
      lowStock,
    );
  });

  it('still says Overdue for real maintenance', () => {
    const late = { next_due: '2026-06-10T12:00:00Z' };
    expect(statusChipHtml(late, undefined, { now })).toContain('label="Overdue"');
    expect(statusChipHtml(late, undefined, { now })).toContain('class="hk-overdue"');
  });

  it('counts elapsed whole days only when asked, and only past a full day', () => {
    const days3 = { next_due: '2026-06-10T12:00:00Z' };
    const hours4 = { next_due: '2026-06-13T08:00:00Z' };
    expect(statusChipHtml(days3, undefined, { now, elapsed: true })).toContain(
      'label="3 days overdue"',
    );
    // One full day is the floor for the count, and it is *included*: exactly one day
    // late reads "1 day overdue", where anything under a day stays the bare "Overdue"
    // rather than rounding up to a day it has not reached.
    const day1 = { next_due: '2026-06-12T12:00:00Z' };
    expect(statusChipHtml(day1, undefined, { now, elapsed: true })).toContain(
      'label="1 day overdue"',
    );
    expect(statusChipHtml(hours4, undefined, { now, elapsed: true })).toContain(
      'label="Overdue"',
    );
    // Without `elapsed` the count never appears, however late the task is.
    expect(statusChipHtml(days3, undefined, { now })).toContain('label="Overdue"');
  });

  it('falls back to the due label when nothing is late', () => {
    const soon = { next_due: '2026-06-14T12:00:00Z' };
    const html = statusChipHtml(soon, undefined, { now });
    // A plain chip carries no class at all — the color is what separates it from an
    // overdue or low-stock one, so an empty `class=""` would still be wrong.
    expect(html).toBe('<ha-assist-chip label="tomorrow"></ha-assist-chip>');
  });

  it('escapes the label it renders', () => {
    // The label goes into an HTML attribute, and `dueLabel` can carry a meter's own
    // unit ("in 7000 miles") — which is stored text, not a fixed string.
    const html = statusChipHtml(
      {
        recurrence_type: 'sensor',
        sensor: {
          mode: 'usage',
          target: 100,
          baseline: 0,
          entity_id: 'sensor.odo',
          unit: '" onload="x',
        },
      },
      { states: { 'sensor.odo': { state: '10' } } },
      { now },
    );
    expect(html).toContain('&quot; onload=&quot;x');
    expect(html).not.toContain('" onload="x');
  });
});

describe('dueLabel', () => {
  const now = new Date('2026-06-13T12:00:00Z');
  it('renders relative day labels', () => {
    expect(dueLabel({ next_due: '2026-06-13T18:00:00Z' }, now)).toBe('today');
    expect(dueLabel({ next_due: '2026-06-14T12:00:00Z' }, now)).toBe('tomorrow');
    expect(dueLabel({ next_due: '2026-06-16T12:00:00Z' }, now)).toBe('in 3 days');
    expect(dueLabel({ next_due: '2026-06-12T12:00:00Z' }, now)).toBe('yesterday');
    // The multi-day past had no assertion, so nothing distinguished "3 days ago" from
    // "yesterday" or from the plural template being wrong.
    expect(dueLabel({ next_due: '2026-06-10T12:00:00Z' }, now)).toBe('3 days ago');
    expect(dueLabel({ next_due: '2026-06-14T12:00:00Z' }, now)).not.toBe('in 1 day');
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

describe('showsUsageIntervals', () => {
  const meter = { recurrence_type: 'sensor', sensor: { entity_id: 's.x', mode: 'usage' } };
  it('is true for a usage meter', () => {
    expect(showsUsageIntervals(meter)).toBe(true);
  });
  it('is false for the other sensor modes', () => {
    // A threshold task logs a reading too, but that reading is a measurement and not a
    // meter that only climbs.
    for (const mode of ['threshold', 'state', 'availability']) {
      expect(showsUsageIntervals({ ...meter, sensor: { entity_id: 's.x', mode } })).toBe(false);
    }
  });
  it('is false for a task that is not sensor-driven, or absent', () => {
    expect(showsUsageIntervals({ recurrence_type: 'floating' })).toBe(false);
    expect(showsUsageIntervals({ recurrence_type: 'sensor' })).toBe(false);
    expect(showsUsageIntervals(undefined)).toBe(false);
    expect(showsUsageIntervals(null)).toBe(false);
  });
});

describe('formatReading', () => {
  it('groups the digits in the viewer language', () => {
    expect(formatReading(163900, 'km', 'en')).toBe('163,900 km');
    expect(formatReading(163900, 'km', 'de')).toBe('163.900 km');
  });
  it('omits the unit when the task has none', () => {
    expect(formatReading(163900, '', 'en')).toBe('163,900');
    expect(formatReading(163900, null, 'en')).toBe('163,900');
    expect(formatReading(163900, undefined, 'en')).toBe('163,900');
  });
  it('trims a padded unit rather than doubling the space', () => {
    expect(formatReading(12, '  h  ', 'en')).toBe('12 h');
  });
  it('keeps one decimal and no more', () => {
    // A run-hours sensor reads 661.4166666; one decimal is the resolution a
    // maintenance interval needs, and the rest is noise.
    expect(formatReading(661.4166666, 'h', 'en')).toBe('661.4 h');
    expect(formatReading(660, 'h', 'en')).toBe('660 h');
  });
  it('formats a negative and a zero reading', () => {
    expect(formatReading(0, 'h', 'en')).toBe('0 h');
    expect(formatReading(-12.5, 'h', 'en')).toBe('-12.5 h');
  });
});

describe('usageIntervalStats', () => {
  const ODOMETER = [
    { ts: '2023-03-12T09:00:00Z', reading: 120000 },
    { ts: '2024-02-04T09:00:00Z', reading: 134800 },
    { ts: '2024-11-19T09:00:00Z', reading: 150200 },
    { ts: '2025-08-28T09:00:00Z', reading: 163900 },
  ];

  it('keys each interval by its own completion', () => {
    const s = usageIntervalStats(ODOMETER);
    expect(s.count).toBe(3);
    expect(s.byTs.get('2024-02-04T09:00:00Z')).toBe(14800);
    expect(s.byTs.get('2024-11-19T09:00:00Z')).toBe(15400);
    expect(s.byTs.get('2025-08-28T09:00:00Z')).toBe(13700);
    // The oldest completion has no predecessor, so it has no interval.
    expect(s.byTs.has('2023-03-12T09:00:00Z')).toBe(false);
  });

  it('reports the last, the average and the range', () => {
    const s = usageIntervalStats(ODOMETER);
    expect(s.last).toBe(13700);
    expect(s.average).toBeCloseTo((14800 + 15400 + 13700) / 3, 6);
    expect(s.shortest).toBe(13700);
    expect(s.longest).toBe(15400);
  });

  it('orders by timestamp, not by position', () => {
    // `completions` keeps insertion order, so a back-dated completion sits at the
    // end. Subtracting in list order would report 15400 and then -1400.
    const s = usageIntervalStats([
      { ts: '2024-02-04T09:00:00Z', reading: 134800 },
      { ts: '2024-11-19T09:00:00Z', reading: 150200 },
      { ts: '2023-03-12T09:00:00Z', reading: 120000 },
    ]);
    expect(s.byTs.get('2024-02-04T09:00:00Z')).toBe(14800);
    expect(s.byTs.get('2024-11-19T09:00:00Z')).toBe(15400);
    expect(s.count).toBe(2);
  });

  it('compares mixed offsets as instants', () => {
    const s = usageIntervalStats([
      { ts: '2024-02-05T02:00:00Z', reading: 134800 },
      { ts: '2024-02-04T23:00:00-05:00', reading: 150200 },
    ]);
    expect(s.last).toBe(15400);
  });

  it('skips a completion with no reading', () => {
    const s = usageIntervalStats([
      { ts: '2024-02-04T09:00:00Z', reading: 134800 },
      { ts: '2024-11-19T09:00:00Z' },
      { ts: '2025-08-28T09:00:00Z', reading: 163900 },
    ]);
    expect(s.count).toBe(1);
    expect(s.byTs.get('2025-08-28T09:00:00Z')).toBe(29100);
    expect(s.byTs.has('2024-11-19T09:00:00Z')).toBe(false);
  });

  it('skips a non-numeric and a non-finite reading', () => {
    expect(
      usageIntervalStats([
        { ts: '2024-02-04T09:00:00Z', reading: '134800' },
        { ts: '2025-08-28T09:00:00Z', reading: 163900 },
      ]).count,
    ).toBe(0);
    expect(
      usageIntervalStats([
        { ts: '2024-02-04T09:00:00Z', reading: Infinity },
        { ts: '2025-08-28T09:00:00Z', reading: 163900 },
      ]).count,
    ).toBe(0);
  });

  it('skips an unparseable timestamp', () => {
    const s = usageIntervalStats([
      { ts: 'not a date', reading: 120000 },
      { ts: '2025-08-28T09:00:00Z', reading: 163900 },
    ]);
    expect(s.count).toBe(0);
  });

  it('skips text that ends in an offset but is not a date', () => {
    // The offset test reads the tail, so this gets past it and has to be caught by the
    // parse. Left in, it would order by NaN and key a made-up interval to it. The
    // backend drops the same string, on the ValueError out of its own parse.
    const s = usageIntervalStats([
      { ts: 'not a date+00:00', reading: 120000 },
      { ts: '2025-08-28T09:00:00Z', reading: 163900 },
    ]);
    expect(s.count).toBe(0);
    expect(s.byTs.size).toBe(0);
  });

  it('accepts every offset shape Home Assistant writes', () => {
    const s = usageIntervalStats([
      { ts: '2024-02-04T09:00:00Z', reading: 134800 },
      { ts: '2024-11-19T09:00:00+00:00', reading: 150200 },
      { ts: '2025-08-28T04:00:00-05:00', reading: 163900 },
      { ts: '2026-01-04T09:00:00+0000', reading: 170000 },
    ]);
    expect(s.count).toBe(3);
    expect(s.last).toBe(6100);
  });

  it('skips a stamp with no offset', () => {
    // `new Date` reads an offset-free stamp as the viewer's own zone, so the same
    // history would order differently in Berlin and in Seattle; the backend refuses to
    // compare it against an offset-bearing one at all. Both sides drop it.
    const s = usageIntervalStats([
      { ts: '2024-02-04T09:00:00+00:00', reading: 134800 },
      { ts: '2024-11-19T09:00:00', reading: 150200 },
      { ts: '2025-08-28T09:00:00+00:00', reading: 163900 },
    ]);
    expect(s.count).toBe(1);
    expect(s.last).toBe(29100);
    expect(s.byTs.has('2024-11-19T09:00:00')).toBe(false);
  });

  it('drops the negative interval a meter reset leaves behind', () => {
    // A replaced controller reads lower than the completion before it, so the
    // difference is not usage. The interval after the reset is real.
    const s = usageIntervalStats([
      { ts: '2024-02-04T09:00:00Z', reading: 134800 },
      { ts: '2024-11-19T09:00:00Z', reading: 200 },
      { ts: '2025-08-28T09:00:00Z', reading: 14000 },
    ]);
    expect(s.count).toBe(1);
    expect(s.byTs.has('2024-11-19T09:00:00Z')).toBe(false);
    expect(s.last).toBe(13800);
  });

  it('keeps a zero interval', () => {
    const s = usageIntervalStats([
      { ts: '2024-02-04T09:00:00Z', reading: 134800 },
      { ts: '2024-11-19T09:00:00Z', reading: 134800 },
    ]);
    expect(s.count).toBe(1);
    expect(s.last).toBe(0);
    expect(s.shortest).toBe(0);
  });

  it('reports nothing for one reading, none, or no list at all', () => {
    for (const empty of [[{ ts: '2025-08-28T09:00:00Z', reading: 1 }], [], undefined]) {
      const s = usageIntervalStats(empty);
      expect(s.count).toBe(0);
      expect(s.last).toBeUndefined();
      expect(s.average).toBeUndefined();
      expect(s.shortest).toBeUndefined();
      expect(s.longest).toBeUndefined();
      expect(s.byTs.size).toBe(0);
    }
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

describe('assetsForTask / assetForTask', () => {
  // Three appliances that all have a claim on dev1, from weakest to strongest, in an
  // order that no accidental "first match wins" could get right.
  const related = { id: 'a-related', name: 'Related', related_device_ids: ['dev1'] };
  const owner = { id: 'a-owner', name: 'Owner', device_id: 'dev1' };
  const partOwner = { id: 'a-part', name: 'Part owner', device_id: 'dev9' };
  const all = [related, owner, partOwner];

  it('ranks the appliance whose part the task is above the one that owns its device', () => {
    const task = {
      id: 't',
      name: 'x',
      device_id: 'dev1',
      source: { part: { asset_id: 'a-part', part_id: 'p' } },
    };
    expect(assetsForTask(task, all).map((a) => a.id)).toEqual(['a-part', 'a-owner', 'a-related']);
    expect(assetForTask(task, all).id).toBe('a-part');
  });

  it('ranks the device owner above an appliance that only lists it as related', () => {
    const task = { id: 't', name: 'x', device_id: 'dev1' };
    expect(assetsForTask(task, all).map((a) => a.id)).toEqual(['a-owner', 'a-related']);
    expect(assetForTask(task, all).id).toBe('a-owner');
  });

  it('falls to the related appliance when nothing owns the device', () => {
    const task = { id: 't', name: 'x', device_id: 'dev1' };
    expect(assetForTask(task, [related]).id).toBe('a-related');
  });

  it('puts an archived appliance behind a live one that claims the same device', () => {
    const archived = { id: 'a-old', name: 'Old', device_id: 'dev1', archived_at: '2026-01-01' };
    const task = { id: 't', name: 'x', device_id: 'dev1' };
    // Archived first in the array, so only the ranking can put the live one first.
    expect(assetsForTask(task, [archived, owner]).map((a) => a.id)).toEqual(['a-owner', 'a-old']);
    // ...and it is still the answer when it is the only appliance that claims it.
    expect(assetForTask(task, [archived]).id).toBe('a-old');
  });

  it('keeps the given order between appliances with the same claim', () => {
    // Three, not two: a two-element sort makes a single comparison, which a
    // symmetric comparator gets right by accident.
    const same = ['a-first', 'a-second', 'a-third'].map((id) => ({ id, name: id, device_id: 'dev1' }));
    const task = { id: 't', name: 'x', device_id: 'dev1' };
    expect(assetsForTask(task, same).map((a) => a.id))
      .toEqual(['a-first', 'a-second', 'a-third']);
    expect(assetsForTask(task, [...same].reverse()).map((a) => a.id))
      .toEqual(['a-third', 'a-second', 'a-first']);
  });

  it('belongs to no appliance when the task has no device, whatever the related list holds', () => {
    // A related list with a hole in it. Without the no-device guard this reaches
    // `[undefined].includes(undefined)` and claims the task.
    const holey = { id: 'a-holey', name: 'Holey', related_device_ids: [undefined] };
    expect(assetForTask({ id: 't', name: 'x' }, [holey])).toBeUndefined();
  });

  it('returns nothing for a task with no device and no part link', () => {
    expect(assetsForTask({ id: 't', name: 'x' }, all)).toEqual([]);
    expect(assetForTask({ id: 't', name: 'x' }, all)).toBeUndefined();
    expect(assetForTask({ id: 't', name: 'x', device_id: 'unknown' }, all)).toBeUndefined();
  });

  it('agrees with taskRelatesToAsset about what counts as related', () => {
    const task = { id: 't', name: 'x', device_id: 'dev1' };
    const matched = assetsForTask(task, all).map((a) => a.id);
    expect(all.filter((a) => taskRelatesToAsset(task, a)).map((a) => a.id).sort())
      .toEqual([...matched].sort());
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
  it('parses a task detail, on its default sub-tab', () => {
    // A bare `/tasks/<id>` — every link minted before task sub-tabs existed — opens
    // the schedule, as it always did.
    expect(parseRoute('/tasks/abc')).toEqual({
      view: 'tasks',
      detail: { kind: 'task', id: 'abc', tab: 'schedule' },
    });
  });
  it('parses each task sub-tab from the third segment', () => {
    for (const tab of TASK_TABS) {
      expect(parseRoute(`/tasks/abc/${tab}`)).toEqual({
        view: 'tasks',
        detail: { kind: 'task', id: 'abc', tab },
      });
    }
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
  it('falls back to the default task sub-tab for an unknown one', () => {
    // An appliance's tab names are not a task's; a stale or hand-typed one opens the
    // task rather than nothing.
    for (const bogus of ['documents', 'nope', 'SCHEDULE', '']) {
      expect(parseRoute(`/tasks/abc/${bogus}`)).toEqual({
        view: 'tasks',
        detail: { kind: 'task', id: 'abc', tab: DEFAULT_TASK_TAB },
      });
    }
  });
  it('decodes percent-encoded ids and tolerates trailing slashes', () => {
    expect(parseRoute('/tasks/a%2Fb/')).toEqual({
      view: 'tasks',
      detail: { kind: 'task', id: 'a/b', tab: 'schedule' },
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
  it('leaves the default task sub-tab implicit, and names the others', () => {
    expect(buildPath({ view: 'tasks', detail: { kind: 'task', id: 'x', tab: 'schedule' } })).toBe(
      '/tasks/x',
    );
    for (const tab of TASK_TABS.filter((t) => t !== DEFAULT_TASK_TAB)) {
      expect(buildPath({ view: 'tasks', detail: { kind: 'task', id: 'x', tab } })).toBe(
        `/tasks/x/${tab}`,
      );
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
      // A detail always resolves with a sub-tab, so that is the shape a round-trip
      // has to come back as.
      { view: 'tasks', detail: { kind: 'task', id: 'task-1', tab: 'schedule' } },
      ...TASK_TABS.map((tab) => ({ view: 'tasks', detail: { kind: 'task', id: 'task-1', tab } })),
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
    // Neutral, not brand: plain-brand paints the label accent-colored, which is
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

  it('setBtnWeight leaves nothing behind, for every ordered pair of weights', () => {
    // The strong form of the clearing rule: whatever a button was, becoming something
    // else must leave it identical to a button that was always that. This is what
    // fails if the cleared-attribute list ever stops covering the table it serves.
    const weights = ['primary', 'secondary', 'tertiary', 'danger', 'danger-primary'];
    const render = (el) =>
      [...el.attributes]
        .map((a) => `${a.name}="${a.value}"`)
        .sort()
        .join(' ');
    for (const from of weights) {
      for (const to of weights) {
        const reweighted = document.createElement('span');
        setBtnWeight(reweighted, from);
        setBtnWeight(reweighted, to);
        const fresh = document.createElement('span');
        setBtnWeight(fresh, to);
        expect(render(reweighted), `${from} -> ${to}`).toBe(render(fresh));
      }
    }
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

describe('toast', () => {
  it("emits HA's notification event from the element, escaping the shadow root", () => {
    const el = document.createElement('div');
    const seen = [];
    el.addEventListener('hass-notification', (e) => seen.push(e));

    toast(el, 'Saved');

    expect(seen).toHaveLength(1);
    expect(seen[0].type).toBe('hass-notification');
    expect(seen[0].detail).toEqual({ message: 'Saved' });
    // Both flags are load-bearing: HA listens above the panel/card, and the event is
    // fired inside a shadow root. Either one false and the toast never shows.
    expect(seen[0].bubbles).toBe(true);
    expect(seen[0].composed).toBe(true);
  });

  it('carries whatever message it was given, including an empty one', () => {
    const el = document.createElement('div');
    let detail;
    el.addEventListener('hass-notification', (e) => (detail = e.detail));
    toast(el, '');
    expect(detail).toEqual({ message: '' });
  });
});

describe('navigateTo', () => {
  afterEach(() => vi.restoreAllMocks());

  it('pushes the path and tells HA’s router to re-route', () => {
    const push = vi.spyOn(history, 'pushState').mockImplementation(() => {});
    const seen = [];
    const onNav = (e) => seen.push(e);
    window.addEventListener('location-changed', onNav);

    navigateTo('/config/devices/device/abc');

    window.removeEventListener('location-changed', onNav);
    // The title argument stays empty — HA's router reads the URL, and a title here
    // would be the only thing that ever set the document title from a chip press.
    expect(push).toHaveBeenCalledWith(null, '', '/config/devices/device/abc');
    expect(seen).toHaveLength(1);
    expect(seen[0].type).toBe('location-changed');
    // Always a push, never a replace: Back returns to the page the user left.
    expect(seen[0].detail).toEqual({ replace: false });
    expect(seen[0].bubbles).toBe(true);
    expect(seen[0].composed).toBe(true);
  });

  it('fires on window, not on the element that asked (which may be unmounted)', () => {
    vi.spyOn(history, 'pushState').mockImplementation(() => {});
    const el = document.createElement('div');
    document.body.appendChild(el);
    const onEl = vi.fn();
    el.addEventListener('location-changed', onEl);
    const onWin = vi.fn();
    window.addEventListener('location-changed', onWin);

    navigateTo('/home-keeper/tasks/t1');

    window.removeEventListener('location-changed', onWin);
    el.remove();
    expect(onWin).toHaveBeenCalledTimes(1);
    expect(onEl).not.toHaveBeenCalled();
  });
});

describe('relativeDay', () => {
  const now = new Date('2026-06-13T12:00:00Z');

  it('names the recent past in whole days', () => {
    expect(relativeDay(new Date('2026-06-13T09:00:00Z'), now)).toBe('today');
    expect(relativeDay(new Date('2026-06-12T12:00:00Z'), now)).toBe('yesterday');
    expect(relativeDay(new Date('2026-06-10T12:00:00Z'), now)).toBe('3 days ago');
    // Plural template, not "3 day ago" — and singular where singular is right.
    expect(relativeDay(new Date('2026-06-12T12:00:00Z'), now)).not.toBe('1 days ago');
  });

  it('reads a future date as today rather than counting backwards', () => {
    // A completion timestamped a few minutes ahead (clock skew) still happened now.
    expect(relativeDay(new Date('2026-06-13T18:00:00Z'), now)).toBe('today');
    expect(relativeDay(new Date('2026-06-20T12:00:00Z'), now)).toBe('today');
  });

  it('rounds to the nearest whole day at the half-day mark', () => {
    // 1.4 days ago is still "yesterday"; 1.6 rounds up to two.
    expect(relativeDay(new Date('2026-06-12T02:24:00Z'), now)).toBe('yesterday');
    expect(relativeDay(new Date('2026-06-11T21:36:00Z'), now)).toBe('2 days ago');
  });

  it('defaults to the real clock when no now is given', () => {
    expect(relativeDay(new Date())).toBe('today');
    expect(relativeDay(new Date(Date.now() - 86_400_000))).toBe('yesterday');
  });
});

describe('formatCost', () => {
  it('formats in the instance currency, in the instance language', () => {
    const hass = { config: { currency: 'USD' }, language: 'en-US' };
    expect(formatCost(hass, 12.5)).toBe('$12.50');
    const eu = { config: { currency: 'EUR' }, language: 'en-US' };
    expect(formatCost(eu, 12.5)).toBe('€12.50');
  });

  it('falls back to the bare number when there is no currency to format in', () => {
    expect(formatCost({ language: 'en-US' }, 12.5)).toBe('12.5');
    expect(formatCost({ config: {} }, 12.5)).toBe('12.5');
    expect(formatCost(undefined, 12.5)).toBe('12.5');
  });

  it('falls back to the bare number for a currency code Intl refuses', () => {
    // A free-text currency in HA's config (or a code Intl has never heard of) used to
    // throw out of the render; the number is worth more than an exception.
    expect(formatCost({ config: { currency: 'not-a-currency' }, language: 'en-US' }, 12.5)).toBe(
      '12.5',
    );
  });
});

describe('personName', () => {
  const hass = {
    states: {
      'person.sam': { attributes: { friendly_name: 'Sam' } },
      'person.blank': { attributes: { friendly_name: '' } },
      'person.bare': { attributes: {} },
      'person.stateless': {},
      'person.odd': { attributes: { friendly_name: 42 } },
    },
  };

  it('prefers the friendly name', () => {
    expect(personName(hass, 'person.sam')).toBe('Sam');
  });

  it('falls back to the entity id whenever there is no name to show', () => {
    // An empty friendly_name is not a name: it would render "Completed by " and stop.
    expect(personName(hass, 'person.blank')).toBe('person.blank');
    expect(personName(hass, 'person.bare')).toBe('person.bare');
    // A state object with no attributes at all — HA hands those out for a moment
    // during startup, and reaching through one used to throw out of the render.
    expect(personName(hass, 'person.stateless')).toBe('person.stateless');
    expect(personName(hass, 'person.odd')).toBe('person.odd');
    expect(personName(hass, 'person.gone')).toBe('person.gone');
    expect(personName({}, 'person.sam')).toBe('person.sam');
    expect(personName(undefined, 'person.sam')).toBe('person.sam');
  });
});

describe('snooze presets', () => {
  const from = new Date(2026, 7, 30, 9, 0); // Sun 30 Aug 2026, 09:00 local

  it('resolves each offset from the given instant', () => {
    expect(resolveSnoozePreset('1h', from)).toEqual(new Date(2026, 7, 30, 10, 0));
    expect(resolveSnoozePreset('1d', from)).toEqual(new Date(2026, 7, 31, 9, 0));
    expect(resolveSnoozePreset('1w', from)).toEqual(new Date(2026, 8, 6, 9, 0));
    expect(resolveSnoozePreset('1mo', from)).toEqual(new Date(2026, 8, 30, 9, 0));
  });

  it('clamps a month onto a shorter one instead of rolling past it', () => {
    // Jan 31 + 1 month is Feb 28, matching the backend's `recurrence.add_months`.
    // A bare `setMonth` would roll *forward* to Mar 3, so the date the dialog
    // previews would not be the date the task ends up with.
    expect(resolveSnoozePreset('1mo', new Date(2026, 0, 31, 9, 0))).toEqual(
      new Date(2026, 1, 28, 9, 0),
    );
  });

  it('clamps onto a leap February', () => {
    expect(resolveSnoozePreset('1mo', new Date(2028, 0, 31, 9, 0))).toEqual(
      new Date(2028, 1, 29, 9, 0),
    );
  });

  it('carries an hour offset across a day boundary', () => {
    expect(resolveSnoozePreset('1h', new Date(2026, 7, 30, 23, 30))).toEqual(
      new Date(2026, 7, 31, 0, 30),
    );
  });

  it('has no offset for custom — the dialog reveals a date field instead', () => {
    expect(resolveSnoozePreset('custom', from)).toBeNull();
  });

  it('returns null for an id that is not a preset', () => {
    expect(resolveSnoozePreset('1y', from)).toBeNull();
  });

  it('opens on a preset that is actually in the list', () => {
    expect(SNOOZE_PRESETS.map((p) => p.id)).toContain(DEFAULT_SNOOZE_PRESET);
  });

  it('ends with custom, so the escape hatch sits last in the dropdown', () => {
    expect(SNOOZE_PRESETS[SNOOZE_PRESETS.length - 1].id).toBe('custom');
  });
});

// ── the stock stepper's step rules ───────────────────────────────────────────

describe('partStockStep', () => {
  it('moves in whole spares for a part counted in spares', () => {
    expect(partStockStep({ name: 'Filter', type: 'consumable', stock: 4, reorder_at: 1 })).toBe(1);
    expect(partStockStep({ name: 'Filter', type: 'consumable' })).toBe(1);
  });
  it('moves finely once the part has a unit', () => {
    expect(partStockStep({ name: 'Descaler', type: 'consumable', stock: 750, stock_unit: 'ml' })).toBe(0.001);
    // A blank unit is no unit.
    expect(partStockStep({ name: 'Descaler', type: 'consumable', stock: 750, stock_unit: '  ' })).toBe(1);
  });
  it('moves finely once any quantity is fractional — the same rule as the device page', () => {
    const base = { name: 'Oil', type: 'consumable', stock: 2 };
    expect(partStockStep({ ...base, stock: 2.5 })).toBe(0.001);
    expect(partStockStep({ ...base, reorder_at: 0.5 })).toBe(0.001);
    expect(partStockStep({ ...base, consume_quantity: 0.25 })).toBe(0.001);
    expect(partStockStep({ ...base, restock_quantity: 1.5 })).toBe(0.001);
    expect(partStockStep({ ...base, reorder_at: null, consume_quantity: null })).toBe(1);
  });
});

describe('partStockButtonStep', () => {
  it('is one spare for a counted part', () => {
    expect(partStockButtonStep({ name: 'Filter', type: 'consumable', stock: 4 })).toBe(1);
  });
  it('is one completion for a measured part, and one unit when no amount is set', () => {
    expect(
      partStockButtonStep({ name: 'Descaler', type: 'consumable', stock: 750, stock_unit: 'ml', consume_quantity: 250 }),
    ).toBe(250);
    expect(partStockButtonStep({ name: 'Descaler', type: 'consumable', stock: 750, stock_unit: 'ml' })).toBe(1);
  });
});

describe('snapStock', () => {
  it('rounds to the step and never goes below zero', () => {
    expect(snapStock(4.4, 1)).toBe(4);
    expect(snapStock(4.5, 1)).toBe(5);
    expect(snapStock(-2, 1)).toBe(0);
    expect(snapStock(749.9994, 0.001)).toBe(749.999);
  });
  it('treats an unreadable value as empty', () => {
    expect(snapStock(NaN, 1)).toBe(0);
    expect(snapStock(Infinity, 1)).toBe(0);
  });
});

describe('normalizeIcon', () => {
  it('keeps a real mdi name, folded and trimmed', () => {
    expect(normalizeIcon('mdi:pill')).toBe('mdi:pill');
    expect(normalizeIcon('  MDI:Air-Filter ')).toBe('mdi:air-filter');
  });

  it('clamps anything the companion app could not resolve', () => {
    // The app draws nothing at all for a name it does not have, and says nothing about
    // it. '' is the visible fallback: the Home Assistant icon the user already had.
    for (const bad of ['', null, undefined, 7, 'pill', 'mdi:', 'hass:pill', 'mdi:a b']) {
      expect(normalizeIcon(bad)).toBe('');
    }
  });

  it('refuses a name that could break out of an attribute', () => {
    for (const hostile of ['mdi:pill" onload="x', "mdi:pill'>", 'mdi:pill<script>', 'mdi:a:b']) {
      expect(normalizeIcon(hostile)).toBe('');
    }
  });
});

describe('notifyRowChip', () => {
  it('paints the accent and draws the glyph', () => {
    const html = notifyRowChip('mdi:pill', '#E53935');
    expect(html).toContain('background:#e53935');
    expect(html).toContain('<ha-icon icon="mdi:pill">');
  });

  it('builds nothing without an icon', () => {
    // A row that has no icon must look exactly as it did before this field existed.
    expect(notifyRowChip('', '#e53935')).toBe('');
    expect(notifyRowChip(null, null)).toBe('');
    expect(notifyRowChip('not-an-icon', '#e53935')).toBe('');
  });

  it('falls back to a theme color rather than an unusable one', () => {
    for (const bad of ['', null, 'red', '#fff', 'red;background:url(x)']) {
      const html = notifyRowChip('mdi:pill', bad);
      expect(html).toContain('background:var(--secondary-text-color)');
      expect(html).not.toContain('url(');
    }
  });

  it('never lets a stored value reach the markup unchecked', () => {
    // Both halves land in attributes, so both are gated at the source rather than
    // escaped after the fact: the icon by its character set, the color by its shape.
    const html = notifyRowChip('mdi:pill" onload="alert(1)', '#000000"onload="alert(1)');
    expect(html).toBe('');
  });
});
