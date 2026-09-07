import { beforeAll, afterEach, describe, expect, it } from 'vitest';
import { definePanelStubs, makeHass, waitFor } from './panel-harness.js';

/**
 * A task detail page describes an **availability** binding in its own words.
 *
 * The detail's Sensor row is built by a chain of `if (mode === …)` guards that ends in
 * the usage meter. `availability` had no guard, so it fell through and the page read
 * "Target 0 (sensor.hallway_lux)" beside a Recurrence of "Every of use" — for a task
 * whose whole condition is "this entity went away". Nothing failed, because no test
 * looked at that surface: the exploratory walk found it in a screenshot.
 *
 * The three cases mirror `sensor_watcher.read_availability_status`: an entity with a
 * real state, one reporting `unavailable`/`unknown`, and one that is not in the state
 * machine at all (deleted, or not loaded yet) — which is neither the arm signal nor a
 * healthy reading.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const LUX = 'sensor.hallway_lux';

const TASK = {
  id: 'avail1',
  name: 'Check on Hallway Motion',
  recurrence_type: 'sensor',
  sensor: { entity_id: LUX, mode: 'availability', for_seconds: 300, clear_on_recover: true },
  enabled: true,
  completions: [],
};

/** Mount the task's own page with *states* in the state machine, and return its text. */
async function detailText(states) {
  const hass = makeHass({ tasks: [TASK] });
  hass.states = states;
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/tasks/avail1' };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('.d-edit'));
  return panel.shadowRoot.textContent;
}

describe('task detail — availability binding', () => {
  it('names the entity and calls it available when it has a real state', async () => {
    const text = await detailText({ [LUX]: { state: '24', attributes: {} } });
    expect(text).toContain(LUX);
    expect(text).toContain('available');
    // The meter's words belong to the meter.
    expect(text).not.toContain('of use');
    expect(text).not.toContain('Target 0');
  });

  it('calls it unavailable when the entity reports unavailable', async () => {
    const text = await detailText({ [LUX]: { state: 'unavailable', attributes: {} } });
    expect(text).toContain('unavailable');
    expect(text).not.toContain('of use');
  });

  it('treats unknown the same as unavailable', async () => {
    // `read_availability_status` groups them: neither is a reading.
    const text = await detailText({ [LUX]: { state: 'unknown', attributes: {} } });
    expect(text).toContain('unavailable');
  });

  it('says the entity is not found when it is absent from the state machine', async () => {
    // Indeterminate, not the arm signal — the binding may point at an entity that was
    // renamed or has not loaded yet, and saying "unavailable" there would be a lie.
    const text = await detailText({});
    expect(text).toContain('not found');
    expect(text).not.toContain('of use');
  });

  it('reads a bound attribute rather than the entity state', async () => {
    // An attribute binding is unavailable when the attribute is missing, even though
    // the entity itself is perfectly healthy.
    const attrTask = {
      ...TASK,
      sensor: { ...TASK.sensor, attribute: 'battery_level' },
    };
    const hass = makeHass({ tasks: [attrTask] });
    hass.states = { [LUX]: { state: '24', attributes: {} } };
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: '/tasks/avail1' };
    document.body.appendChild(panel);
    panel.hass = hass;
    await waitFor(() => panel.shadowRoot?.querySelector('.d-edit'));
    expect(panel.shadowRoot.textContent).toContain('unavailable');
  });

  it('draws no meter bar — there is no interval to be partway through', async () => {
    const hass = makeHass({ tasks: [TASK] });
    hass.states = { [LUX]: { state: '24', attributes: {} } };
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: '/tasks/avail1' };
    document.body.appendChild(panel);
    panel.hass = hass;
    await waitFor(() => panel.shadowRoot?.querySelector('.d-edit'));
    expect(panel.shadowRoot.querySelector('.hk-meter')).toBeNull();
  });
});
