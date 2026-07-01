import { describe, expect, it } from 'vitest';
import { buildTaskPayload, sensorHintText, taskFormData, taskSchema } from '../src/forms.ts';
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
