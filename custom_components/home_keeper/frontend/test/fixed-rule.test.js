/**
 * A fixed task's rule through the form: what the form shows, what it sends, what the
 * summary says, and the "A later date" helpers the snooze dialog uses.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import {
  defaultMoveTo,
  emptySnoozeState,
  moveHintText,
  moveTarget,
  occurrenceOrigin,
  offersLaterDates,
  pickOccurrence,
} from '../src/defer.ts';
import {
  buildTaskPayload,
  duplicateTaskSeed,
  formRule,
  formRecurrenceSummary,
  taskFormData,
  taskRule,
  taskSchemaSections,
} from '../src/forms.ts';
import { setLanguage, t } from '../src/i18n.ts';
import { formatOccurrence, recurrenceSummary } from '../src/utils.ts';

const fixed = (over = {}) => ({
  id: 't1',
  name: 'Take trash out',
  recurrence_type: 'fixed',
  rrule: 'FREQ=WEEKLY;BYDAY=TU,FR',
  anchor: '2026-09-29T07:00:00-07:00',
  ...over,
});

beforeEach(() => setLanguage('en'));

describe('taskRule', () => {
  it('reads the rule, or the legacy pair when there is none', () => {
    expect(taskRule(fixed())).toBe('FREQ=WEEKLY;BYDAY=TU,FR');
    expect(taskRule({ freq: 'MONTHLY', interval: 3 })).toBe('FREQ=MONTHLY;INTERVAL=3');
    expect(taskRule({})).toBe('FREQ=DAILY;INTERVAL=1');
    expect(taskRule({ freq: 'HOURLY', interval: 0 })).toBe('FREQ=DAILY;INTERVAL=1');
  });
});

describe('the form reads Repeats and Every from the rule', () => {
  it('shows a simple rule in the controls', () => {
    const data = taskFormData(fixed({ rrule: 'FREQ=WEEKLY;INTERVAL=2;BYDAY=TU' }));
    expect(data).toMatchObject({ freq: 'WEEKLY', interval: 2, rrule: 'FREQ=WEEKLY;INTERVAL=2;BYDAY=TU' });
  });

  it('shows a custom rule as what it would reset to', () => {
    const data = taskFormData(fixed({ rrule: 'FREQ=MONTHLY;INTERVAL=2;BYDAY=1TU' }));
    expect(data).toMatchObject({ freq: 'MONTHLY', interval: 2, rrule: 'FREQ=MONTHLY;INTERVAL=2;BYDAY=1TU' });
  });

  it('builds the rule from the legacy pair of an old record', () => {
    const data = taskFormData({ recurrence_type: 'fixed', freq: 'DAILY', interval: 3 });
    expect(data).toMatchObject({ freq: 'DAILY', interval: 3, rrule: 'FREQ=DAILY;INTERVAL=3' });
  });

  it('leaves another kind its own interval', () => {
    const data = taskFormData({ recurrence_type: 'floating', interval: 5, unit: 'days' });
    expect(data).toMatchObject({ interval: 5, freq: 'DAILY', rrule: '' });
  });
});

describe('the fixed sections', () => {
  const fields = (task) =>
    Object.fromEntries(taskSchemaSections(task).map((s) => [s.key, s.fields]));

  it('greys Repeats and Every out for a custom rule and opens the rule box', () => {
    const custom = fields(fixed({ rrule: 'FREQ=MONTHLY;BYDAY=1TU' }));
    const [grid] = custom.cadence;
    expect(grid.schema.map((f) => [f.name, f.disabled])).toEqual([
      ['interval', true],
      ['freq', true],
    ]);
    const box = custom.rule.find((f) => f.name === 'rule_advanced');
    expect(box).toMatchObject({ type: 'expandable', flatten: true, expanded: true });
    expect(box.schema.map((f) => f.name)).toEqual(['rrule']);
  });

  it('leaves a simple rule editable and its box closed', () => {
    const simple = fields(fixed());
    expect(simple.cadence[0].schema.map((f) => f.disabled)).toEqual([false, false]);
    expect(simple.rule.find((f) => f.name === 'rule_advanced').expanded).toBe(false);
  });

  it('offers yearly', () => {
    const freq = fields(fixed()).cadence[0].schema[1];
    expect(freq.selector.select.options.map((o) => o.value)).toEqual([
      'DAILY',
      'WEEKLY',
      'MONTHLY',
      'YEARLY',
    ]);
  });

  it('puts the start, the rule and Last completed after the cadence', () => {
    const names = fields(fixed({ id: undefined })).rule.flatMap((f) =>
      f.schema ? f.schema.map((x) => x.name) : [f.name],
    );
    expect(names).toEqual(['anchor', 'rrule', 'last_completed']);
  });

  it('hides the rule when a managing integration locks it', () => {
    const locked = fields(fixed({ managed_by: { locked_fields: ['rrule'] } }));
    expect(locked.cadence).toEqual([]);
    expect(locked.rule.map((f) => f.name)).toEqual(['anchor']);
  });

  it('has no rule section for another kind', () => {
    expect(fields({ recurrence_type: 'floating' }).rule).toBeUndefined();
  });
});

describe('formRule', () => {
  it('takes Repeats and Every from the form for a simple rule', () => {
    // The card's form changes only freq/interval; the rule has to follow them.
    expect(formRule(fixed({ freq: 'WEEKLY', interval: 2 }))).toBe(
      'FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,FR',
    );
    expect(formRule(fixed({ freq: 'MONTHLY', interval: 1 }))).toBe('FREQ=MONTHLY;INTERVAL=1');
  });

  it('leaves the rule alone when the form agrees with it', () => {
    expect(formRule(fixed({ freq: 'WEEKLY', interval: 1 }))).toBe('FREQ=WEEKLY;BYDAY=TU,FR');
    expect(formRule(fixed())).toBe('FREQ=WEEKLY;BYDAY=TU,FR');
  });

  it('ignores a frequency the menu does not offer and a bad interval', () => {
    expect(formRule(fixed({ freq: 'HOURLY', interval: 0 }))).toBe('FREQ=WEEKLY;BYDAY=TU,FR');
  });

  it('never rewrites a custom rule', () => {
    const rule = 'FREQ=MONTHLY;BYDAY=1TU';
    expect(formRule(fixed({ rrule: rule, freq: 'DAILY', interval: 3 }))).toBe(rule);
  });
});

describe('the payload', () => {
  it('sends the rule and never the legacy pair', () => {
    const payload = buildTaskPayload(fixed({ interval: 1, freq: 'WEEKLY' }));
    expect(payload.rrule).toBe('FREQ=WEEKLY;BYDAY=TU,FR');
    expect(payload).not.toHaveProperty('interval');
    expect(payload).not.toHaveProperty('freq');
    expect(new Date(payload.anchor).toISOString()).toBe('2026-09-29T14:00:00.000Z');
  });

  it('turns an old record into a rule', () => {
    const payload = buildTaskPayload({ name: 'x', recurrence_type: 'fixed', freq: 'MONTHLY', interval: 2 });
    expect(payload.rrule).toBe('FREQ=MONTHLY;INTERVAL=2');
  });

  it('copies the rule, not the moves, into a duplicate', () => {
    const seed = duplicateTaskSeed(
      fixed({ moved_occurrences: [{ from: 'a', to: 'b' }] }),
    );
    expect(seed.rrule).toBe('FREQ=WEEKLY;BYDAY=TU,FR');
    expect(seed).not.toHaveProperty('moved_occurrences');
  });
});

describe('the rule in words', () => {
  it('names the days of a weekly rule', () => {
    expect(recurrenceSummary(fixed())).toBe('Every week on Tuesday and Friday');
    expect(recurrenceSummary(fixed({ rrule: 'FREQ=WEEKLY;INTERVAL=2;BYDAY=MO' }))).toBe(
      'Every 2 weeks on Monday',
    );
  });

  it('names the start day of a weekly rule that names none', () => {
    // The anchor is read in the test machine's zone; noon keeps the weekday.
    expect(
      recurrenceSummary(fixed({ rrule: 'FREQ=WEEKLY', anchor: '2026-09-29T12:00:00' })),
    ).toBe('Every week on Tuesday');
  });

  it('says every week when there is no usable start', () => {
    expect(recurrenceSummary(fixed({ rrule: 'FREQ=WEEKLY', anchor: 'not a date' }))).toBe(
      'Every week',
    );
    expect(recurrenceSummary(fixed({ rrule: 'FREQ=WEEKLY', anchor: undefined }))).toBe(
      'Every week',
    );
  });

  it('says daily, monthly and yearly rules plainly', () => {
    expect(recurrenceSummary(fixed({ rrule: 'FREQ=DAILY' }))).toBe('Every day');
    expect(recurrenceSummary(fixed({ rrule: 'FREQ=MONTHLY;INTERVAL=3' }))).toBe(
      'Every 3 months',
    );
    expect(recurrenceSummary(fixed({ rrule: 'FREQ=YEARLY' }))).toBe('Every year');
    expect(recurrenceSummary(fixed({ rrule: 'FREQ=YEARLY;INTERVAL=2' }))).toBe(
      'Every 2 years',
    );
  });

  it('quotes a custom rule', () => {
    expect(recurrenceSummary(fixed({ rrule: 'RRULE:FREQ=MONTHLY;BYDAY=1TU' }))).toBe(
      'Custom rule: FREQ=MONTHLY;BYDAY=1TU',
    );
  });

  it('describes an old record from its legacy pair', () => {
    expect(recurrenceSummary({ recurrence_type: 'fixed', freq: 'WEEKLY', interval: 2 })).toBe(
      'Every 2 weeks',
    );
  });

  it('is what the form preview says', () => {
    expect(formRecurrenceSummary(fixed())).toBe('Every week on Tuesday and Friday');
  });

  it('uses a whole phrase for yearly in Danish', () => {
    setLanguage('da');
    expect(recurrenceSummary(fixed({ rrule: 'FREQ=YEARLY' }))).toBe('Hvert år');
  });
});

describe('A later date', () => {
  const row = { start: '2026-10-09T07:00:00-07:00', moved_from: null };
  const moved = { start: '2026-10-10T07:00:00-07:00', moved_from: '2026-10-09T07:00:00-07:00' };

  it('is offered only for a fixed task', () => {
    expect(offersLaterDates(fixed())).toBe(true);
    expect(offersLaterDates({ recurrence_type: 'floating' })).toBe(false);
    expect(offersLaterDates(null)).toBe(false);
  });

  it('moves a row by the date on the rule', () => {
    expect(occurrenceOrigin(row)).toBe(row.start);
    expect(occurrenceOrigin(moved)).toBe(moved.moved_from);
  });

  it('seeds the new date one day later at the same time', () => {
    const next = new Date(defaultMoveTo('2026-10-09T14:00:00Z'));
    expect(next.getTime() - new Date('2026-10-09T14:00:00Z').getTime()).toBe(86_400_000);
  });

  it('picks a row and resolves where it goes', () => {
    const s = { ...emptySnoozeState(), task: fixed(), mode: 'later', error: 'old' };
    expect(moveTarget(s)).toBeNull();
    expect(moveHintText(s, 'en')).toBe(t('defer.movePick'));
    pickOccurrence(s, row);
    expect(s.picked).toBe(row);
    expect(s.error).toBeUndefined();
    expect(moveTarget(s)).toBeInstanceOf(Date);
    expect(moveHintText(s, 'en')).toContain('moves to');
    s.moveTo = '';
    expect(moveTarget(s)).toBeNull();
    expect(moveHintText(s, 'en')).toBe(t('defer.snoozePickDate'));
    s.moveTo = 'not a date';
    expect(moveTarget(s)).toBeNull();
  });

  it('labels a date short', () => {
    expect(formatOccurrence('2026-10-09T12:00:00Z', 'en')).toMatch(/Fri, Oct 9/);
    expect(formatOccurrence('nope', 'en')).toBe('');
    expect(formatOccurrence(new Date('2026-10-09T12:00:00Z'), 'en')).toMatch(/Oct 9/);
  });
});
