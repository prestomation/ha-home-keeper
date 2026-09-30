import { describe, expect, it } from 'vitest';
import {
  buildTaskPayload,
  isBinarySensorBinding,
  sensorHintText,
  sensorLive,
  taskFormData,
} from '../src/forms.ts';

/**
 * F02-2: an emptied optional sensor box must clear the value on save.
 *
 * Home Assistant's text and number selectors emit `undefined` for a box the user
 * emptied, and `ha-form` spreads `{ key: undefined }` into the edit state. That state
 * still holds the loaded nested `sensor`, so a `??` fallback read the stored
 * attribute, hold or unit back and saved it again.
 */

/** A loaded state/threshold task, as `_openEdit` seeds the edit state. */
const THRESHOLD = {
  id: 't1',
  name: 'Car battery',
  recurrence_type: 'sensor',
  sensor: {
    entity_id: 'sensor.car',
    mode: 'threshold',
    attribute: 'battery_level',
    comparison: '<=',
    value: 20,
    for_seconds: 600,
  },
};

const USAGE = {
  id: 't2',
  name: 'Oil change',
  recurrence_type: 'sensor',
  sensor: { entity_id: 'sensor.odo', mode: 'usage', target: 5000, unit: 'km' },
};

const BINARY = {
  id: 't3',
  name: 'Leak',
  recurrence_type: 'sensor',
  sensor: { entity_id: 'binary_sensor.leak', mode: 'state', state: 'on', attribute: 'x' },
};

describe('F02-2: clearing an optional sensor box', () => {
  it('drops a cleared attribute and hold from the payload', () => {
    const edit = { ...THRESHOLD, sensor_attribute: undefined, sensor_for: undefined };
    const payload = buildTaskPayload(edit);
    expect(payload.sensor).not.toHaveProperty('attribute');
    expect(payload.sensor).not.toHaveProperty('for_seconds');
    expect(payload.sensor.comparison).toBe('<=');
    expect(payload.sensor.value).toBe(20);
  });

  it('keeps the stored attribute and hold when the boxes were not touched', () => {
    const payload = buildTaskPayload({ ...THRESHOLD });
    expect(payload.sensor.attribute).toBe('battery_level');
    expect(payload.sensor.for_seconds).toBe(600);
  });

  it('keeps a typed value over the stored one', () => {
    const payload = buildTaskPayload({ ...THRESHOLD, sensor_attribute: 'range', sensor_for: 30 });
    expect(payload.sensor.attribute).toBe('range');
    expect(payload.sensor.for_seconds).toBe(30);
  });

  it('drops a cleared unit from a usage payload', () => {
    expect(buildTaskPayload({ ...USAGE }).sensor.unit).toBe('km');
    expect(buildTaskPayload({ ...USAGE, sensor_unit: undefined }).sensor).not.toHaveProperty(
      'unit',
    );
  });

  it('shows the cleared boxes as empty when the form is drawn again', () => {
    const data = taskFormData({
      ...THRESHOLD,
      sensor_attribute: undefined,
      sensor_for: undefined,
    });
    expect(data.sensor_attribute).toBe('');
    expect(data.sensor_for).toBe(0);
    expect(taskFormData({ ...USAGE, sensor_unit: undefined }).sensor_unit).toBe('');
    const loaded = taskFormData({ ...THRESHOLD });
    expect(loaded.sensor_attribute).toBe('battery_level');
    expect(loaded.sensor_for).toBe(600);
    expect(taskFormData({ ...USAGE }).sensor_unit).toBe('km');
  });

  it('brings the on/off picker back once the attribute is cleared', () => {
    expect(isBinarySensorBinding({ ...BINARY })).toBe(false);
    expect(isBinarySensorBinding({ ...BINARY, sensor_attribute: undefined })).toBe(true);
  });

  it('reads the entity state, not the stale attribute, for the live reading', () => {
    const hass = {
      states: { 'sensor.car': { state: '55', attributes: { battery_level: 80 } } },
    };
    expect(sensorLive(hass, { ...THRESHOLD }).reading).toBe(80);
    expect(sensorLive(hass, { ...THRESHOLD, sensor_attribute: undefined }).reading).toBe(55);
  });

  it('drops a cleared hold from the hint', () => {
    const withHold = sensorHintText({ ...THRESHOLD });
    const cleared = sensorHintText({ ...THRESHOLD, sensor_for: undefined });
    expect(withHold).not.toBe(cleared);
  });
});
