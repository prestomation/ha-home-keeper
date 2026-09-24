/**
 * The task list's layout decisions.
 *
 * What is asserted here is what a compact card says and what it offers: which
 * layout a stored value means, the short due text a board card has room for, the
 * urgency a card colours itself with, and which rows the action sheet gets. All
 * of it is user-visible behaviour rather than markup, and all of it is on the
 * mutation surface.
 */

import { describe, expect, it } from 'vitest';
import {
  TASK_LAYOUTS,
  boardColumnLabel,
  parseTaskLayout,
  sheetActions,
  sheetFlags,
  shortDueLabel,
  urgencyClass,
} from '../src/task-layout.ts';

// Pinned, because every due figure below is counted from it.
const NOW = new Date('2026-06-13T12:00:00Z');

const task = (over = {}) => ({
  id: 't1',
  name: 'Replace filter',
  recurrence_type: 'floating',
  interval: 3,
  unit: 'months',
  completions: [],
  ...over,
});

const verbs = (over = {}) => ({ snooze: false, skip: false, dueToday: false, ...over });

describe('parseTaskLayout', () => {
  it('keeps every layout it offers', () => {
    expect(TASK_LAYOUTS).toEqual(['rows', 'tiles', 'board']);
    for (const value of TASK_LAYOUTS) expect(parseTaskLayout(value)).toBe(value);
  });

  it('falls back to rows for anything it does not know', () => {
    // The value comes out of a shared per-user store, so it can be an older
    // panel's word, a hand edit, or nothing at all.
    for (const junk of [undefined, null, '', 'grid', 'ROWS', 0, 1, true, {}, ['tiles']]) {
      expect(parseTaskLayout(junk)).toBe('rows');
    }
  });
});

describe('shortDueLabel', () => {
  it('says Disabled for a disabled task in place of a count of days', () => {
    expect(shortDueLabel(task({ next_due: '2020-01-01T00:00:00Z', enabled: false }), NOW)).toBe('Disabled');
    expect(shortDueLabel(task({ next_due: '2020-01-01T00:00:00Z', enabled: true }), NOW)).not.toBe('Disabled');
  });

  it('counts an overdue task in whole days', () => {
    expect(shortDueLabel(task({ next_due: '2026-02-04T12:00:00Z' }), NOW)).toBe('129d');
    expect(shortDueLabel(task({ next_due: '2026-06-12T23:00:00Z' }), NOW)).toBe('1d');
  });

  it('counts an upcoming task in whole days', () => {
    expect(shortDueLabel(task({ next_due: '2026-07-13T12:00:00Z' }), NOW)).toBe('in 30d');
    expect(shortDueLabel(task({ next_due: '2026-06-14T01:00:00Z' }), NOW)).toBe('in 1d');
  });

  it('reads Today all day, whichever side of the hour it is', () => {
    // Calendar days, not elapsed hours: a task due at 09:00 must not turn into
    // "1d" at 09:01 for someone reading the board at lunchtime.
    expect(shortDueLabel(task({ next_due: '2026-06-13T09:00:00Z' }), NOW)).toBe('Today');
    expect(shortDueLabel(task({ next_due: '2026-06-13T22:00:00Z' }), NOW)).toBe('Today');
  });

  it('says Armed for a dormant monitored task', () => {
    expect(shortDueLabel(task({ recurrence_type: 'triggered' }), NOW)).toBe('Armed');
    const watched = task({ recurrence_type: 'sensor', sensor: { mode: 'threshold' } });
    expect(shortDueLabel(watched, NOW)).toBe('Armed');
  });

  it('says Done for a completed one-off', () => {
    const done = task({
      recurrence_type: 'one-off',
      last_completed: '2026-06-01T12:00:00Z',
    });
    expect(shortDueLabel(done, NOW)).toBe('Done');
  });

  it('counts in whole days from whatever hour it is read at', () => {
    // Built from local parts, because the day count is a local one.
    const evening = new Date(2026, 5, 13, 23, 0);
    const nextMorning = new Date(2026, 5, 14, 1, 0).toISOString();
    expect(shortDueLabel(task({ next_due: nextMorning }), evening)).toBe('in 1d');
  });

  it('says Done only for a one-off that is finished', () => {
    // Every part of the rule is load-bearing. A repeating task's completion does
    // not end it, and a one-off still carrying a date is not finished.
    const repeating = task({ last_completed: '2026-06-01T12:00:00Z' });
    expect(shortDueLabel(repeating, NOW)).toBe('');
    const again = task({
      recurrence_type: 'one-off',
      next_due: '2026-06-20T12:00:00Z',
      last_completed: '2026-06-01T12:00:00Z',
    });
    expect(shortDueLabel(again, NOW)).toBe('in 7d');
  });

  it('says nothing when there is no date to say', () => {
    expect(shortDueLabel(task({ recurrence_type: 'one-off' }), NOW)).toBe('');
    expect(shortDueLabel(task({ next_due: 'not-a-date' }), NOW)).toBe('');
  });
});

describe('urgencyClass', () => {
  it('leaves a disabled task plain, whatever its frozen date says', () => {
    expect(urgencyClass(task({ next_due: '2020-01-01T00:00:00Z', enabled: false }), NOW)).toBe('');
    expect(urgencyClass(task({ next_due: '2020-01-01T00:00:00Z', enabled: true }), NOW)).toBe('overdue');
  });

  it('colours an overdue task', () => {
    expect(urgencyClass(task({ next_due: '2026-06-10T12:00:00Z' }), NOW)).toBe('overdue');
  });

  it('colours a task due inside the soon window', () => {
    expect(urgencyClass(task({ next_due: '2026-06-15T12:00:00Z' }), NOW)).toBe('soon');
  });

  it('leaves a later task and a dormant one plain', () => {
    expect(urgencyClass(task({ next_due: '2026-09-01T12:00:00Z' }), NOW)).toBe('');
    expect(urgencyClass(task({ recurrence_type: 'triggered' }), NOW)).toBe('');
  });

  it('leaves a buy reminder plain although every filter calls it overdue', () => {
    // Minted with no due date, so it is late from the moment a part goes low.
    // The pill says "Low stock" for the same reason the rail stays uncoloured.
    const buy = task({
      recurrence_type: 'one-off',
      next_due: '2026-06-10T12:00:00Z',
      source: { buy: { asset_id: 'a1', part_id: 'p1' } },
    });
    expect(urgencyClass(buy, NOW)).toBe('');
  });
});

describe('sheetFlags', () => {
  it('reads a plain task as able to do everything', () => {
    expect(sheetFlags(task({ next_due: '2026-06-20T12:00:00Z' }))).toEqual({
      dormant: false,
      completedOneOff: false,
      blocked: false,
    });
  });

  it('reads a dormant monitored task', () => {
    expect(sheetFlags(task({ recurrence_type: 'triggered' })).dormant).toBe(true);
    const watched = task({ recurrence_type: 'sensor', sensor: { mode: 'threshold' } });
    expect(sheetFlags(watched).dormant).toBe(true);
  });

  it('reads a completed one-off', () => {
    const done = task({ recurrence_type: 'one-off', last_completed: '2026-06-01T12:00:00Z' });
    expect(sheetFlags(done).completedOneOff).toBe(true);
    // Each part of the rule is load-bearing on its own.
    expect(sheetFlags(task({ recurrence_type: 'one-off' })).completedOneOff).toBe(false);
    const repeating = task({ last_completed: '2026-06-01T12:00:00Z' });
    expect(sheetFlags(repeating).completedOneOff).toBe(false);
    const again = task({
      recurrence_type: 'one-off',
      next_due: '2026-06-20T12:00:00Z',
      last_completed: '2026-06-01T12:00:00Z',
    });
    expect(sheetFlags(again).completedOneOff).toBe(false);
  });

  it('reads a task its owner clears for it as blocked', () => {
    const blocked = task({ next_due: '2026-06-20T12:00:00Z', managed_by: { completion_blocked: true } });
    expect(sheetFlags(blocked).blocked).toBe(true);
  });
});

describe('sheetActions', () => {
  const ids = (list) => list.map((a) => a.id);
  const plain = { dormant: false, completedOneOff: false, blocked: false };

  it('orders the rows Done, Snooze, Skip, Due today, Open task', () => {
    const all = sheetActions(verbs({ snooze: true, skip: true, dueToday: true }), plain);
    expect(ids(all)).toEqual(['done', 'snooze', 'skip', 'dueToday', 'open']);
    expect(all.every((a) => a.blocked === false)).toBe(true);
  });

  it('drops each verb its switch turns off, and only that one', () => {
    expect(ids(sheetActions(verbs({ skip: true, dueToday: true }), plain))).toEqual([
      'done',
      'skip',
      'dueToday',
      'open',
    ]);
    expect(ids(sheetActions(verbs({ snooze: true, dueToday: true }), plain))).toEqual([
      'done',
      'snooze',
      'dueToday',
      'open',
    ]);
    expect(ids(sheetActions(verbs({ snooze: true, skip: true }), plain))).toEqual([
      'done',
      'snooze',
      'skip',
      'open',
    ]);
  });

  it('drops Done for a dormant task and for a completed one-off', () => {
    expect(ids(sheetActions(verbs(), { ...plain, dormant: true }))).toEqual(['open']);
    expect(ids(sheetActions(verbs(), { ...plain, completedOneOff: true }))).toEqual(['open']);
  });

  it('keeps a blocked Done, and marks it', () => {
    // It stays on the sheet because "this cannot be completed here" is what the
    // person pressing it needs to be told.
    const rows = sheetActions(verbs({ snooze: true }), { ...plain, blocked: true });
    expect(ids(rows)).toEqual(['done', 'snooze', 'open']);
    expect(rows[0].blocked).toBe(true);
    expect(rows[1].blocked).toBe(false);
  });

  it('always ends with Open task', () => {
    const cases = [
      [verbs(), plain],
      [verbs({ snooze: true, skip: true, dueToday: true }), plain],
      [verbs({ skip: true }), { ...plain, dormant: true }],
      [verbs(), { ...plain, blocked: true }],
    ];
    for (const [v, f] of cases) {
      const rows = sheetActions(v, f);
      expect(rows[rows.length - 1].id).toBe('open');
      expect(ids(rows).filter((id) => id === 'open').length).toBe(1);
    }
  });
});

describe('boardColumnLabel', () => {
  it('keeps a group that has a label', () => {
    expect(boardColumnLabel('Kitchen')).toBe('Kitchen');
  });

  it('heads the one unlabelled group with All', () => {
    // Group by none makes a single unlabelled group, and a column needs a head
    // to be a column.
    expect(boardColumnLabel('')).toBe('All');
  });
});
