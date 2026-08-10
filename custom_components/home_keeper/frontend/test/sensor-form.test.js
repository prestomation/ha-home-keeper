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
