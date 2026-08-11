import { beforeEach, describe, expect, it } from 'vitest';
import {
  formRecurrenceSummary,
  notifyFormData,
  notifyFormToNotification,
  notificationSchema,
  taskSchema,
} from '../src/forms.ts';
import { setLanguage } from '../src/i18n.ts';

// `taskSchema` decides which fields the edit form offers, and the notification
// round-trip decides what a delivery actually does. Both are pure structure
// builders, so their contract is the structure — a missing field is a control
// the user can't reach, and an extra one is a value a managing integration
// declared off-limits.

beforeEach(() => setLanguage('en'));

// `ha-form` groups the cadence fields inside an unnamed `grid` container, so a
// flat `map(f => f.name)` misses exactly the fields these tests care about.
const names = (fields) =>
  fields.flatMap((f) => (f.schema ? names(f.schema) : [f.name])).filter(Boolean);

describe('taskSchema by recurrence type', () => {
  it('offers "every N units" for a floating task', () => {
    expect(names(taskSchema({ recurrence_type: 'floating' }))).toEqual([
      'name',
      'notes',
      'recurrence_type',
      'interval',
      'unit',
      'last_completed',
      'device_id',
      'labels',
      'completion_detail',
    ]);
  });

  it('offers the calendar rule for a fixed task', () => {
    expect(names(taskSchema({ recurrence_type: 'fixed' }))).toEqual([
      'name',
      'notes',
      'recurrence_type',
      'interval',
      'freq',
      'anchor',
      'last_completed',
      'device_id',
      'labels',
      'completion_detail',
    ]);
  });

  it('offers a single due date for a one-off task', () => {
    // A do-once task has no cadence at all, and no "last done" seed — it has
    // never been done, and completing it retires it.
    expect(names(taskSchema({ recurrence_type: 'one-off' }))).toEqual([
      'name',
      'notes',
      'recurrence_type',
      'due',
      'device_id',
      'labels',
      'completion_detail',
    ]);
  });

  it('swaps the cadence unit for a calendar frequency between the two', () => {
    const floating = names(taskSchema({ recurrence_type: 'floating' }));
    const fixed = names(taskSchema({ recurrence_type: 'fixed' }));
    expect(floating).toContain('unit');
    expect(floating).not.toContain('freq');
    expect(fixed).toContain('freq');
    expect(fixed).not.toContain('unit');
  });

  it('offers a triggered task only its descriptive fields', () => {
    // Its state is owned by the integration watching the condition, so there is
    // no schedule to edit — offering one would let a user arm a dormant task.
    const got = names(taskSchema({ recurrence_type: 'triggered' }));
    expect(got).toEqual(['name', 'notes', 'device_id', 'labels']);
    for (const scheduling of ['interval', 'unit', 'freq', 'anchor', 'due', 'recurrence_type']) {
      expect(got).not.toContain(scheduling);
    }
  });
});

describe('taskSchema respects locked fields', () => {
  const locked = (fields) => ({
    recurrence_type: 'floating',
    managed_by: { integration: 'x', display_name: 'X', locked_fields: fields },
  });

  it('omits a locked field entirely rather than showing it disabled', () => {
    const unlocked = names(taskSchema({ recurrence_type: 'floating' }));
    const withLock = names(taskSchema(locked(['name'])));
    expect(unlocked).toContain('name');
    expect(withLock).not.toContain('name');
    // Everything else survives — locking one field must not blank the form.
    expect(withLock.length).toBe(unlocked.length - 1);
  });

  it('omits several locked fields at once', () => {
    const got = names(taskSchema(locked(['name', 'notes', 'device_id'])));
    for (const field of ['name', 'notes', 'device_id']) expect(got).not.toContain(field);
    // The unlocked remainder is untouched.
    expect(got).toContain('labels');
    expect(got).toContain('completion_detail');
  });

  it('treats an absent or empty locked_fields as nothing locked', () => {
    const base = names(taskSchema({ recurrence_type: 'floating' }));
    expect(names(taskSchema(locked([])))).toEqual(base);
    expect(
      names(taskSchema({ recurrence_type: 'floating', managed_by: { integration: 'x' } })),
    ).toEqual(base);
  });

  it('applies locking to a triggered task too', () => {
    const got = names(
      taskSchema({
        recurrence_type: 'triggered',
        managed_by: { integration: 'x', locked_fields: ['name', 'notes'] },
      }),
    );
    expect(got).toEqual(['device_id', 'labels']);
  });
});

describe('taskSchema card links', () => {
  const links = [{ value: 'a1:e1', label: 'Manual' }];

  it('offers the picker only when the appliance has links to show', () => {
    expect(names(taskSchema({ recurrence_type: 'floating' }, [], links))).toContain(
      'card_links',
    );
    // No links means no picker — an empty dropdown is worse than no control.
    expect(names(taskSchema({ recurrence_type: 'floating' }, [], []))).not.toContain(
      'card_links',
    );
    expect(names(taskSchema({ recurrence_type: 'floating' }))).not.toContain('card_links');
  });

  it('offers it for every task kind, including triggered', () => {
    for (const kind of ['floating', 'fixed', 'one-off', 'triggered']) {
      expect(names(taskSchema({ recurrence_type: kind }, [], links))).toContain('card_links');
    }
  });

  it('omits it when locked', () => {
    const task = {
      recurrence_type: 'floating',
      managed_by: { integration: 'x', locked_fields: ['card_links'] },
    };
    expect(names(taskSchema(task, [], links))).not.toContain('card_links');
  });
});

describe('formRecurrenceSummary', () => {
  it('is empty without a recurrence type', () => {
    expect(formRecurrenceSummary({})).toBe('');
    expect(formRecurrenceSummary({ recurrence_type: '' })).toBe('');
  });

  it('describes a floating cadence', () => {
    const summary = formRecurrenceSummary({
      recurrence_type: 'floating',
      interval: 3,
      unit: 'months',
    });
    expect(summary).toBeTruthy();
    expect(summary).toMatch(/3/);
  });

  it('does not describe a triggered task as a clock schedule', () => {
    // `buildTaskPayload` drops `recurrence_type` for a triggered task, so without
    // it being re-attached the summary falls through to the cadence branch and
    // reads "every day" — confident and wrong.
    const summary = formRecurrenceSummary({ recurrence_type: 'triggered', name: 'Filter' });
    expect(summary).not.toMatch(/every day/i);
  });

  it('never throws on a half-typed form', () => {
    // The summary renders under a form the user is still filling in, so every
    // intermediate state has to produce a string rather than an exception.
    for (const partial of [
      { recurrence_type: 'floating' },
      { recurrence_type: 'floating', interval: 'abc' },
      { recurrence_type: 'fixed' },
      { recurrence_type: 'fixed', freq: 'nonsense' },
      { recurrence_type: 'one-off' },
      { recurrence_type: 'not-a-kind' },
    ]) {
      expect(() => formRecurrenceSummary(partial)).not.toThrow();
      expect(formRecurrenceSummary(partial)).toBeTypeOf('string');
    }
  });
});

describe('notification form round-trip', () => {
  const notification = {
    id: 'n1',
    name: 'Evening walk',
    profile_id: 'p1',
    targets: ['mobile_app_phone'],
    actions: ['complete', 'snooze'],
    style: 'walk',
    snooze_hours: 12,
    auto: { overdue: true, due_soon: false },
  };

  it('flattens the nested auto block for ha-form', () => {
    expect(notifyFormData(notification)).toEqual({
      name: 'Evening walk',
      profile_id: 'p1',
      targets: ['mobile_app_phone'],
      actions: ['complete', 'snooze'],
      style: 'walk',
      snooze_hours: 12,
      auto_overdue: true,
      auto_due_soon: false,
    });
  });

  it('renders a null profile as an empty string for the select', () => {
    // ha-form's select has no concept of null; it would render "null" as a value.
    expect(notifyFormData({ ...notification, profile_id: null }).profile_id).toBe('');
  });

  it('rebuilds the notification, keeping the id', () => {
    expect(notifyFormToNotification('n1', notifyFormData(notification))).toEqual(notification);
  });

  it('turns an empty profile selection back into null, not ""', () => {
    const rebuilt = notifyFormToNotification('n1', { name: 'x', profile_id: '' });
    expect(rebuilt.profile_id).toBeNull();
  });

  it('falls back to a name rather than saving a blank one', () => {
    for (const blank of ['', '   ', undefined, null]) {
      const rebuilt = notifyFormToNotification('n1', { name: blank });
      expect(rebuilt.name).toBeTruthy();
      expect(rebuilt.name.trim()).toBe(rebuilt.name);
    }
    expect(notifyFormToNotification('n1', { name: '  Padded  ' }).name).toBe('Padded');
  });

  it('defaults style and snooze, rejecting unusable values', () => {
    const rebuilt = notifyFormToNotification('n1', { name: 'x' });
    expect(rebuilt.style).toBe('walk');
    expect(rebuilt.snooze_hours).toBe(24);
    // 0 and NaN would mean "snooze forever" / "snooze never"; both fall back.
    expect(notifyFormToNotification('n1', { name: 'x', snooze_hours: 0 }).snooze_hours).toBe(24);
    expect(notifyFormToNotification('n1', { name: 'x', snooze_hours: 'abc' }).snooze_hours).toBe(
      24,
    );
    expect(notifyFormToNotification('n1', { name: 'x', snooze_hours: 6 }).snooze_hours).toBe(6);
  });

  it('coerces the auto switches to real booleans', () => {
    const rebuilt = notifyFormToNotification('n1', {
      name: 'x',
      auto_overdue: 'yes',
      auto_due_soon: undefined,
    });
    expect(rebuilt.auto).toEqual({ overdue: true, due_soon: false });
  });

  it('coerces list fields to arrays of strings', () => {
    const rebuilt = notifyFormToNotification('n1', { name: 'x', targets: 'nope', actions: [1] });
    expect(rebuilt.targets).toEqual([]);
    expect(rebuilt.actions).toEqual(['1']);
  });
});

describe('notificationSchema', () => {
  const profiles = [{ id: 'p1', name: 'Overdue' }];

  it('describes every notification field', () => {
    expect(names(notificationSchema(['mobile_app_phone'], profiles))).toEqual([
      'name',
      'profile_id',
      'targets',
      'actions',
      'style',
      'snooze_hours',
      'auto_overdue',
      'auto_due_soon',
    ]);
  });

  it('requires a name and a profile', () => {
    const fields = notificationSchema([], []);
    const required = fields.filter((f) => f.required).map((f) => f.name);
    // A delivery with no profile has nothing to send; a nameless one is unpickable.
    expect(required).toEqual(['name', 'profile_id']);
  });

  it('populates the profile dropdown from the live profiles', () => {
    const field = notificationSchema([], profiles).find((f) => f.name === 'profile_id');
    expect(field.selector.select.options).toEqual([{ value: 'p1', label: 'Overdue' }]);
  });

  it('populates targets from the live mobile_app list, multi-select', () => {
    const field = notificationSchema(['mobile_app_a', 'mobile_app_b'], []).find(
      (f) => f.name === 'targets',
    );
    expect(field.selector.select.options).toEqual([
      { value: 'mobile_app_a', label: 'mobile_app_a' },
      { value: 'mobile_app_b', label: 'mobile_app_b' },
    ]);
    expect(field.selector.select.multiple).toBe(true);
  });

  it('keeps snooze hours at a minimum of one', () => {
    const field = notificationSchema([], []).find((f) => f.name === 'snooze_hours');
    expect(field.selector.number.min).toBe(1);
  });
});
