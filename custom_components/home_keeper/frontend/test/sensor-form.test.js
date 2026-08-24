import { describe, expect, it } from 'vitest';
import {
  backstopEnabled,
  buildTaskPayload,
  formRecurrenceSummary,
  sensorHintText,
  taskFormData,
  taskSchema,
} from '../src/forms.ts';
import { recurrenceSummary } from '../src/utils.ts';

describe('task form — sensor-based tasks', () => {
  it('offers sensor as a recurrence type', () => {
    const rec = taskSchema({ recurrence_type: 'floating' }).find(
      (f) => f.name === 'recurrence_type',
    );
    const values = rec.selector.select.options.map((o) => o.value);
    expect(values).toContain('sensor');
  });

  it('shows usage fields (entity, mode, target) and hides cadence', () => {
    const names = taskSchema({ recurrence_type: 'sensor' }).map((f) => f.name);
    expect(names).toContain('sensor_entity_id');
    expect(names).toContain('sensor_mode');
    expect(names).toContain('sensor_target');
    // No clock cadence grid for a sensor task.
    expect(names).not.toContain('interval');
    expect(names).not.toContain('anchor');
  });

  it('shows threshold fields when the live mode is threshold', () => {
    const names = taskSchema({
      recurrence_type: 'sensor',
      sensor_mode: 'threshold',
    }).map((f) => f.name);
    expect(names).toContain('sensor_comparison');
    expect(names).toContain('sensor_value');
    expect(names).toContain('sensor_for');
    expect(names).not.toContain('sensor_target');
  });

  it('flattens an existing usage binding into form fields', () => {
    const data = taskFormData({
      recurrence_type: 'sensor',
      sensor: { entity_id: 'sensor.odo', mode: 'usage', target: 15000, baseline: 100 },
    });
    expect(data.sensor_entity_id).toBe('sensor.odo');
    expect(data.sensor_mode).toBe('usage');
    expect(data.sensor_target).toBe(15000);
  });

  it('reflects the live flat sensor_mode (not just a loaded binding)', () => {
    // Regression: while editing, the form state holds flat sensor_* fields; the mode
    // dropdown must show the live value so the matching fields render.
    const data = taskFormData({ recurrence_type: 'sensor', sensor_mode: 'threshold' });
    expect(data.sensor_mode).toBe('threshold');
  });

  it('assembles a usage payload from flat fields', () => {
    const payload = buildTaskPayload({
      name: 'Oil change',
      recurrence_type: 'sensor',
      sensor_entity_id: 'sensor.odo',
      sensor_mode: 'usage',
      sensor_target: '15000',
    });
    expect(payload.recurrence_type).toBe('sensor');
    expect(payload.sensor).toEqual({
      entity_id: 'sensor.odo',
      mode: 'usage',
      target: 15000,
    });
    // No clock cadence leaks into a sensor payload.
    expect(payload.interval).toBeUndefined();
  });

  it('assembles a threshold payload with an optional hold', () => {
    const payload = buildTaskPayload({
      name: 'Filter',
      recurrence_type: 'sensor',
      sensor_entity_id: 'sensor.airflow',
      sensor_mode: 'threshold',
      sensor_comparison: '<',
      sensor_value: '60',
      sensor_for: '120',
      sensor_attribute: '',
    });
    expect(payload.sensor).toEqual({
      entity_id: 'sensor.airflow',
      mode: 'threshold',
      comparison: '<',
      value: 60,
      for_seconds: 120,
    });
  });

  it('omits a zero hold and a blank attribute from a threshold payload', () => {
    const payload = buildTaskPayload({
      name: 'Filter',
      recurrence_type: 'sensor',
      sensor_entity_id: 'sensor.airflow',
      sensor_mode: 'threshold',
      sensor_comparison: '>=',
      sensor_value: '90',
      sensor_for: '0',
    });
    expect(payload.sensor.for_seconds).toBeUndefined();
    expect(payload.sensor.attribute).toBeUndefined();
  });

  it('summarises sensor tasks for the list/detail views', () => {
    expect(
      recurrenceSummary({
        recurrence_type: 'sensor',
        sensor: { entity_id: 'sensor.odo', mode: 'usage', target: 15000 },
      }),
    ).toContain('15000');
    const thr = recurrenceSummary({
      recurrence_type: 'sensor',
      sensor: { entity_id: 'sensor.h', mode: 'threshold', comparison: '>', value: 90 },
    });
    expect(thr).toContain('>');
    expect(thr).toContain('90');
  });
});

describe('sensorHintText — live "when is it due" primer', () => {
  it('spells out the next due point from the current reading (baseline anchor)', () => {
    const hint = sensorHintText(
      { recurrence_type: 'sensor', sensor_mode: 'usage', sensor_target: 100 },
      { reading: 660, unit: 'h' },
    );
    // reads 660 -> due at 660 + 100 = 760, then every 100.
    expect(hint).toContain('660 h');
    expect(hint).toContain('760 h');
    expect(hint).toContain('100 h');
  });

  it('handles a missing unit gracefully', () => {
    const hint = sensorHintText(
      { recurrence_type: 'sensor', sensor_mode: 'usage', sensor_target: 100 },
      { reading: 660 },
    );
    expect(hint).toContain('660');
    expect(hint).toContain('760');
    expect(hint).not.toContain('undefined');
  });

  it('falls back to a static explanation when the reading is unavailable', () => {
    const hint = sensorHintText(
      { recurrence_type: 'sensor', sensor_mode: 'usage', sensor_target: 100 },
      {},
    );
    expect(hint).toContain('100');
    expect(hint).not.toContain('undefined');
    // No concrete "reads N now" claim without a live value.
    expect(hint).not.toMatch(/reads\s+\d/);
  });

  it('reads a loaded binding when no flat edit state is present', () => {
    const hint = sensorHintText(
      { recurrence_type: 'sensor', sensor: { mode: 'usage', target: 500, entity_id: 'sensor.x' } },
      { reading: 20, unit: 'h' },
    );
    expect(hint).toContain('520 h');
  });

  it('describes the threshold comparison in plain symbols', () => {
    const hint = sensorHintText(
      {
        recurrence_type: 'sensor',
        sensor_mode: 'threshold',
        sensor_comparison: '>=',
        sensor_value: 90,
      },
      { unit: '%' },
    );
    expect(hint).toContain('≥');
    expect(hint).toContain('90 %');
  });

  it('mentions the hold time when a threshold sets one', () => {
    const hint = sensorHintText({
      recurrence_type: 'sensor',
      sensor_mode: 'threshold',
      sensor_comparison: '<',
      sensor_value: 10,
      sensor_for: 300,
    });
    expect(hint).toContain('300');
  });

  it('returns empty until enough is entered to be useful', () => {
    expect(sensorHintText({ recurrence_type: 'sensor', sensor_mode: 'usage' }, { reading: 5 })).toBe(
      '',
    );
    expect(
      sensorHintText({ recurrence_type: 'sensor', sensor_mode: 'threshold' }, {}),
    ).toBe('');
  });
});

describe('usage tasks with a time backstop', () => {
  const backstopTask = {
    recurrence_type: 'sensor',
    sensor_mode: 'usage',
    sensor_entity_id: 'sensor.printer_hours',
    sensor_target: 300,
    sensor_unit: 'h',
    sensor_backstop_on: true,
    sensor_also_every: 6,
    sensor_also_unit: 'months',
    sensor_combinator: 'any',
  };

  it('offers the unit label and backstop fields in usage mode only', () => {
    const usage = taskSchema({ recurrence_type: 'sensor' }).map((f) => f.name);
    expect(usage).toContain('sensor_unit');
    // The switch is always offered; its three fields only once it's on.
    expect(usage).toContain('sensor_backstop_on');
    expect(usage).not.toContain('sensor_also_every');
    const withBackstop = taskSchema(backstopTask).map((f) => f.name);
    expect(withBackstop).toContain('sensor_also_every');
    expect(withBackstop).toContain('sensor_also_unit');
    expect(withBackstop).toContain('sensor_combinator');
    const threshold = taskSchema({
      recurrence_type: 'sensor',
      sensor_mode: 'threshold',
    }).map((f) => f.name);
    expect(threshold).not.toContain('sensor_backstop_on');
    expect(threshold).not.toContain('sensor_also_every');
    expect(threshold).not.toContain('sensor_unit');
  });

  it('assembles the backstop into the payload', () => {
    const { sensor } = buildTaskPayload(backstopTask);
    expect(sensor).toEqual({
      entity_id: 'sensor.printer_hours',
      mode: 'usage',
      target: 300,
      unit: 'h',
      also_every: { interval: 6, unit: 'months' },
      combinator: 'any',
    });
  });

  it('treats a zero interval as "no backstop"', () => {
    const { sensor } = buildTaskPayload({ ...backstopTask, sensor_also_every: 0 });
    expect(sensor.also_every).toBeUndefined();
    expect(sensor.combinator).toBeUndefined();
  });

  it('drops the backstop when its switch is off, whatever the interval says', () => {
    // The stale interval survives in the edit state after the switch is flipped off
    // (the field is only hidden, not cleared), so the switch has to be authoritative
    // or turning it off would save a backstop anyway.
    const { sensor } = buildTaskPayload({ ...backstopTask, sensor_backstop_on: false });
    expect(sensor.also_every).toBeUndefined();
    expect(sensor.combinator).toBeUndefined();
    expect(sensor.target).toBe(300);
  });

  it('infers the switch from a loaded task that already has a backstop', () => {
    const loaded = {
      recurrence_type: 'sensor',
      sensor: {
        entity_id: 'sensor.printer_hours',
        mode: 'usage',
        target: 300,
        also_every: { interval: 6, unit: 'months' },
        combinator: 'any',
      },
    };
    expect(backstopEnabled(loaded)).toBe(true);
    expect(taskFormData(loaded).sensor_backstop_on).toBe(true);
    expect(taskSchema(loaded).map((f) => f.name)).toContain('sensor_also_every');
    // ...and a pure meter opens with the switch off and the fields hidden.
    const meter = { recurrence_type: 'sensor', sensor: { entity_id: 'x', mode: 'usage', target: 300 } };
    expect(backstopEnabled(meter)).toBe(false);
    expect(taskFormData(meter).sensor_backstop_on).toBe(false);
    expect(taskSchema(meter).map((f) => f.name)).not.toContain('sensor_also_every');
  });

  // The migration risk in one test: a task stored before the switch existed must open
  // and re-save byte-identically if nobody touches it. Load -> form -> payload is the
  // exact path an "open the edit form, change the name, save" edit takes, and it is
  // where a wrong default silently rewrites someone's schedule.
  it.each([
    [
      'a task with a backstop',
      {
        entity_id: 'sensor.printer_hours',
        mode: 'usage',
        target: 300,
        unit: 'h',
        also_every: { interval: 6, unit: 'months' },
        combinator: 'all',
      },
    ],
    [
      'a pure meter with no backstop',
      { entity_id: 'sensor.printer_hours', mode: 'usage', target: 300, unit: 'h' },
    ],
  ])('round-trips %s through the form untouched', (_label, sensor) => {
    const stored = { id: 't1', name: 'Service', recurrence_type: 'sensor', sensor };
    // taskFormData is what the form is seeded with; buildTaskPayload is what Save sends.
    const reopened = { ...stored, ...taskFormData(stored) };
    expect(buildTaskPayload(reopened).sensor).toEqual(sensor);
  });

  it('stops saving the backstop once the switch is turned off', () => {
    // Turning the switch off only hides the interval, so the stale value is still in
    // the edit state. Reading it instead of the switch would re-save the backstop the
    // user just removed — the whole reason the switch is authoritative.
    const stored = {
      id: 't1',
      recurrence_type: 'sensor',
      sensor: {
        entity_id: 'sensor.printer_hours',
        mode: 'usage',
        target: 300,
        also_every: { interval: 6, unit: 'months' },
        combinator: 'any',
      },
    };
    const edited = { ...stored, ...taskFormData(stored), sensor_backstop_on: false };
    expect(edited.sensor_also_every).toBe(6); // the stale interval really is still there
    const { sensor } = buildTaskPayload(edited);
    expect(sensor.also_every).toBeUndefined();
    expect(sensor.combinator).toBeUndefined();
    expect(sensor.target).toBe(300);
  });

  it('seeds a usable interval rather than zero for a fresh form', () => {
    // Switching the backstop on must not reveal three fields that describe nothing.
    expect(taskFormData({ recurrence_type: 'sensor' }).sensor_also_every).toBeGreaterThan(0);
  });

  it('flattens a loaded backstop binding back into form fields', () => {
    const data = taskFormData({
      recurrence_type: 'sensor',
      sensor: {
        entity_id: 'sensor.printer_hours',
        mode: 'usage',
        target: 300,
        unit: 'h',
        also_every: { interval: 6, unit: 'months' },
        combinator: 'all',
      },
    });
    expect(data.sensor_unit).toBe('h');
    expect(data.sensor_also_every).toBe(6);
    expect(data.sensor_also_unit).toBe('months');
    expect(data.sensor_combinator).toBe('all');
  });

  it('summarises "every N units of use, or every M months"', () => {
    const summary = recurrenceSummary({
      recurrence_type: 'sensor',
      sensor: {
        entity_id: 'sensor.printer_hours',
        mode: 'usage',
        target: 300,
        unit: 'h',
        also_every: { interval: 6, unit: 'months' },
        combinator: 'any',
      },
    });
    expect(summary).toContain('300 h');
    expect(summary).toContain('6 months');
    expect(summary).toContain('or');
  });

  it('summarises the "both must be met" variant differently', () => {
    const summary = recurrenceSummary({
      recurrence_type: 'sensor',
      sensor: {
        entity_id: 'sensor.engine_hours',
        mode: 'usage',
        target: 100,
        also_every: { interval: 1, unit: 'months' },
        combinator: 'all',
      },
    });
    expect(summary).toContain('and every 1 months');
  });

  it('extends the live hint with the backstop clause', () => {
    const hint = sensorHintText(backstopTask, { reading: 660, unit: 'h' });
    expect(hint).toContain('960');
    expect(hint).toContain('6 months');
    expect(hint).toContain('whichever comes first');
  });

  it('leaves the hint alone when there is no backstop', () => {
    const hint = sensorHintText(
      { ...backstopTask, sensor_also_every: 0 },
      { reading: 660, unit: 'h' },
    );
    expect(hint).not.toContain('whichever comes first');
  });
});

describe('formRecurrenceSummary — the rule shown above the submit button', () => {
  it('reads the same as the saved task will, for a metered rule with a backstop', () => {
    const form = {
      recurrence_type: 'sensor',
      sensor_mode: 'usage',
      sensor_entity_id: 'sensor.printer_hours',
      sensor_target: 100,
      sensor_unit: 'h',
      sensor_backstop_on: true,
      sensor_also_every: 1,
      sensor_also_unit: 'months',
      sensor_combinator: 'any',
    };
    // The whole point of building the preview from buildTaskPayload: what the form
    // promises and what the card later says are the same sentence, not two
    // formatters that agree today and drift tomorrow.
    expect(formRecurrenceSummary(form)).toBe(recurrenceSummary(buildTaskPayload(form)));
    expect(formRecurrenceSummary(form)).toBe('Every 100 h of use, or every 1 months');
  });

  it('says "and" for the both-must-be-met combinator', () => {
    const summary = formRecurrenceSummary({
      recurrence_type: 'sensor',
      sensor_mode: 'usage',
      sensor_entity_id: 'sensor.generator_hours',
      sensor_target: 200,
      sensor_unit: 'h',
      sensor_backstop_on: true,
      sensor_also_every: 6,
      sensor_also_unit: 'months',
      sensor_combinator: 'all',
    });
    expect(summary).toBe('Every 200 h of use, and every 6 months');
  });

  it('drops the backstop clause when the interval is blank or zero', () => {
    const summary = formRecurrenceSummary({
      recurrence_type: 'sensor',
      sensor_mode: 'usage',
      sensor_entity_id: 'sensor.printer_hours',
      sensor_target: 100,
      sensor_unit: 'h',
      sensor_backstop_on: true,
      sensor_also_every: 0,
    });
    expect(summary).toBe('Every 100 h of use');
  });

  it('covers the clock-based kinds too, not just sensor tasks', () => {
    expect(formRecurrenceSummary({ recurrence_type: 'floating', interval: 3, unit: 'months' })).toBe(
      'every 3 months after completion',
    );
    expect(formRecurrenceSummary({ recurrence_type: 'fixed', interval: 2, freq: 'WEEKLY' })).toBe(
      'every 2 weeks',
    );
    // A triggered task is the trap here: buildTaskPayload drops recurrence_type for
    // that kind, so a naive preview reads "every day" instead of "Monitored".
    expect(formRecurrenceSummary({ recurrence_type: 'triggered' })).toBe('Monitored');
  });

  it('says nothing until a recurrence type is chosen', () => {
    expect(formRecurrenceSummary({})).toBe('');
    expect(formRecurrenceSummary({ name: 'Half-typed' })).toBe('');
  });

  it('stays quiet rather than throwing on half-entered input', () => {
    // A user mid-type has blank numbers everywhere; the strip hides, it never errors.
    expect(() =>
      formRecurrenceSummary({
        recurrence_type: 'sensor',
        sensor_mode: 'usage',
        sensor_target: '',
        sensor_also_every: '',
      }),
    ).not.toThrow();
  });
});

describe('state mode — binary sensors', () => {
  it('offers state alongside usage and threshold', () => {
    const mode = taskSchema({ recurrence_type: 'sensor' }).find((f) => f.name === 'sensor_mode');
    expect(mode.selector.select.options.map((o) => o.value)).toEqual([
      'usage',
      'threshold',
      'state',
    ]);
  });

  it('shows the state fields and hides both other modes', () => {
    const names = taskSchema({ recurrence_type: 'sensor', sensor_mode: 'state' }).map(
      (f) => f.name,
    );
    expect(names).toContain('sensor_state');
    expect(names).toContain('sensor_for');
    expect(names).toContain('sensor_clear_on_recover');
    // Neither the meter's target nor the threshold's comparison belongs here.
    expect(names).not.toContain('sensor_target');
    expect(names).not.toContain('sensor_comparison');
    expect(names).not.toContain('sensor_value');
  });

  it('offers on/off as a picker for a binary sensor', () => {
    const field = taskSchema({
      recurrence_type: 'sensor',
      sensor_mode: 'state',
      sensor_entity_id: 'binary_sensor.rosie_water_tank_low',
    }).find((f) => f.name === 'sensor_state');
    expect(field.selector.select.options.map((o) => o.value)).toEqual(['on', 'off']);
  });

  it('falls back to free text for a non-binary entity', () => {
    // `vacuum.x === 'docked'` has to stay reachable, so the picker can't be forced.
    const field = taskSchema({
      recurrence_type: 'sensor',
      sensor_mode: 'state',
      sensor_entity_id: 'vacuum.rosie',
    }).find((f) => f.name === 'sensor_state');
    expect(field.selector.text).toBeDefined();
    expect(field.selector.select).toBeUndefined();
  });

  it('falls back to free text when reading an attribute of a binary sensor', () => {
    // The attribute's value is what gets compared, and that is arbitrary even on a
    // binary sensor — so on/off would be the wrong pair to offer.
    const field = taskSchema({
      recurrence_type: 'sensor',
      sensor_mode: 'state',
      sensor_entity_id: 'binary_sensor.rosie_water_tank_low',
      sensor_attribute: 'level',
    }).find((f) => f.name === 'sensor_state');
    expect(field.selector.text).toBeDefined();
  });

  it('treats a whitespace-only attribute as no attribute at all', () => {
    // Otherwise a stray space in the field would silently demote the on/off picker
    // to free text, for a binding that still reads the entity's own state.
    const field = taskSchema({
      recurrence_type: 'sensor',
      sensor_mode: 'state',
      sensor_entity_id: 'binary_sensor.rosie_water_tank_low',
      sensor_attribute: '   ',
    }).find((f) => f.name === 'sensor_state');
    expect(field.selector.select).toBeDefined();
  });

  it('picks the control from a loaded binding, not just live edit state', () => {
    const field = taskSchema({
      recurrence_type: 'sensor',
      sensor: { entity_id: 'binary_sensor.x', mode: 'state', state: 'on' },
    }).find((f) => f.name === 'sensor_state');
    expect(field.selector.select.options.map((o) => o.value)).toEqual(['on', 'off']);
  });

  it('assembles a state payload', () => {
    const payload = buildTaskPayload({
      name: 'Fill the water tank',
      recurrence_type: 'sensor',
      sensor_entity_id: 'binary_sensor.rosie_water_tank_low',
      sensor_mode: 'state',
      sensor_state: 'on',
      sensor_for: '60',
    });
    expect(payload.sensor).toEqual({
      entity_id: 'binary_sensor.rosie_water_tank_low',
      mode: 'state',
      state: 'on',
      for_seconds: 60,
    });
  });

  it('never sends the other modes’ fields, even if they linger in edit state', () => {
    // Switching usage -> state leaves `sensor_target` in the live form state; sending
    // it would be rejected by the backend as a usage-only field.
    const payload = buildTaskPayload({
      name: 'T',
      recurrence_type: 'sensor',
      sensor_entity_id: 'binary_sensor.x',
      sensor_mode: 'state',
      sensor_state: 'on',
      sensor_target: '300',
      sensor_unit: 'h',
      sensor_comparison: '>=',
      sensor_value: '90',
    });
    expect(payload.sensor).toEqual({
      entity_id: 'binary_sensor.x',
      mode: 'state',
      state: 'on',
    });
  });

  it('trims the state and omits a zero hold', () => {
    const payload = buildTaskPayload({
      name: 'T',
      recurrence_type: 'sensor',
      sensor_entity_id: 'vacuum.rosie',
      sensor_mode: 'state',
      sensor_state: '  docked  ',
      sensor_for: '0',
    });
    expect(payload.sensor.state).toBe('docked');
    expect(payload.sensor.for_seconds).toBeUndefined();
  });

  it('carries clear_on_recover only when switched on', () => {
    const base = {
      name: 'T',
      recurrence_type: 'sensor',
      sensor_entity_id: 'binary_sensor.x',
      sensor_mode: 'state',
      sensor_state: 'on',
    };
    expect(buildTaskPayload(base).sensor.clear_on_recover).toBeUndefined();
    expect(buildTaskPayload({ ...base, sensor_clear_on_recover: false }).sensor.clear_on_recover)
      .toBeUndefined();
    expect(buildTaskPayload({ ...base, sensor_clear_on_recover: true }).sensor.clear_on_recover)
      .toBe(true);
  });

  it('offers clear_on_recover on threshold tasks too', () => {
    const names = taskSchema({ recurrence_type: 'sensor', sensor_mode: 'threshold' }).map(
      (f) => f.name,
    );
    expect(names).toContain('sensor_clear_on_recover');
    const payload = buildTaskPayload({
      name: 'T',
      recurrence_type: 'sensor',
      sensor_entity_id: 'sensor.airflow',
      sensor_mode: 'threshold',
      sensor_comparison: '<',
      sensor_value: '60',
      sensor_clear_on_recover: true,
    });
    expect(payload.sensor.clear_on_recover).toBe(true);
  });

  it('flattens a loaded state binding back into form fields', () => {
    const data = taskFormData({
      recurrence_type: 'sensor',
      sensor: {
        entity_id: 'binary_sensor.x',
        mode: 'state',
        state: 'off',
        for_seconds: 30,
        clear_on_recover: true,
      },
    });
    expect(data.sensor_mode).toBe('state');
    expect(data.sensor_state).toBe('off');
    expect(data.sensor_for).toBe(30);
    expect(data.sensor_clear_on_recover).toBe(true);
  });

  it('seeds a fresh form with "on", the state that means "something needs doing"', () => {
    expect(taskFormData({ recurrence_type: 'sensor' }).sensor_state).toBe('on');
    // ...and with self-clearing OFF: a task you have to go and do must wait for you
    // unless you ask otherwise.
    expect(taskFormData({ recurrence_type: 'sensor' }).sensor_clear_on_recover).toBe(false);
  });

  it('summarises a state task by the state it waits for', () => {
    expect(
      recurrenceSummary({
        recurrence_type: 'sensor',
        sensor: { entity_id: 'binary_sensor.x', mode: 'state', state: 'on' },
      }),
    ).toContain('on');
  });

  it('describes the rule in the live hint', () => {
    const hint = sensorHintText({
      recurrence_type: 'sensor',
      sensor_mode: 'state',
      sensor_state: 'on',
    });
    expect(hint).toContain('on');
    expect(hint).not.toBe('');
  });

  it('mentions the hold time when the state sets one', () => {
    const base = { recurrence_type: 'sensor', sensor_mode: 'state', sensor_state: 'on' };
    expect(sensorHintText({ ...base, sensor_for: 600 })).toContain('600');
    // A zero hold is "no hold", not "for 0 seconds" — the two wordings are different
    // strings and a reader would notice the difference.
    const noHold = sensorHintText({ ...base, sensor_for: 0 });
    expect(noHold).not.toContain('0');
    expect(noHold).not.toBe(sensorHintText({ ...base, sensor_for: 600 }));
  });

  it('says the plain threshold wording when the hold is zero', () => {
    const base = {
      recurrence_type: 'sensor',
      sensor_mode: 'threshold',
      sensor_comparison: '>',
      sensor_value: 90,
    };
    const noHold = sensorHintText({ ...base, sensor_for: 0 });
    const held = sensorHintText({ ...base, sensor_for: 300 });
    expect(held).toContain('300');
    expect(noHold).not.toBe(held);
  });

  it('adds the self-clearing clause when clear_on_recover is on', () => {
    const plain = sensorHintText({
      recurrence_type: 'sensor',
      sensor_mode: 'state',
      sensor_state: 'on',
    });
    const clearing = sensorHintText({
      recurrence_type: 'sensor',
      sensor_mode: 'state',
      sensor_state: 'on',
      sensor_clear_on_recover: true,
    });
    expect(clearing.startsWith(plain)).toBe(true);
    expect(clearing.length).toBeGreaterThan(plain.length);
  });

  it('adds the same clause to a threshold hint', () => {
    const clearing = sensorHintText({
      recurrence_type: 'sensor',
      sensor_mode: 'threshold',
      sensor_comparison: '>',
      sensor_value: 90,
      sensor_clear_on_recover: true,
    });
    const plain = sensorHintText({
      recurrence_type: 'sensor',
      sensor_mode: 'threshold',
      sensor_comparison: '>',
      sensor_value: 90,
    });
    expect(clearing.startsWith(plain)).toBe(true);
  });

  it('stays quiet until a state is entered', () => {
    expect(
      sensorHintText({ recurrence_type: 'sensor', sensor_mode: 'state', sensor_state: '  ' }),
    ).toBe('');
  });
});

// ── an explicit starting reading (issue #235) ────────────────────────────────

describe('task form — the meter starting reading', () => {
  const usage = (over = {}) => ({ recurrence_type: 'sensor', sensor_target: 100, ...over });

  it('offers a starting-reading box in usage mode only', () => {
    expect(taskSchema(usage()).map((f) => f.name)).toContain('sensor_baseline');
    for (const mode of ['threshold', 'state']) {
      const names = taskSchema({ recurrence_type: 'sensor', sensor_mode: mode }).map(
        (f) => f.name,
      );
      expect(names, `${mode} mode`).not.toContain('sensor_baseline');
    }
  });

  it('does not pin the box at min 0 — a meter can read negative', () => {
    // `selNumber()` hardcodes min: 0, which is stricter than the backend
    // (`_finite_float`, no range gate). A net-energy sensor reads below zero, and a
    // stored float like 660.5 has to stay re-savable.
    const field = taskSchema(usage()).find((f) => f.name === 'sensor_baseline');
    expect(field.selector.number.min).toBeUndefined();
    expect(field.selector.number.step).toBe('any');
  });

  it('flattens a stored baseline into the form', () => {
    const data = taskFormData({
      recurrence_type: 'sensor',
      sensor: { entity_id: 'sensor.odo', mode: 'usage', target: 10000, baseline: 45000 },
    });
    expect(data.sensor_baseline).toBe(45000);
  });

  it('leaves the box undefined (not "") when nothing is stored', () => {
    // `ha-selector-number` in box mode wants undefined, not an empty string — every
    // other number field in this form seeds the same way.
    expect(taskFormData({ recurrence_type: 'sensor' }).sensor_baseline).toBeUndefined();
  });

  it('sends the baseline when the box holds a number', () => {
    const payload = buildTaskPayload(usage({ sensor_entity_id: 'sensor.odo', sensor_baseline: 45000 }));
    expect(payload.sensor.baseline).toBe(45000);
  });

  it('sends a baseline of 0 rather than dropping it', () => {
    // 0 is a valid anchor (a brand-new hour meter) and falsy, so the `|| 0` idiom
    // used for `target` would be wrong here in both directions.
    const payload = buildTaskPayload(usage({ sensor_entity_id: 'sensor.odo', sensor_baseline: 0 }));
    expect(payload.sensor.baseline).toBe(0);
  });

  it('omits the baseline entirely when the box is blank', () => {
    // Blank on create means "anchor at the live reading"; blank on edit is preserved
    // by merge_update. Either way the key must not be sent.
    for (const blank of ['', null, undefined]) {
      const payload = buildTaskPayload(
        usage({ sensor_entity_id: 'sensor.odo', sensor_baseline: blank }),
      );
      expect(payload.sensor, `blank=${String(blank)}`).not.toHaveProperty('baseline');
    }
  });

  it('never sends a baseline in threshold mode, even with one in edit state', () => {
    // The flat sensor_* state survives a mode switch, and the backend *rejects*
    // sensor.baseline on a threshold binding — so a user who types a baseline and
    // then picks Threshold would otherwise save a payload that fails validation.
    const payload = buildTaskPayload({
      recurrence_type: 'sensor',
      sensor_entity_id: 'sensor.odo',
      sensor_mode: 'threshold',
      sensor_value: 90,
      sensor_baseline: 45000,
    });
    expect(payload.sensor).not.toHaveProperty('baseline');
  });

  it('respects a managed integration locking last_completed', () => {
    const locked = {
      ...usage(),
      managed_by: { integration: 'x', display_name: 'X', locked_fields: ['last_completed'] },
    };
    expect(taskSchema(locked).map((f) => f.name)).not.toContain('last_completed');
  });

  it('offers "last completed" on a new sensor task', () => {
    // It anchors the time backstop (`sensor.also_every`), so "every 10,000 mi or 12
    // months" can start its calendar half where the meter half starts.
    expect(taskSchema(usage()).map((f) => f.name)).toContain('last_completed');
    // Still hidden when editing an existing task, like every other recurrence type.
    expect(taskSchema(usage({ id: 't1' })).map((f) => f.name)).not.toContain(
      'last_completed',
    );
  });
});

describe('sensorHintText — the starting-reading arithmetic', () => {
  const usage = (over = {}) => ({ recurrence_type: 'sensor', sensor_target: 10000, ...over });

  it('reads forward from the live value when no baseline is set', () => {
    const hint = sensorHintText(usage(), { reading: 48000 });
    expect(hint).toContain('48000');
    expect(hint).toContain('58000');
  });

  it('reads from the baseline, naming what is already used and where it lands', () => {
    const hint = sensorHintText(usage({ sensor_baseline: 45000 }), { reading: 48000 });
    expect(hint).toContain('45000'); // counting from
    expect(hint).toContain('3000'); // already used
    expect(hint).toContain('55000'); // due at — NOT 58000
    expect(hint).not.toContain('58000');
  });

  it('states the due point from the baseline when the sensor has no reading yet', () => {
    const hint = sensorHintText(usage({ sensor_baseline: 45000 }), {});
    expect(hint).toContain('45000');
    expect(hint).toContain('55000');
    // With no live value there is nothing to say about what's already used — the
    // with-reading wording would be a claim the panel can't back up.
    expect(hint).toMatch(/that's 10000 of use/i);
    expect(hint).not.toMatch(/already used/i);
  });

  it('treats a blank or missing baseline as "no baseline", not as zero', () => {
    // Number('') and Number(null) are both 0, which is finite — so dropping either
    // guard would silently anchor the task at zero and quote a due point of 10000.
    for (const blank of ['', null, undefined]) {
      const hint = sensorHintText(usage({ sensor_baseline: blank }), { reading: 48000 });
      // The forward-looking wording, anchored at the live value...
      expect(hint, `blank=${String(blank)}`).toMatch(/sensor reads 48000 now/i);
      expect(hint, `blank=${String(blank)}`).toContain('58000');
      // ...and never the anchored wording, which at a phantom baseline of 0 would
      // read "counting from 0, the sensor is already 48000 past it".
      expect(hint, `blank=${String(blank)}`).not.toMatch(/counting from/i);
    }
  });

  it('counts consumed exactly equal to the target as already due', () => {
    // The boundary: `>=`, not `>`. 45,000 + 3,000 used against a 3,000 target is due.
    const hint = sensorHintText(usage({ sensor_target: 3000, sensor_baseline: 45000 }), {
      reading: 48000,
    });
    expect(hint).toMatch(/as soon as you save/i);
  });

  it('distinguishes the already-used wording from the plain due-point wording', () => {
    const hint = sensorHintText(usage({ sensor_baseline: 45000 }), { reading: 48000 });
    expect(hint).toMatch(/already used/i);
    expect(hint).not.toMatch(/as soon as you save/i);
  });

  it('warns when the starting reading is above the live one', () => {
    // The watcher treats reading < baseline as a meter reset and re-anchors, so a
    // typo silently loses the number. Say so before it is saved.
    const hint = sensorHintText(usage({ sensor_baseline: 50000 }), { reading: 48000 });
    expect(hint).toMatch(/above what the sensor reads now/i);
    expect(hint).toContain('50000');
    expect(hint).toContain('48000');
  });

  it('says so when the baseline already puts the task past its target', () => {
    // usage_met is true on creation, so the watcher arms it seconds after Create.
    const hint = sensorHintText(usage({ sensor_target: 1000, sensor_baseline: 45000 }), {
      reading: 48000,
    });
    expect(hint).toMatch(/as soon as you save/i);
    expect(hint).toContain('3000');
  });

  it('treats a baseline equal to the reading as zero used, not as a reset', () => {
    const hint = sensorHintText(usage({ sensor_baseline: 48000 }), { reading: 48000 });
    expect(hint).not.toMatch(/above what the sensor reads now/i);
    expect(hint).toContain('58000');
  });

  it('keeps the unit on every figure', () => {
    const hint = sensorHintText(usage({ sensor_target: 300, sensor_baseline: 660 }), {
      reading: 780,
      unit: 'h',
    });
    expect(hint).toContain('660 h');
    expect(hint).toContain('120 h');
    expect(hint).toContain('960 h');
  });

  it('rounds the consumed figure instead of showing float noise', () => {
    const hint = sensorHintText(usage({ sensor_target: 300, sensor_baseline: 660.1 }), {
      reading: 780.3,
    });
    expect(hint).toContain('120.2');
    expect(hint).not.toMatch(/120\.19999/);
  });

  it('still appends the backstop clause when a baseline is set', () => {
    const hint = sensorHintText(
      usage({
        sensor_baseline: 45000,
        sensor_backstop_on: true,
        sensor_also_every: 12,
        sensor_also_unit: 'months',
      }),
      { reading: 48000 },
    );
    expect(hint).toContain('55000');
    expect(hint).toMatch(/12 months/);
  });

  it('falls back to the stored binding when the form has no live baseline', () => {
    const hint = sensorHintText(
      {
        recurrence_type: 'sensor',
        sensor: { entity_id: 'sensor.odo', mode: 'usage', target: 10000, baseline: 45000 },
      },
      { reading: 48000 },
    );
    expect(hint).toContain('55000');
  });

  it('ignores a non-numeric baseline rather than rendering NaN', () => {
    const hint = sensorHintText(usage({ sensor_baseline: 'abc' }), { reading: 48000 });
    expect(hint).not.toContain('NaN');
    expect(hint).toContain('58000');
  });
});
