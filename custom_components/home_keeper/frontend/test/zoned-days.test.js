import { afterEach, describe, expect, it } from 'vitest';
import { statusBucket } from '../src/card-filter.ts';
import { partFirstDue } from '../src/forms.ts';
import {
  dueLabel,
  endOfZonedDay,
  formatDate,
  setTimeZone,
  zonedDayNumber,
  zonedMidnight,
} from '../src/utils.ts';

// X04-7: "today" and "tomorrow" are days in Home Assistant's zone, the days the to-do
// list and the calendar use. Each test names its zone, so the result does not depend
// on the zone the suite runs in.
afterEach(() => setTimeZone(undefined));

// 16:50 on Sep 30 in New York is 05:50 on Oct 1 in Tokyo.
const NOW = Date.UTC(2026, 8, 30, 20, 50);
// 09:00 on Oct 1 in New York is 22:00 on Oct 1 in Tokyo.
const DUE = '2026-10-01T13:00:00Z';

const task = (next_due) => ({ id: 't', name: 'Filter', recurrence_type: 'floating', next_due });

describe('dueLabel in the HA zone', () => {
  it('counts the day in the HA zone, not in the browser zone', () => {
    setTimeZone('America/New_York');
    expect(dueLabel(task(DUE), new Date(NOW))).toBe('tomorrow');
    setTimeZone('Asia/Tokyo');
    expect(dueLabel(task(DUE), new Date(NOW))).toBe('today');
  });

  it('counts whole days across a month end', () => {
    setTimeZone('Asia/Tokyo');
    expect(dueLabel(task('2026-10-03T13:00:00Z'), new Date(NOW))).toBe('in 2 days');
    expect(dueLabel(task('2026-09-29T13:00:00Z'), new Date(NOW))).toBe('2 days ago');
    expect(dueLabel(task('2026-09-30T13:00:00Z'), new Date(NOW))).toBe('yesterday');
  });

  it('does not throw on a due date it cannot read', () => {
    const unzoned = dueLabel(task('not-a-date'), new Date(NOW));
    setTimeZone('Asia/Tokyo');
    expect(dueLabel(task('not-a-date'), new Date(NOW))).toBe(unzoned);
  });
});

describe('statusBucket in the HA zone', () => {
  it('ends today at midnight in the HA zone', () => {
    setTimeZone('America/New_York');
    expect(statusBucket(task(DUE), NOW)).toBe('soon');
    setTimeZone('Asia/Tokyo');
    expect(statusBucket(task(DUE), NOW)).toBe('today');
  });
});

describe('zoned day helpers', () => {
  it('gives the last millisecond of the day in the HA zone', () => {
    setTimeZone('America/New_York');
    expect(endOfZonedDay(NOW)).toBe(Date.UTC(2026, 9, 1, 4) - 1);
    setTimeZone('Asia/Tokyo');
    expect(endOfZonedDay(NOW)).toBe(Date.UTC(2026, 9, 1, 15) - 1);
  });

  it('uses the browser zone when no zone is set', () => {
    const local = new Date(NOW);
    local.setHours(23, 59, 59, 999);
    expect(endOfZonedDay(NOW)).toBe(local.getTime());
    expect(zonedMidnight(2026, 10, 1)).toEqual(new Date(2026, 9, 1));
    expect(zonedDayNumber(NOW + 86_400_000) - zonedDayNumber(NOW)).toBe(1);
  });

  it('gives the midnight that starts a date in the HA zone', () => {
    setTimeZone('Asia/Tokyo');
    expect(zonedMidnight(2026, 10, 1).getTime()).toBe(Date.UTC(2026, 8, 30, 15));
    setTimeZone('America/New_York');
    expect(zonedMidnight(2026, 10, 1).getTime()).toBe(Date.UTC(2026, 9, 1, 4));
  });

  it('numbers the calendar days of the HA zone', () => {
    setTimeZone('America/New_York');
    expect(zonedDayNumber(NOW)).toBe(Date.UTC(2026, 8, 30) / 86_400_000);
    setTimeZone('Asia/Tokyo');
    expect(zonedDayNumber(NOW)).toBe(Date.UTC(2026, 9, 1) / 86_400_000);
  });
});

describe('partFirstDue in the HA zone', () => {
  const wear = { name: 'Filter', replace_interval: 6, replace_unit: 'months' };

  it('is the start of the due date in the HA zone, so the date reads the same', () => {
    for (const zone of ['Asia/Tokyo', 'America/New_York']) {
      setTimeZone(zone);
      const first = partFirstDue({ ...wear, last_replaced: '2026-03-03' });
      expect(first.getTime()).toBe(zonedMidnight(2026, 9, 3).getTime());
      expect(formatDate(first, 'en-US')).toBe('Sep 3, 2026');
    }
  });

  it('clamps and adds days on the calendar, whatever the zone', () => {
    setTimeZone('Pacific/Kiritimati');
    expect(formatDate(partFirstDue({ ...wear, replace_interval: 1, last_replaced: '2026-01-31' }), 'en-US')).toBe(
      'Feb 28, 2026',
    );
    expect(
      formatDate(
        partFirstDue({ ...wear, replace_interval: 10, replace_unit: 'days', last_replaced: '2026-03-03' }),
        'en-US',
      ),
    ).toBe('Mar 13, 2026');
  });
});
