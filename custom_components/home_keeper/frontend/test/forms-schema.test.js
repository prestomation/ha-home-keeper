import { beforeEach, describe, expect, it } from 'vitest';
import {
  buildTaskPayload,
  formRecurrenceSummary,
  notifyFormData,
  notifyFormToNotification,
  notificationSchema,
  problemSyncExclusionsSchema,
  problemSyncSchema,
  problemSyncToggleSchema,
  shoppingSchema,
  taskFormData,
  taskSchema,
  taskSchemaSections,
  pickFormData,
  schemaFieldNames,
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

// The Settings tab's Shopping list card. The picker's shape is the whole
// control: the wrong domain offers lists Home Keeper can't write to, and a
// missing exclusion offers Home Keeper's own list — which would be a list
// mirrored onto itself.
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
