import { beforeEach, describe, expect, it } from 'vitest';
import {
  assetIdentitySchema,
  buildTaskPayload,
  duplicateTaskSeed,
  formRecurrenceSummary,
  metadataSchema,
  notifyFormData,
  notifyFormToNotification,
  notificationSchema,
  pickFormData,
  problemSyncExclusionsSchema,
  problemSyncSchema,
  partSchema,
  problemSyncToggleSchema,
  profileSyncSchema,
  schemaFieldNames,
  selUnit,
  sensorLive,
  shoppingSchema,
  structuredDetailsSchema,
  taskFormData,
  taskSchema,
  taskSchemaSections,
  toProfileSync,
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

// The drawer renders one `ha-form` per section so it can put a heading between two
// fields, but the payload builder, the saved task and every test below are written
// against the flat schema. These two views of the same form must never drift: a
// field that exists in one and not the other is either a control the user cannot
// reach or a value that never gets saved.
describe('taskSchemaSections is exactly taskSchema, grouped', () => {
  const cases = [
    ['floating', { recurrence_type: 'floating' }],
    ['fixed', { recurrence_type: 'fixed' }],
    ['one-off', { recurrence_type: 'one-off' }],
    ['triggered', { recurrence_type: 'triggered' }],
    ['sensor / usage', { recurrence_type: 'sensor', sensor_mode: 'usage' }],
    ['sensor / usage with a backstop', {
      recurrence_type: 'sensor',
      sensor_mode: 'usage',
      sensor_backstop_on: true,
    }],
    ['sensor / threshold', { recurrence_type: 'sensor', sensor_mode: 'threshold' }],
    ['sensor / state', { recurrence_type: 'sensor', sensor_mode: 'state' }],
    ['a saved task (no last_completed seed)', { id: 't1', recurrence_type: 'floating' }],
    ['a managed task with locked fields', {
      recurrence_type: 'floating',
      managed_by: { domain: 'x', locked_fields: ['name', 'interval', 'device_id'] },
    }],
  ];
  const consumables = [{ value: 'a:p', label: 'Anode rod' }];
  const links = [{ value: 'doc:1', label: 'Manual' }];
  const tags = [{ value: 'tag_1', label: 'Kitchen sticker' }];

  for (const [label, task] of cases) {
    it(`flattens to the same fields, in the same order — ${label}`, () => {
      const sections = taskSchemaSections(task, consumables, links, tags);
      const flattened = sections.flatMap((s) => s.fields);
      expect(flattened).toEqual(taskSchema(task, consumables, links, tags));
      // Nothing is silently dropped on the way into a section.
      expect(names(flattened)).toEqual(names(taskSchema(task, consumables, links, tags)));
    });
  }

  it('puts the recurrence choice above the fields it reveals, and marks them dependent', () => {
    const sections = taskSchemaSections({ recurrence_type: 'floating' });
    const schedule = sections.findIndex((s) => s.key === 'schedule');
    const cadence = sections.findIndex((s) => s.key === 'cadence');
    expect(schedule).toBeGreaterThanOrEqual(0);
    expect(cadence).toBeGreaterThan(schedule);
    expect(names(sections[schedule].fields)).toEqual(['recurrence_type']);
    expect(names(sections[cadence].fields)).toEqual(['interval', 'unit', 'last_completed']);
    expect(sections[cadence].dependent).toBe(true);
    // Only the revealed run is dependent — the rest stand on their own.
    expect(sections.filter((s) => s.dependent).map((s) => s.key)).toEqual(['cadence']);
  });

  it('groups the descriptive fields apart from the placement ones', () => {
    const byKey = Object.fromEntries(
      taskSchemaSections({ recurrence_type: 'floating' }, [], [], tags).map((s) => [
        s.key,
        names(s.fields),
      ]),
    );
    expect(byKey.basics).toEqual(['name', 'notes']);
    expect(byKey.placement).toEqual([
      'device_id',
      'area_id',
      'tag_id',
      'require_tag_scan',
      'labels',
    ]);
    expect(byKey.completion).toEqual(['completion_detail']);
  });

  it('keeps a triggered task to the two sections it can actually edit', () => {
    const sections = taskSchemaSections({ recurrence_type: 'triggered' });
    expect(sections.map((s) => s.key)).toEqual(['basics', 'placement']);
    // No schedule section at all: an integration owns when a triggered task is due.
    expect(sections.some((s) => s.key === 'cadence')).toBe(false);
  });
});

describe('pickFormData', () => {
  it('keeps only the keys the schema offers', () => {
    const data = { name: 'x', notes: 'y', interval: 3, unit: 'months' };
    expect(pickFormData(data, [{ name: 'name' }, { name: 'notes' }])).toEqual({
      name: 'x',
      notes: 'y',
    });
  });

  it('reaches into a grid group, where the cadence fields live', () => {
    const data = { interval: 3, unit: 'months', name: 'x' };
    const schema = [{ name: '', type: 'grid', schema: [{ name: 'interval' }, { name: 'unit' }] }];
    expect(pickFormData(data, schema)).toEqual({ interval: 3, unit: 'months' });
  });

  it('contributes nothing for an entry that is neither named nor a group', () => {
    // A grid container carries no name of its own, and neither does anything else a
    // schema might grow. Such an entry has to drop out rather than seed a key.
    expect(schemaFieldNames([{ name: 'a' }, { type: 'constant' }, { name: 'b' }])).toEqual([
      'a',
      'b',
    ]);
    expect(pickFormData({ a: 1, b: 2 }, [{ type: 'constant' }, { name: 'a' }])).toEqual({ a: 1 });
  });

  it('omits a key the data does not have rather than seeding it undefined', () => {
    // A seeded `undefined` would read as "this field was cleared" when the form
    // echoed it back, which is the difference between leaving a value alone and
    // wiping it.
    expect(pickFormData({ name: 'x' }, [{ name: 'name' }, { name: 'notes' }])).toEqual({
      name: 'x',
    });
    expect('notes' in pickFormData({ name: 'x' }, [{ name: 'notes' }])).toBe(false);
  });

  it('splits the task form into sections that between them hold every value', () => {
    const task = { recurrence_type: 'floating', name: 'Flush tank', interval: 3 };
    const data = taskFormData(task);
    const sections = taskSchemaSections(task);
    const merged = Object.assign({}, ...sections.map((s) => pickFormData(data, s.fields)));
    // Every field the form offers is seeded by exactly one section.
    for (const name of names(taskSchema(task))) {
      expect(merged[name], `${name} should be seeded by one of the sections`).toEqual(data[name]);
    }
  });
});

describe('selUnit', () => {
  // One list behind two forms: a floating task's cadence and, in the panel, a wear
  // part's replacement schedule. They used to carry a copy each.
  it('offers exactly days / weeks / months, labelled in the active language', () => {
    expect(selUnit()).toEqual({
      select: {
        mode: 'dropdown',
        sort: false,
        multiple: false,
        options: [
          { value: 'days', label: 'days' },
          { value: 'weeks', label: 'weeks' },
          { value: 'months', label: 'months' },
        ],
      },
    });
  });

  it('translates the labels while the stored values stay in English', () => {
    setLanguage('de');
    const { options } = selUnit().select;
    expect(options.map((o) => o.value)).toEqual(['days', 'weeks', 'months']);
    // A German panel must still save `unit: "months"` — the label moves, the value
    // is the recurrence field the backend reads.
    for (const o of options) expect(o.label).not.toBe(o.value);
    setLanguage('en');
  });

  it('is the selector the task form actually hands to ha-form', () => {
    const unit = taskSchema({ recurrence_type: 'floating' })
      .flatMap((f) => f.schema ?? [f])
      .find((f) => f.name === 'unit');
    expect(unit.selector).toEqual(selUnit());
  });
});

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
      'area_id',
      'tag_id',
      'require_tag_scan',
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
      'area_id',
      'tag_id',
      'require_tag_scan',
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
      'area_id',
      'tag_id',
      'require_tag_scan',
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
    expect(got).toEqual([
      'name',
      'notes',
      'device_id',
      'area_id',
      'tag_id',
      'require_tag_scan',
      'labels',
    ]);
    for (const scheduling of ['interval', 'unit', 'freq', 'anchor', 'due', 'recurrence_type']) {
      expect(got).not.toContain(scheduling);
    }
  });
});

// A task carries its own `area_id` in the store, the services and the websocket
// API, and the panel groups/filters on it — but the form offered no control for
// it, so a task with no device could never be placed in a room from the UI at all
// (issue #204). These assert the whole path the picker sits on: it's offered, it
// loads, it saves, and it clears.
describe('taskSchema area field (issue #204)', () => {
  const KITCHEN = 'kitchen_area_id';

  it('offers an area picker for every task kind, not just device-backed ones', () => {
    for (const recurrence_type of ['floating', 'fixed', 'one-off', 'sensor', 'triggered']) {
      const fields = taskSchema({ recurrence_type });
      expect(names(fields)).toContain('area_id');
      // The single-select area selector — a `multiple` picker would save an array
      // the backend rejects.
      const area = fields.find((f) => f.name === 'area_id');
      expect(area.selector).toEqual({ area: {} });
    }
  });

  it('sits next to the device picker, since both are attachment fields', () => {
    const got = names(taskSchema({ recurrence_type: 'floating' }));
    expect(got.indexOf('area_id')).toBe(got.indexOf('device_id') + 1);
  });

  it('omits the picker when the managing integration locks the area', () => {
    // A synced problem-sensor task takes its area from the source sensor's device
    // (`problem_tasks._LOCKED_FIELDS`), so the form must not offer to change it.
    const unlocked = taskSchema({ recurrence_type: 'floating' });
    const fields = taskSchema({
      recurrence_type: 'floating',
      managed_by: { integration: 'x', display_name: 'X', locked_fields: ['area_id'] },
    });
    expect(names(fields)).not.toContain('area_id');
    // Locking the area alone leaves the neighbouring attachment fields reachable.
    expect(names(fields)).toContain('device_id');
    expect(names(fields)).toContain('labels');
    // Count the raw entries, not the names: a nameless entry would be dropped by
    // `names()`, so only this catches the locked branch contributing anything at all
    // to the schema instead of nothing.
    expect(fields.length).toBe(unlocked.length - 1);
  });

  it('omits the picker on a locked *triggered* task too', () => {
    // The triggered branch builds its own short field list, so it needs its own
    // locking assertion — the floating path's does not exercise it.
    const unlocked = taskSchema({ recurrence_type: 'triggered' });
    const fields = taskSchema({
      recurrence_type: 'triggered',
      managed_by: { integration: 'x', display_name: 'X', locked_fields: ['area_id'] },
    });
    expect(names(fields)).toEqual([
      'name',
      'notes',
      'device_id',
      'tag_id',
      'require_tag_scan',
      'labels',
    ]);
    expect(fields.length).toBe(unlocked.length - 1);
  });

  it('loads a task’s saved area into the form', () => {
    expect(taskFormData({ area_id: KITCHEN }).area_id).toBe(KITCHEN);
  });

  it('leaves the picker empty for a task with no area of its own', () => {
    // `undefined`, not null or '' — ha-form treats an empty registry picker as
    // unset, and a null would render as a selected "null" option.
    expect(taskFormData({}).area_id).toBeUndefined();
    expect(taskFormData({ area_id: null }).area_id).toBeUndefined();
  });

  it('saves the chosen area on every task kind', () => {
    for (const recurrence_type of ['floating', 'fixed', 'one-off', 'sensor', 'triggered']) {
      const payload = buildTaskPayload({ name: 'T', recurrence_type, area_id: KITCHEN });
      expect(payload.area_id).toBe(KITCHEN);
    }
  });

  it('sends an explicit null when the area is cleared, so the old one is dropped', () => {
    // `merge_update` only overwrites keys the payload carries — omitting a cleared
    // area would silently keep the task in its old room.
    expect(buildTaskPayload({ name: 'T', recurrence_type: 'floating' }).area_id).toBeNull();
    expect(
      buildTaskPayload({ name: 'T', recurrence_type: 'floating', area_id: '' }).area_id,
    ).toBeNull();
    expect(
      buildTaskPayload({ name: 'T', recurrence_type: 'triggered', area_id: null }).area_id,
    ).toBeNull();
  });

  it('round-trips an area through the form unchanged', () => {
    const task = { id: 't1', name: 'T', recurrence_type: 'floating', interval: 3, unit: 'months', area_id: KITCHEN };
    expect(buildTaskPayload({ ...task, ...taskFormData(task) }).area_id).toBe(KITCHEN);
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

  it('drops the unit dropdown alone when the cadence unit is locked', () => {
    // The cadence pair lives in an unnamed grid, so a lock in there has to leave the
    // grid holding exactly the other field — not an empty slot beside it.
    const grid = taskSchema(locked(['unit'])).find((f) => f.type === 'grid');
    expect(grid.schema.map((f) => f.name)).toEqual(['interval']);
    expect(names(taskSchema(locked(['unit'])))).not.toContain('unit');
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
    expect(got).toEqual(['device_id', 'area_id', 'tag_id', 'require_tag_scan', 'labels']);
  });

  it('honours a lock on every field a triggered task offers', () => {
    // A triggered task takes its own branch of the builder, so each key it can hide
    // has to be exercised there — locking `name` proves nothing about `device_id`.
    for (const field of ['name', 'notes', 'device_id', 'area_id', 'tag_id', 'labels']) {
      const got = names(
        taskSchema({
          recurrence_type: 'triggered',
          managed_by: { integration: 'x', locked_fields: [field] },
        }),
      );
      expect(got).not.toContain(field);
      // Locking one field hides one field.
      expect(got).toHaveLength(names(taskSchema({ recurrence_type: 'triggered' })).length - 1);
    }
  });

  it('never emits an entry that is neither a named field nor a group', () => {
    // `names()` drops falsy entries so a `grid` container does not read as a field,
    // which means a schema that grew a *nameless* entry would slip past every
    // assertion written in terms of names. Assert the shape itself.
    const lockSets = [
      [],
      ['name'],
      ['notes'],
      ['device_id'],
      ['area_id'],
      ['labels'],
      ['name', 'notes', 'device_id', 'area_id', 'labels'],
    ];
    for (const kind of ['floating', 'fixed', 'one-off', 'sensor', 'triggered']) {
      for (const locked_fields of lockSets) {
        const schema = taskSchema(
          { recurrence_type: kind, managed_by: { integration: 'x', locked_fields } },
          [],
          [{ value: 'a1:e1', label: 'Manual' }],
        );
        for (const field of schema) expect(field.name || field.schema).toBeTruthy();
      }
    }
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
    channel: 'Chores',
    urgency: 'high',
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
      channel: 'Chores',
      urgency: 'high',
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

  it('leaves a new notification on no channel at normal urgency', () => {
    // The pair of defaults that make an unconfigured notification send the payload it
    // sent before these fields existed. A blank channel must be '' and not undefined:
    // the backend echoes what it stores, and `undefined` drops out of the saved JSON.
    const rebuilt = notifyFormToNotification('n1', { name: 'x' });
    expect(rebuilt.channel).toBe('');
    expect(rebuilt.urgency).toBe('normal');
  });

  it('trims the channel name', () => {
    // Android creates one channel per distinct string, so "Meds " and "Meds" would
    // otherwise become two channels the user has to configure separately.
    expect(notifyFormToNotification('n1', { name: 'x', channel: '  Meds  ' }).channel).toBe('Meds');
    expect(notifyFormToNotification('n1', { name: 'x', channel: null }).channel).toBe('');
  });

  it('keeps every urgency the ladder offers', () => {
    for (const urgency of ['quiet', 'normal', 'high', 'critical']) {
      expect(notifyFormToNotification('n1', { name: 'x', urgency }).urgency).toBe(urgency);
    }
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
      'channel',
      'urgency',
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

  it('offers the urgency ladder quietest first, single-select', () => {
    // The order is the whole point: a shuffled list reads as unrelated choices rather
    // than a ladder, and a multi-select would let someone pick two at once.
    const field = notificationSchema([], []).find((f) => f.name === 'urgency');
    expect(field.selector.select.options).toEqual([
      { value: 'quiet', label: 'Quiet' },
      { value: 'normal', label: 'Normal' },
      { value: 'high', label: 'High' },
      { value: 'critical', label: 'Critical' },
    ]);
    expect(field.selector.select.multiple).toBe(false);
    expect(field.selector.select.sort).toBe(false);
  });

  it('takes any channel name as free text', () => {
    // Android creates a channel on first use, so the names worth offering are the
    // ones the household invents. A dropdown would have nothing to list.
    const field = notificationSchema([], []).find((f) => f.name === 'channel');
    expect(field.selector).toEqual({ text: {} });
    expect(field.required).toBeUndefined();
  });
});

// The Settings tab's Shopping list card. The picker's shape is the whole
// control: the wrong domain offers lists Home Keeper can't write to, and a
// missing exclusion offers Home Keeper's own list — which would be a list
// synced onto itself.
// The Settings card renders the switch and the exclusions as two forms so the
// exclusions can be indented behind the condition that makes them matter. The
// options endpoint merges partial updates, so each form saving only its own fields
// is safe — but only while the two halves still add up to the whole schema.
describe('problemSyncSchema is its two halves, in order', () => {
  it('concatenates the toggle and the exclusions', () => {
    expect(problemSyncSchema()).toEqual([
      ...problemSyncToggleSchema(),
      ...problemSyncExclusionsSchema(),
    ]);
  });

  it('puts the switch on its own and every exclusion in the dependent half', () => {
    expect(problemSyncToggleSchema().map((f) => f.name)).toEqual(['sync_problem_sensors']);
    expect(problemSyncExclusionsSchema().map((f) => f.name)).toEqual([
      'problem_sensor_exclude_entities',
      'problem_sensor_exclude_devices',
      'problem_sensor_exclude_areas',
      'problem_sensor_exclude_labels',
    ]);
  });
});

describe('shoppingSchema', () => {
  it('offers a single to-do entity picker', () => {
    expect(shoppingSchema()).toEqual([
      {
        name: 'shopping_list_entity',
        selector: { entity: { filter: { domain: 'todo' }, multiple: false } },
      },
    ]);
  });

  it("keeps Home Keeper's own to-do lists out of the picker", () => {
    const [field] = shoppingSchema(['todo.home_keeper_tasks']);
    expect(field.selector.entity.exclude_entities).toEqual(['todo.home_keeper_tasks']);
  });

  it('emits no exclusion key when there is nothing to exclude', () => {
    const [field] = shoppingSchema([]);
    expect('exclude_entities' in field.selector.entity).toBe(false);
  });
});

// A profile's "Sync to a to-do list" group. Configuring it is a standing instruction
// to write Home Keeper's tasks onto somebody else's list and to accept completions
// back, so every part of its shape is load-bearing: the wrong domain offers lists
// that can't hold tasks, a missing exclusion offers Home Keeper's own list (a loop),
// and a boolean that defaults the wrong way silently changes what ticking an item
// off does. There is no delete button in the group, so the picker's ability to go
// back to empty is the only off switch there is.
describe('profileSyncSchema', () => {
  it('describes the list and the two switches, in that order', () => {
    expect(names(profileSyncSchema())).toEqual(['entity_id', 'two_way', 'vanish_as_completed']);
  });

  it('offers no profile picker — a profile syncs to at most one list', () => {
    // The old standalone card paired a list with a profile; the group is *inside* a
    // profile, so a second reference to one would be a way to contradict the parent.
    expect(names(profileSyncSchema())).not.toContain('profile_id');
  });

  it('offers a single to-do entity picker', () => {
    const field = profileSyncSchema().find((f) => f.name === 'entity_id');
    // A `multiple` picker would save an array the backend reads as unusable, and
    // any other domain offers entities that can't hold a to-do item at all.
    expect(field.selector).toEqual({ entity: { filter: { domain: 'todo' }, multiple: false } });
  });

  it("keeps Home Keeper's own to-do lists out of the picker", () => {
    // Syncing our own list onto itself is a loop, and ours accepts no new items.
    const field = profileSyncSchema(['todo.home_keeper_tasks']).find(
      (f) => f.name === 'entity_id',
    );
    expect(field.selector.entity.exclude_entities).toEqual(['todo.home_keeper_tasks']);
  });

  it('emits no exclusion key when there is nothing to exclude', () => {
    const field = profileSyncSchema().find((f) => f.name === 'entity_id');
    expect('exclude_entities' in field.selector.entity).toBe(false);
  });

  it('renders both sync switches as booleans', () => {
    const fields = profileSyncSchema();
    expect(fields.find((f) => f.name === 'two_way').selector).toEqual({ boolean: {} });
    expect(fields.find((f) => f.name === 'vanish_as_completed').selector).toEqual({ boolean: {} });
  });
});

describe('toProfileSync', () => {
  const sync = { entity_id: 'todo.shopping', two_way: false, vanish_as_completed: false };

  it('passes a fully configured sync through unchanged', () => {
    expect(toProfileSync(sync)).toEqual(sync);
  });

  it('reads a missing sync block as off, with both switches on', () => {
    // The backend normalizer fills both in as `True`; reading a missing key as
    // `false` here would show two-way sync switched off on a profile that has it on.
    for (const absent of [undefined, null, {}]) {
      expect(toProfileSync(absent)).toEqual({
        entity_id: '',
        two_way: true,
        vanish_as_completed: true,
      });
    }
  });

  it('turns a cleared entity picker into the empty string', () => {
    // The picker emits `undefined` when cleared, and JSON drops an undefined on the
    // way to the backend — so the key would never reach the saved profile and
    // "switch the sync off" silently wouldn't stick. Clearing it is the only off
    // switch the group has, so this is the whole control.
    expect(toProfileSync({ two_way: true }).entity_id).toBe('');
    expect(toProfileSync({ entity_id: undefined }).entity_id).toBe('');
    expect(toProfileSync({ entity_id: null }).entity_id).toBe('');
    expect(toProfileSync({ entity_id: 'todo.x' }).entity_id).toBe('todo.x');
  });

  it('keeps a switch the user turned off, and coerces to a real boolean', () => {
    const off = toProfileSync({ entity_id: 'todo.x', two_way: false, vanish_as_completed: false });
    expect(off.two_way).toBe(false);
    expect(off.vanish_as_completed).toBe(false);
    const coerced = toProfileSync({
      entity_id: 'todo.x',
      two_way: 'yes',
      vanish_as_completed: 0,
    });
    expect(coerced.two_way).toBe(true);
    expect(coerced.vanish_as_completed).toBe(false);
  });

  it('defaults each switch independently of the other', () => {
    // One switch present must not decide the other: a snapshot that predates only
    // `vanish_as_completed` still has to come back with it on.
    expect(toProfileSync({ entity_id: 'todo.x', two_way: false })).toEqual({
      entity_id: 'todo.x',
      two_way: false,
      vanish_as_completed: true,
    });
    expect(toProfileSync({ entity_id: 'todo.x', vanish_as_completed: false })).toEqual({
      entity_id: 'todo.x',
      two_way: true,
      vanish_as_completed: false,
    });
  });

  it('stringifies an entity id that arrives as a non-string', () => {
    expect(toProfileSync({ entity_id: 7 }).entity_id).toBe('7');
  });
});

// ── appliance form schemas ──────────────────────────────────────────────────
// The appliance drawer's field sets. Same contract as the task form's above: a
// missing field is a control the user cannot reach, and a selector with the wrong
// `min` or `step` is a value the field silently refuses. Both are invisible to a
// test that only counts fields, so these spell the selectors out.

/** Every field, grid containers flattened away, as objects (not just names). */
const flat = (fields) => fields.flatMap((f) => (f.schema ? flat(f.schema) : [f]));
const field = (fields, name) => flat(fields).find((f) => f.name === name);
const selectorOf = (fields, name) => field(fields, name)?.selector;

const TEXT = { text: {} };
const MULTILINE = { text: { multiline: true } };
const dropdown = (options) => ({ select: { mode: 'dropdown', options, sort: false, multiple: false } });

describe('partSchema', () => {
  const consumable = { name: 'Anode rod', type: 'consumable' };

  it('offers the fixed fields, in order, whatever the part is', () => {
    expect(names(partSchema(consumable))).toEqual([
      'part_name',
      'part_number',
      'type',
      'vendor',
      'cost',
      'part_url',
      'notes',
      'stock',
      'reorder_at',
      'stock_unit',
    ]);
  });

  it('spells out the selector every fixed field carries', () => {
    const sel = (n) => selectorOf(partSchema(consumable), n);
    expect(sel('part_name')).toEqual(TEXT);
    expect(sel('part_number')).toEqual(TEXT);
    expect(sel('vendor')).toEqual(TEXT);
    expect(sel('part_url')).toEqual(TEXT);
    expect(sel('stock_unit')).toEqual(TEXT);
    // A part note is prose, so it gets the tall box.
    expect(sel('notes')).toEqual(MULTILINE);
    // Money steps in whole units; the quantities do not — a part measured in
    // millilitres is as valid as one counted in whole filters.
    expect(sel('cost')).toEqual({ number: { min: 0, mode: 'box' } });
    expect(sel('stock')).toEqual({ number: { min: 0, mode: 'box', step: 'any' } });
    expect(sel('reorder_at')).toEqual({ number: { min: 0, mode: 'box', step: 'any' } });
    expect(sel('type')).toEqual(
      dropdown([
        { value: 'consumable', label: 'consumable' },
        { value: 'wear', label: 'wear item' },
      ]),
    );
  });

  it('reveals the per-completion amount only once the part tracks stock', () => {
    // Nothing to draw from, so the field would promise nothing.
    expect(names(partSchema(consumable))).not.toContain('consume_quantity');
    expect(names(partSchema({ ...consumable, stock: null }))).not.toContain('consume_quantity');
    // "Out of stock" is still tracking stock — zero is a count, not an absence.
    expect(names(partSchema({ ...consumable, stock: 0 }))).toContain('consume_quantity');
    expect(names(partSchema({ ...consumable, stock: 2 }))).toContain('consume_quantity');
  });

  it('floors the per-completion amount just above zero', () => {
    // A number selector has no exclusive minimum, and a zero here is a field that
    // quietly does nothing — so the floor is one step of the stored precision.
    expect(selectorOf(partSchema({ ...consumable, stock: 2 }), 'consume_quantity')).toEqual({
      number: { min: 0.001, mode: 'box', step: 'any' },
    });
  });

  it('reveals auto-buy only once a reorder threshold defines "low"', () => {
    expect(names(partSchema(consumable))).not.toContain('create_buy_task');
    expect(names(partSchema({ ...consumable, reorder_at: null }))).not.toContain('create_buy_task');
    // Reordering at zero is a threshold like any other.
    expect(names(partSchema({ ...consumable, reorder_at: 0 }))).toContain('create_buy_task');
    expect(selectorOf(partSchema({ ...consumable, reorder_at: 1 }), 'create_buy_task')).toEqual({
      boolean: {},
    });
  });

  it('reveals the restock amount only once auto-buy is switched on', () => {
    const off = { ...consumable, reorder_at: 1 };
    expect(names(partSchema(off))).not.toContain('restock_quantity');
    expect(names(partSchema({ ...off, create_buy_task: false }))).not.toContain('restock_quantity');
    const on = partSchema({ ...off, create_buy_task: true });
    expect(names(on)).toContain('restock_quantity');
    expect(selectorOf(on, 'restock_quantity')).toEqual({
      number: { min: 0.001, mode: 'box', step: 'any' },
    });
    // And it stays hidden while there is no threshold to be low against.
    expect(names(partSchema({ ...consumable, create_buy_task: true }))).not.toContain(
      'restock_quantity',
    );
  });

  it('adds the replacement schedule for a wear item only', () => {
    expect(names(partSchema(consumable))).not.toContain('replace_interval');
    const wear = partSchema({ name: 'Filter', type: 'wear' });
    expect(names(wear).slice(-3)).toEqual(['replace_interval', 'replace_unit', 'last_replaced']);
    // The interval and its unit share a line, in an unnamed grid like the others.
    const wearGrid = wear.filter((f) => f.type === 'grid').at(-1);
    expect(names(wearGrid.schema)).toEqual(['replace_interval', 'replace_unit']);
    expect(wearGrid.name).toBe('');
    // Replacing "every 0 months" is not a schedule.
    expect(selectorOf(wear, 'replace_interval')).toEqual({ number: { min: 1, mode: 'box' } });
    expect(selectorOf(wear, 'replace_unit')).toEqual(
      dropdown([
        { value: 'days', label: 'days' },
        { value: 'weeks', label: 'weeks' },
        { value: 'months', label: 'months' },
      ]),
    );
    // The date the clock starts from, so a derived task doesn't start at "now".
    expect(selectorOf(wear, 'last_replaced')).toEqual({ date: {} });
  });

  it('lays the fixed fields out in three grids', () => {
    // The grids are what put name/number/type on one line; flattening hides that,
    // so the shape is asserted here rather than only the field names.
    const grids = partSchema(consumable).filter((f) => f.type === 'grid');
    expect(grids.map((g) => names(g.schema))).toEqual([
      ['part_name', 'part_number', 'type'],
      ['vendor', 'cost'],
      ['stock', 'reorder_at', 'stock_unit'],
    ]);
    // A grid is an *unnamed* container: `ha-form` emits the fields inside it, so a
    // name on the container itself would be a value nobody ever set.
    expect(grids.every((g) => g.name === '')).toBe(true);
  });
});

describe('metadataSchema', () => {
  it('always offers type, label and value — the type and label side by side', () => {
    const schema = metadataSchema({ type: 'text', label: 'Serial', value: 'abc' });
    expect(names(schema)).toEqual(['type', 'label', 'value']);
    expect(schema[0].type).toBe('grid');
    expect(schema[0].name).toBe('');
    expect(names(schema[0].schema)).toEqual(['type', 'label']);
    expect(selectorOf(schema, 'type')).toEqual(
      dropdown([
        { value: 'text', label: 'Text' },
        { value: 'link', label: 'Link' },
        { value: 'date', label: 'Date' },
      ]),
    );
    expect(selectorOf(schema, 'label')).toEqual(TEXT);
  });

  it('swaps the value control to a date picker for a date entry', () => {
    expect(selectorOf(metadataSchema({ type: 'text' }), 'value')).toEqual(TEXT);
    expect(selectorOf(metadataSchema({ type: 'link' }), 'value')).toEqual(TEXT);
    expect(selectorOf(metadataSchema({}), 'value')).toEqual(TEXT);
    expect(selectorOf(metadataSchema({ type: 'date' }), 'value')).toEqual({ date: {} });
  });

  it('offers "track as sensor" for a date entry only', () => {
    // Tracking is what turns a warranty expiry into something that can fire; the
    // other two types have no date to count down to.
    expect(names(metadataSchema({ type: 'text' }))).not.toContain('track');
    expect(names(metadataSchema({ type: 'link' }))).not.toContain('track');
    const dated = metadataSchema({ type: 'date' });
    expect(names(dated)).toEqual(['type', 'label', 'value', 'track']);
    expect(selectorOf(dated, 'track')).toEqual({ boolean: {} });
  });
});

describe('assetIdentitySchema', () => {
  const parents = [{ value: 'a1', label: 'Kitchen' }];

  it('asks what kind of appliance this is only while creating one', () => {
    // `kind` is immutable after creation and ha-form has no per-field disable, so
    // the only way editing cannot put it in an inconsistent state is not to offer it.
    const creating = assetIdentitySchema({}, false, parents);
    expect(creating[0].name).toBe('kind');
    expect(creating[0].selector).toEqual(
      dropdown([
        { value: 'virtual', label: 'New appliance (Home Keeper creates a device)' },
        { value: 'existing', label: 'Existing device (add details to it)' },
      ]),
    );
    expect(names(assetIdentitySchema({}, true, parents))).not.toContain('kind');
  });

  it('lays a virtual appliance out with a parent picker and no device', () => {
    const schema = assetIdentitySchema({ kind: 'virtual' }, true, parents);
    expect(names(schema)).toEqual([
      'name',
      'manufacturer',
      'model',
      'serial_number',
      'icon',
      'parent_asset_id',
      'area_id',
    ]);
    // A virtual appliance owns no other name source, so the name is required.
    expect(field(schema, 'name').required).toBe(true);
    expect(selectorOf(schema, 'parent_asset_id')).toEqual(dropdown(parents));
    expect(selectorOf(schema, 'icon')).toEqual({ icon: {} });
    expect(selectorOf(schema, 'area_id')).toEqual({ area: {} });
  });

  it('swaps the parent picker for a device picker on an existing device', () => {
    const schema = assetIdentitySchema({ kind: 'existing' }, true, parents);
    expect(names(schema)).toEqual([
      'device_id',
      'name',
      'manufacturer',
      'model',
      'serial_number',
      'icon',
      'area_id',
    ]);
    // The device is the whole point, so it is required — and it supplies its own
    // name, so the name is not.
    expect(field(schema, 'device_id').required).toBe(true);
    expect(field(schema, 'name').required).toBe(false);
    expect(selectorOf(schema, 'device_id')).toEqual({ device: {} });
    // A device nests natively through the registry, so no parent picker is offered.
    expect(names(schema)).not.toContain('parent_asset_id');
  });

  it('keeps make and model on one line, and serial with them', () => {
    const grids = assetIdentitySchema({ kind: 'virtual' }, true, parents).filter(
      (f) => f.type === 'grid',
    );
    expect(grids.map((g) => names(g.schema))).toEqual([
      ['manufacturer', 'model'],
      ['icon', 'parent_asset_id'],
    ]);
    expect(grids.every((g) => g.name === '')).toBe(true);
    // serial_number is first-class (it syncs into the device page), so it sits
    // outside the free-form custom fields, next to make and model.
    expect(selectorOf(assetIdentitySchema({}, true, parents), 'serial_number')).toEqual(TEXT);
  });

  it('offers whatever parent list it is handed, and nothing else', () => {
    // The panel resolves the tree (no cycles, virtual only); this only lays it out.
    expect(selectorOf(assetIdentitySchema({}, true, []), 'parent_asset_id')).toEqual(dropdown([]));
  });
});

describe('structuredDetailsSchema', () => {
  it('is the appliance value, as a whole-stepped number', () => {
    expect(structuredDetailsSchema()).toEqual([
      { name: 'cost', selector: { number: { min: 0, mode: 'box' } } },
    ]);
  });
});

describe('sensorLive', () => {
  const hass = (states) => ({ states });

  it('reads the entity being picked right now, before the task is saved', () => {
    const h = hass({ 'sensor.hours': { state: '660', attributes: { unit_of_measurement: 'h' } } });
    expect(sensorLive(h, { sensor_entity_id: 'sensor.hours' })).toEqual({ reading: 660, unit: 'h' });
  });

  it('falls back to a saved task binding when the form has no flat value', () => {
    const h = hass({ 'sensor.km': { state: '48000', attributes: { unit_of_measurement: 'km' } } });
    expect(sensorLive(h, { sensor: { entity_id: 'sensor.km' } })).toEqual({
      reading: 48000,
      unit: 'km',
    });
    // The flat edit state wins while both are present — it is what is on screen.
    expect(
      sensorLive(hass({ 'sensor.a': { state: '1' }, 'sensor.b': { state: '2' } }), {
        sensor_entity_id: 'sensor.a',
        sensor: { entity_id: 'sensor.b' },
      }),
    ).toEqual({ reading: 1, unit: undefined });
  });

  it('reads an attribute when one is named, not the state', () => {
    const h = hass({
      'sensor.car': { state: '12', attributes: { odometer: 48000, unit_of_measurement: 'km' } },
    });
    expect(sensorLive(h, { sensor_entity_id: 'sensor.car', sensor_attribute: 'odometer' })).toEqual({
      reading: 48000,
      unit: 'km',
    });
    // A saved task's attribute counts the same way.
    expect(
      sensorLive(h, { sensor: { entity_id: 'sensor.car', attribute: 'odometer' } }),
    ).toEqual({ reading: 48000, unit: 'km' });
  });

  it('says nothing at all when there is no entity to read', () => {
    expect(sensorLive(hass({}), {})).toEqual({});
    expect(sensorLive(hass({}), { sensor_entity_id: '' })).toEqual({});
    // Named but unknown to Home Assistant — an entity that has not loaded yet.
    expect(sensorLive(hass({}), { sensor_entity_id: 'sensor.gone' })).toEqual({});
    expect(sensorLive(undefined, { sensor_entity_id: 'sensor.hours' })).toEqual({});
    // A hass that has not loaded its states yet is not a crash.
    expect(sensorLive({}, { sensor_entity_id: 'sensor.hours' })).toEqual({});
  });

  it('drops a reading it cannot make a number of, but keeps the unit', () => {
    const h = hass({
      'sensor.hours': { state: 'unavailable', attributes: { unit_of_measurement: 'h' } },
    });
    expect(sensorLive(h, { sensor_entity_id: 'sensor.hours' })).toEqual({
      reading: undefined,
      unit: 'h',
    });
    // An empty state is not zero.
    expect(sensorLive(hass({ 'sensor.x': { state: '' } }), { sensor_entity_id: 'sensor.x' })).toEqual(
      { reading: undefined, unit: undefined },
    );
    expect(
      sensorLive(hass({ 'sensor.x': { state: null } }), { sensor_entity_id: 'sensor.x' }),
    ).toEqual({ reading: undefined, unit: undefined });
    // Zero is a real reading.
    expect(sensorLive(hass({ 'sensor.x': { state: '0' } }), { sensor_entity_id: 'sensor.x' })).toEqual(
      { reading: 0, unit: undefined },
    );
  });
});

// A duplicate is the original's payload minus exactly three things — the record of
// what happened, the meter's anchor, and the tag binding. Every assertion below is a
// whole-object comparison rather than a key spot-check, because the interesting
// failure is "which field did the seed forget", and a spot-check only catches the
// fields somebody thought to name.
describe('duplicateTaskSeed — a copy of the rule, not of the record (#279)', () => {
  beforeEach(() => setLanguage('en'));

  const floating = {
    id: 't1',
    name: 'Water flowers',
    notes: 'Deep soak, not a sprinkle.',
    recurrence_type: 'floating',
    interval: 3,
    unit: 'days',
    device_id: 'dev1',
    area_id: 'area1',
    labels: ['lbl1', 'lbl2'],
    card_links: [{ asset_id: 'a1', entry_id: 'e1' }],
    completion_detail: 'required',
    enabled: true,
    created: '2026-01-01T00:00:00+00:00',
    last_completed: '2026-08-01T10:00:00+00:00',
    next_due: '2026-08-04T10:00:00+00:00',
    completions: [{ date: '2026-08-01T10:00:00+00:00' }],
    tag_id: 'tag-abc',
    require_tag_scan: true,
    task_chips: [{ label: 'Pawsistant' }],
  };

  const usageSensor = {
    id: 't2',
    name: 'Replace printer nozzle',
    recurrence_type: 'sensor',
    device_id: 'dev2',
    completion_detail: 'none',
    last_completed: '2026-06-01T00:00:00+00:00',
    sensor: {
      entity_id: 'sensor.printer_hours',
      mode: 'usage',
      target: 300,
      unit: 'h',
      baseline: 660,
      also_every: { interval: 6, unit: 'months' },
      combinator: 'any',
    },
  };

  it('drops the id, which is the whole mechanism', () => {
    // `_submitForm` routes an id-less task to `addTask`. Keep the id and Duplicate
    // silently becomes Save-over-the-original.
    expect(duplicateTaskSeed(floating).id).toBeUndefined();
  });

  it('names the copy after the original', () => {
    expect(duplicateTaskSeed(floating).name).toBe('Water flowers (copy)');
  });

  it('never carries the original last-completed date into the new task', () => {
    // The trap: `buildTaskPayload` emits `last_completed` *only* when `!task.id`,
    // which is never true on the edit path and always true here. Carried over, every
    // copy is born back-dated and the recurrence engine derives next_due from it.
    const seed = duplicateTaskSeed(floating);
    expect(seed.last_completed).toBeUndefined();
    expect(buildTaskPayload(seed)).not.toHaveProperty('last_completed');
    // And the field the form now reveals (it only renders for an id-less task)
    // starts blank rather than pre-filled with the original's date.
    expect(taskFormData(seed).last_completed).toBe('');
  });

  it('keeps the whole sensor binding except the meter baseline', () => {
    // The second trap. Inherit `baseline: 660` and the copy is instantly ~80% used
    // against a machine it has never metered; leaving it unset is what makes the
    // backend stamp the copy's own live reading.
    const seed = duplicateTaskSeed(usageSensor);
    expect(seed.sensor).toEqual({
      entity_id: 'sensor.printer_hours',
      mode: 'usage',
      target: 300,
      unit: 'h',
      also_every: { interval: 6, unit: 'months' },
      combinator: 'any',
    });
    expect(buildTaskPayload(seed).sensor).not.toHaveProperty('baseline');
    expect(taskFormData(seed).sensor_baseline).toBeUndefined();
  });

  it('omits the sensor key entirely for a task that has no binding', () => {
    // Not `sensor: undefined`. The seed is an allowlist, and a key that exists
    // holding nothing is how a "cleared this field" reading gets in later.
    expect('sensor' in duplicateTaskSeed(floating)).toBe(false);
    expect('sensor' in duplicateTaskSeed(usageSensor)).toBe(true);
  });

  it('does not reach through and strip the source task it copied', () => {
    // The binding is shallow-copied. Sharing the reference and deleting the key
    // would clear the baseline of the task still sitting in the panel's list.
    duplicateTaskSeed(usageSensor);
    expect(usageSensor.sensor.baseline).toBe(660);
  });

  it('leaves the tag behind — one sticker completes one task', () => {
    const payload = buildTaskPayload(duplicateTaskSeed(floating));
    expect(payload.tag_id).toBeNull();
    expect(payload.require_tag_scan).toBe(false);
  });

  it('drops identity, history and ownership', () => {
    const seed = duplicateTaskSeed({
      ...floating,
      source: { part: { asset_id: 'a1', part_id: 'p1', manual: true } },
      managed_by: { display_name: 'Pawsistant', config_entry_id: 'ce1' },
    });
    for (const key of [
      'id',
      'created',
      'completions',
      'next_due',
      'last_completed',
      'source',
      'managed_by',
      'task_chips',
      'tag_id',
      'require_tag_scan',
      'enabled',
    ]) {
      expect(seed, `a copy must not carry ${key}`).not.toHaveProperty(key);
    }
  });

  it('carries the consumable link as the flat token, not as a source', () => {
    // `taskFormData` renders the picker from `source`, but `_submitForm` reads only
    // the flat key. Seeding `source` would show a link the save never applies.
    const linked = {
      ...floating,
      source: { part: { asset_id: 'a1', part_id: 'p1', manual: true } },
    };
    expect(duplicateTaskSeed(linked).consumable_link).toBe('a1:p1');
    expect(duplicateTaskSeed(floating).consumable_link).toBe('');
  });

  it('copies the label and card-link collections rather than sharing them', () => {
    const seed = duplicateTaskSeed(floating);
    expect(seed.labels).toEqual(['lbl1', 'lbl2']);
    expect(seed.card_links).toEqual(['a1:e1']);
    seed.labels.push('lbl3');
    expect(floating.labels).toEqual(['lbl1', 'lbl2']);
  });

  it.each([
    ['floating', floating],
    [
      'fixed',
      {
        id: 't3',
        name: 'Bins out',
        recurrence_type: 'fixed',
        interval: 1,
        freq: 'WEEKLY',
        anchor: '2026-03-02T18:00:00+00:00',
        last_completed: '2026-08-24T18:00:00+00:00',
      },
    ],
    [
      'one-off',
      {
        id: 't4',
        name: 'Register the warranty',
        recurrence_type: 'one-off',
        interval: 1,
        due: '2026-09-30T09:00:00+00:00',
        last_completed: '2026-09-30T09:05:00+00:00',
      },
    ],
    ['sensor', usageSensor],
  ])('a %s copy is the original payload minus exactly the dropped fields', (_kind, task) => {
    // The strongest assertion in the file: it says what a duplicate *is*, rather
    // than listing the keys somebody remembered to check.
    const sensor = task.sensor ? { ...task.sensor } : undefined;
    if (sensor) delete sensor.baseline;
    const expected = buildTaskPayload({
      ...task,
      id: undefined,
      name: `${task.name} (copy)`,
      last_completed: undefined,
      tag_id: null,
      require_tag_scan: false,
      ...(sensor ? { sensor } : {}),
    });
    expect(buildTaskPayload(duplicateTaskSeed(task))).toEqual(expected);
  });

  it("keeps a one-off's due date — a deadline is the rule, not the record", () => {
    const oneOff = {
      id: 't4',
      name: 'Register the warranty',
      recurrence_type: 'one-off',
      interval: 1,
      due: '2026-09-30T09:00:00+00:00',
    };
    // Without this, `taskFormData` would default an id-less task to *now* and
    // quietly move the deadline the user was duplicating.
    expect(buildTaskPayload(duplicateTaskSeed(oneOff)).due).toBe('2026-09-30T09:00:00.000Z');
  });

  it('defaults the capture mode rather than emitting undefined', () => {
    const bare = { id: 't5', name: 'Dust', recurrence_type: 'floating', interval: 1, unit: 'months' };
    expect(duplicateTaskSeed(bare).completion_detail).toBe('none');
    expect(duplicateTaskSeed(bare).notes).toBe('');
    expect(duplicateTaskSeed(bare).device_id).toBeNull();
    expect(duplicateTaskSeed(bare).area_id).toBeNull();
    expect(duplicateTaskSeed(bare).labels).toEqual([]);
    expect(duplicateTaskSeed(bare).card_links).toEqual([]);
  });
});
