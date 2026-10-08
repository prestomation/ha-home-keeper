/**
 * The set due time of floating tasks (#438) on the panel side.
 *
 * `setDueTime` reads the option the way the backend does, `snapToDueTime` and the
 * snooze target give the instant the backend writes, and `formatDue` hides a time
 * of day that says nothing. All four decide what a user sees.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { snoozeHintText, snoozeStateFor, snoozeTarget } from '../src/defer.ts';
import { dueTimeSchema } from '../src/forms.ts';
import { t } from '../src/i18n.ts';
import {
  formatDate,
  formatDateTime,
  formatDue,
  setDueTime,
  setTimeZone,
  snapToDueTime,
} from '../src/utils.ts';

const TZ = 'America/Los_Angeles';

beforeEach(() => setTimeZone(TZ));
afterEach(() => setTimeZone(undefined));

describe('setDueTime', () => {
  it('is null unless the mode is set_time', () => {
    expect(setDueTime(undefined)).toBeNull();
    expect(setDueTime({})).toBeNull();
    expect(setDueTime({ due_time_mode: 'completion', due_time: '07:00' })).toBeNull();
  });

  it('reads the time as HH:MM', () => {
    expect(setDueTime({ due_time_mode: 'set_time', due_time: '07:30' })).toBe('07:30');
    expect(setDueTime({ due_time_mode: 'set_time', due_time: '7:05:00' })).toBe('07:05');
    expect(setDueTime({ due_time_mode: 'set_time', due_time: '23:59' })).toBe('23:59');
  });

  it('reads a value that is not a time as 08:00', () => {
    for (const bad of [undefined, '', 'noon', '24:00', '12:60', '1:2']) {
      expect(setDueTime({ due_time_mode: 'set_time', due_time: bad })).toBe('08:00');
    }
  });
});

describe('snapToDueTime', () => {
  // 22:42 on 5 Jan 2027 in Los Angeles (PST, UTC-8).
  const late = new Date('2027-01-06T06:42:00Z');

  it('returns the same instant without a due time', () => {
    expect(snapToDueTime(late, null)).toBe(late);
  });

  it('keeps the local date', () => {
    expect(snapToDueTime(late, '08:00').toISOString()).toBe('2027-01-05T16:00:00.000Z');
  });

  it('rounds up to the next set time', () => {
    expect(snapToDueTime(late, '08:00', true).toISOString()).toBe('2027-01-06T16:00:00.000Z');
    // 07:00 local: the set time today.
    const early = new Date('2027-01-05T15:00:00Z');
    expect(snapToDueTime(early, '08:00', true).toISOString()).toBe('2027-01-05T16:00:00.000Z');
    // At the set time: no change.
    const exact = new Date('2027-01-05T16:00:00Z');
    expect(snapToDueTime(exact, '08:00', true).toISOString()).toBe(exact.toISOString());
  });

  it('keeps the wall time across daylight saving', () => {
    // 14 Mar 2027 is the spring change: 08:00 is PDT (UTC-7).
    const day = new Date('2027-03-14T20:00:00Z');
    expect(snapToDueTime(day, '08:00').toISOString()).toBe('2027-03-14T15:00:00.000Z');
  });
});

describe('formatDue', () => {
  const atEight = '2027-01-05T16:00:00Z';
  const atNine = '2027-01-05T17:00:00Z';

  it('shows only the date at the set due time', () => {
    expect(formatDue(atEight, '08:00', 'en')).toBe(formatDate(atEight, 'en'));
  });

  it('keeps the time at any other time, or without a set time', () => {
    expect(formatDue(atNine, '08:00', 'en')).toBe(formatDateTime(atNine, 'en'));
    expect(formatDue(atEight, null, 'en')).toBe(formatDateTime(atEight, 'en'));
  });

  it('is empty for no date', () => {
    expect(formatDue(null, '08:00')).toBe('');
    expect(formatDue('not a date', '08:00')).toBe('');
  });
});

describe('snooze with a set due time', () => {
  // 22:00 on 15 Sep 2026 in Los Angeles (PDT, UTC-7).
  const NOW = new Date('2026-09-16T05:00:00Z');
  const floating = {
    id: 't1',
    name: 'Furnace filter',
    recurrence_type: 'floating',
    next_due: '2026-09-15T15:00:00Z',
  };

  it('keeps the set due time only for a floating task', () => {
    expect(snoozeStateFor(floating, NOW, '08:00').dueTime).toBe('08:00');
    const fixed = { ...floating, recurrence_type: 'fixed' };
    expect('dueTime' in snoozeStateFor(fixed, NOW, '08:00')).toBe(false);
  });

  it('rounds a preset up to the next set time', () => {
    const s = { ...snoozeStateFor(floating, NOW, '08:00'), preset: '1h' };
    // 23:00 tonight becomes 08:00 tomorrow.
    expect(snoozeTarget(s, NOW)?.toISOString()).toBe('2026-09-16T15:00:00.000Z');
  });

  it('lands a custom date at the set time on that date', () => {
    const s = {
      ...snoozeStateFor(floating, NOW, '08:00'),
      preset: 'custom',
      customAt: '2026-09-20',
    };
    expect(snoozeTarget(s, NOW)?.toISOString()).toBe('2026-09-20T15:00:00.000Z');
  });

  it('opens a custom length as a date only', () => {
    const s = snoozeStateFor({ ...floating, snooze_hours: 30 }, NOW, '08:00');
    expect(s.preset).toBe('custom');
    expect(s.customAt).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('refuses a custom date whose set time is not later than now', () => {
    const s = {
      ...snoozeStateFor(floating, NOW, '08:00'),
      preset: 'custom',
      customAt: '2026-09-15',
    };
    expect(snoozeTarget(s, NOW)).toBeNull();
  });

  it('states the date without the time', () => {
    const s = { ...snoozeStateFor(floating, NOW, '08:00'), preset: '1d' };
    const until = snoozeTarget(s, NOW);
    expect(snoozeHintText(s, 'en', NOW)).toBe(
      t('defer.snoozeResolves', { date: formatDate(until.toISOString(), 'en') }),
    );
  });
});

describe('dueTimeSchema', () => {
  it('shows the time field only for a set time', () => {
    expect(dueTimeSchema('completion').map((f) => f.name)).toEqual(['due_time_mode']);
    expect(dueTimeSchema(undefined).map((f) => f.name)).toEqual(['due_time_mode']);
    expect(dueTimeSchema('set_time').map((f) => f.name)).toEqual(['due_time_mode', 'due_time']);
    expect(dueTimeSchema('set_time')[1].selector).toEqual({ time: {} });
  });
});
