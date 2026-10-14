import { describe, expect, it } from 'vitest';
import {
  WEEKDAYS,
  anchorDay,
  buildSimple,
  dayList,
  monthlyChoices,
  parseSimple,
  splitMonthBy,
  resetToSimple,
  ruleParts,
  shownDays,
  sortDays,
  toggleDay,
  weekdayName,
  weekdayOf,
  withSimpleChange,
} from '../src/rrule.ts';

// 2026-09-29 is a Tuesday.
const TUESDAY = anchorDay('2026-09-29T07:00:00-07:00');

describe('ruleParts', () => {
  it('splits and upper-cases, and drops an RRULE: prefix', () => {
    expect(ruleParts(' rrule:freq=weekly; byday=tu,fr ;')).toEqual({
      FREQ: 'WEEKLY',
      BYDAY: 'TU,FR',
    });
  });

  it('answers null for text without the KEY=VALUE shape', () => {
    expect(ruleParts('')).toBeNull();
    expect(ruleParts('FREQ')).toBeNull();
    expect(ruleParts('FREQ=')).toBeNull();
    expect(ruleParts('=WEEKLY')).toBeNull();
    expect(ruleParts(';;')).toBeNull();
  });
});

describe('parseSimple', () => {
  it('reads a weekly rule with days', () => {
    expect(parseSimple('FREQ=WEEKLY;INTERVAL=2;BYDAY=FR,TU')).toEqual({
      freq: 'WEEKLY',
      interval: 2,
      byday: ['TU', 'FR'],
    });
  });

  it('reads one weekday of the month for a monthly rule', () => {
    expect(parseSimple('FREQ=MONTHLY;INTERVAL=2;BYDAY=1TU')).toEqual({
      freq: 'MONTHLY',
      interval: 2,
      byday: [],
      monthBy: '1TU',
    });
    expect(parseSimple('FREQ=MONTHLY;BYDAY=-1FR')?.monthBy).toBe('-1FR');
    expect(buildSimple({ freq: 'MONTHLY', interval: 1, byday: [], monthBy: '-1FR' })).toBe(
      'FREQ=MONTHLY;INTERVAL=1;BYDAY=-1FR',
    );
  });

  it('keeps the weekday of the month through an Every change, and drops it for weekly', () => {
    expect(withSimpleChange('FREQ=MONTHLY;BYDAY=2TU', { interval: 3 })).toBe(
      'FREQ=MONTHLY;INTERVAL=3;BYDAY=2TU',
    );
    expect(withSimpleChange('FREQ=MONTHLY;BYDAY=2TU', { freq: 'WEEKLY' })).toBe(
      'FREQ=WEEKLY;INTERVAL=1',
    );
    expect(withSimpleChange('FREQ=MONTHLY;BYDAY=2TU', { monthBy: '' })).toBe(
      'FREQ=MONTHLY;INTERVAL=1',
    );
  });

  it('defaults the interval to 1 and the days to none', () => {
    expect(parseSimple('FREQ=MONTHLY')).toEqual({ freq: 'MONTHLY', interval: 1, byday: [] });
  });

  it('accepts the default week start', () => {
    expect(parseSimple('FREQ=WEEKLY;WKST=MO;BYDAY=TU')).not.toBeNull();
  });

  it.each([
    [''],
    [null],
    [undefined],
    ['nonsense'],
    ['FREQ=HOURLY'],
    ['FREQ=WEEKLY;WKST=SU'],
    ['FREQ=MONTHLY;BYDAY=5TU'],
    ['FREQ=MONTHLY;BYDAY=1TU,3TU'],
    ['FREQ=MONTHLY;BYDAY=TU'],
    ['FREQ=WEEKLY;BYDAY=1TU'],
    ['FREQ=WEEKLY;BYDAY=XX'],
    ['FREQ=MONTHLY;BYMONTHDAY=-1'],
    ['FREQ=YEARLY;BYMONTH=3'],
    ['FREQ=WEEKLY;INTERVAL=0'],
    ['FREQ=WEEKLY;INTERVAL=two'],
    ['FREQ=DAILY;COUNT=3'],
  ])('answers null for %s, which the controls cannot show', (rule) => {
    expect(parseSimple(rule)).toBeNull();
  });
});

describe('buildSimple', () => {
  it('writes the days in week order, and only for a weekly rule', () => {
    expect(buildSimple({ freq: 'WEEKLY', interval: 1, byday: ['FR', 'TU', 'FR'] })).toBe(
      'FREQ=WEEKLY;INTERVAL=1;BYDAY=TU,FR',
    );
    expect(buildSimple({ freq: 'MONTHLY', interval: 3, byday: ['TU'] })).toBe(
      'FREQ=MONTHLY;INTERVAL=3',
    );
    expect(buildSimple({ freq: 'WEEKLY', interval: 1, byday: [] })).toBe(
      'FREQ=WEEKLY;INTERVAL=1',
    );
  });

  it('clamps a bad interval to 1', () => {
    expect(buildSimple({ freq: 'DAILY', interval: 0, byday: [] })).toBe('FREQ=DAILY;INTERVAL=1');
    expect(buildSimple({ freq: 'DAILY', interval: 2.7, byday: [] })).toBe(
      'FREQ=DAILY;INTERVAL=2',
    );
    expect(buildSimple({ freq: 'DAILY', interval: Number.NaN, byday: [] })).toBe(
      'FREQ=DAILY;INTERVAL=1',
    );
  });

  it('round-trips through parseSimple', () => {
    const simple = { freq: 'WEEKLY', interval: 2, byday: ['MO', 'TH'] };
    expect(parseSimple(buildSimple(simple))).toEqual(simple);
  });
});

describe('resetToSimple', () => {
  it('keeps the frequency and interval and drops the rest', () => {
    expect(resetToSimple('FREQ=MONTHLY;INTERVAL=2;BYDAY=1TU')).toBe('FREQ=MONTHLY;INTERVAL=2');
  });

  it('falls back to every week', () => {
    expect(resetToSimple('FREQ=HOURLY;INTERVAL=x')).toBe('FREQ=WEEKLY;INTERVAL=1');
    expect(resetToSimple('')).toBe('FREQ=WEEKLY;INTERVAL=1');
    expect(resetToSimple(null)).toBe('FREQ=WEEKLY;INTERVAL=1');
    expect(resetToSimple('garbage')).toBe('FREQ=WEEKLY;INTERVAL=1');
  });
});

describe('withSimpleChange', () => {
  it('changes the interval and keeps the days', () => {
    expect(withSimpleChange('FREQ=WEEKLY;BYDAY=TU,FR', { interval: 2 })).toBe(
      'FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,FR',
    );
  });

  it('drops the days when the frequency changes', () => {
    expect(withSimpleChange('FREQ=WEEKLY;BYDAY=TU,FR', { freq: 'MONTHLY' })).toBe(
      'FREQ=MONTHLY;INTERVAL=1',
    );
  });

  it('keeps the days when the same frequency comes back', () => {
    expect(withSimpleChange('FREQ=WEEKLY;BYDAY=TU,FR', { freq: 'WEEKLY' })).toBe(
      'FREQ=WEEKLY;INTERVAL=1;BYDAY=TU,FR',
    );
  });

  it('ignores a frequency the menu does not offer', () => {
    expect(withSimpleChange('FREQ=DAILY;INTERVAL=3', { freq: 'HOURLY' })).toBe(
      'FREQ=DAILY;INTERVAL=3',
    );
  });

  it('never touches a custom rule', () => {
    const rule = 'FREQ=MONTHLY;BYMONTHDAY=1,15';
    expect(withSimpleChange(rule, { freq: 'DAILY', interval: 4 })).toBe(rule);
  });
});

describe('days', () => {
  it('reads the weekday of a start date', () => {
    expect(weekdayOf(TUESDAY)).toBe('TU');
    expect(weekdayOf(anchorDay('2026-10-04'))).toBe('SU');
    expect(weekdayOf(anchorDay('2026-10-05 00:00:00'))).toBe('MO');
  });

  it('takes the date as written, whatever the browser zone', () => {
    // 23:30 at -07:00 is already Wednesday in UTC; the anchor still says Tuesday.
    expect(weekdayOf(anchorDay('2026-09-29T23:30:00-07:00'))).toBe('TU');
    expect(anchorDay('2026-09-29T23:30:00-07:00').toISOString()).toBe(
      '2026-09-29T12:00:00.000Z',
    );
  });

  it('answers null for text that is not a date', () => {
    expect(anchorDay('')).toBeNull();
    expect(anchorDay(null)).toBeNull();
    expect(anchorDay(undefined)).toBeNull();
    expect(anchorDay('tomorrow')).toBeNull();
  });

  it('shows the rule days, or the start day when the rule names none', () => {
    expect(shownDays('FREQ=WEEKLY;BYDAY=FR,TU', TUESDAY)).toEqual(['TU', 'FR']);
    expect(shownDays('FREQ=WEEKLY', TUESDAY)).toEqual(['TU']);
    expect(shownDays('FREQ=WEEKLY', null)).toEqual([]);
    expect(shownDays('FREQ=MONTHLY', TUESDAY)).toEqual([]);
    expect(shownDays('FREQ=MONTHLY;BYDAY=1TU', TUESDAY)).toEqual([]);
  });

  it('adds a day to the shown days, so the start day stays', () => {
    expect(toggleDay('FREQ=WEEKLY;INTERVAL=1', 'FR', TUESDAY)).toBe(
      'FREQ=WEEKLY;INTERVAL=1;BYDAY=TU,FR',
    );
  });

  it('removes a day', () => {
    expect(toggleDay('FREQ=WEEKLY;BYDAY=TU,FR', 'TU', TUESDAY)).toBe(
      'FREQ=WEEKLY;INTERVAL=1;BYDAY=FR',
    );
  });

  it('will not remove the last day', () => {
    const rule = 'FREQ=WEEKLY;BYDAY=FR';
    expect(toggleDay(rule, 'FR', TUESDAY)).toBe(rule);
  });

  it('does nothing to a rule that is not simple weekly', () => {
    expect(toggleDay('FREQ=MONTHLY', 'FR', TUESDAY)).toBe('FREQ=MONTHLY');
    expect(toggleDay('FREQ=MONTHLY;BYDAY=1TU', 'FR', TUESDAY)).toBe('FREQ=MONTHLY;BYDAY=1TU');
  });

  it('sorts days into week order', () => {
    expect(sortDays(['SU', 'MO', 'FR'])).toEqual(['MO', 'FR', 'SU']);
    expect(WEEKDAYS).toHaveLength(7);
  });

  it('names days in the language asked for', () => {
    expect(weekdayName('TU', 'en', 'short')).toBe('Tue');
    expect(weekdayName('TU', 'en', 'long')).toBe('Tuesday');
    expect(weekdayName('MO', 'en')).toBe('Mon');
    expect(weekdayName('SU', 'de', 'long')).toBe('Sonntag');
    expect(weekdayName('SA', 'en', 'narrow')).toBe('S');
  });

  it('lists days as a sentence', () => {
    expect(dayList(['FR', 'TU'], 'en')).toBe('Tuesday and Friday');
    expect(dayList(['MO', 'WE', 'FR'], 'en')).toBe('Monday, Wednesday, and Friday');
  });
});

describe('monthlyChoices', () => {
  it('offers the day and the weekday of the month of the start date', () => {
    // Tue Oct 13 2026: the second Tuesday, and not in the last 7 days.
    expect(monthlyChoices(anchorDay('2026-10-13T07:00'))).toEqual(['', '2TU']);
  });

  it('offers the last weekday in the last 7 days, and no 5th weekday', () => {
    // Tue Sep 29 2026: the 5th Tuesday of a 30-day month.
    expect(monthlyChoices(anchorDay('2026-09-29T07:00'))).toEqual(['', '-1TU']);
    // Sun Oct 25 2026: the 4th Sunday, and also the last (Nov 1 is the next one).
    expect(monthlyChoices(anchorDay('2026-10-25T07:00'))).toEqual(['', '4SU', '-1SU']);
  });

  it('keeps a stored choice that the start date does not give', () => {
    expect(monthlyChoices(anchorDay('2026-10-13T07:00'), '1FR')).toEqual(['', '2TU', '1FR']);
    expect(monthlyChoices(null, '1FR')).toEqual(['', '1FR']);
  });

  it('splits a choice into its ordinal and weekday', () => {
    expect(splitMonthBy('2TU')).toEqual(['2', 'TU']);
    expect(splitMonthBy('-1FR')).toEqual(['last', 'FR']);
    expect(splitMonthBy('')).toBeNull();
  });
});
