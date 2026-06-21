import { describe, expect, it } from 'vitest';
import { buildTaskPayload, taskFormData, taskSchema } from '../src/forms.ts';
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
