import { beforeAll, afterEach, describe, expect, it } from 'vitest';
import { definePanelStubs, makeHass, waitFor } from './panel-harness.js';

/**
 * A task detail page describes a **template** binding in its own words.
 *
 * The same hole as `sensor-availability-detail.test.js`, dug a second time. The
 * detail's Sensor row is a chain of `if (mode === …)` guards ending in the usage
 * meter, and `template` shipped without a guard — so a task whose whole condition is
 * one Jinja expression read "Target 0 (sensor.hallway_lux)" beside a Recurrence of
 * "Every of use", and the template it was actually watching appeared nowhere on the
 * page. A Docker walk found it in a screenshot; nothing failed.
 *
 * The same miss put the task back under a live **Done** button, because
 * `EDGE_SENSOR_MODES` is the other list `template` was left out of. That half is
 * pinned in `utils.test.js`; this file pins what the page says.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const LUX = 'sensor.hallway_lux';
const SOURCE = '{{ state | float(0) >= 500 }}';

const TASK = {
  id: 'tmpl1',
  name: 'Service the lamp',
  recurrence_type: 'sensor',
  sensor: { entity_id: LUX, mode: 'template', template: SOURCE, clear_on_recover: true },
  enabled: true,
  completions: [],
};

/** Mount the task's own page with *states* in the state machine, and return its text. */
async function detailText(states, task = TASK) {
  const hass = makeHass({ tasks: [task] });
  hass.states = states;
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: `/tasks/${task.id}` };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('.hk-detail-card'));
  return panel.shadowRoot.textContent;
}

describe('task detail — template binding', () => {
  it('shows the entity, its reading and the template', async () => {
    const text = await detailText({ [LUX]: { state: '780', attributes: {} } });
    expect(text).toContain(LUX);
    expect(text).toContain('780');
    // The condition itself. Nothing else on the page says what the task watches for.
    expect(text).toContain(SOURCE);
  });

  it('never borrows the meter’s words', async () => {
    const text = await detailText({ [LUX]: { state: '780', attributes: {} } });
    expect(text).not.toContain('of use');
    expect(text).not.toContain('Target 0');
  });

  it('shows the template alone when the entity has no reading', async () => {
    // A template is free to be about exactly this — `{{ state == 'unavailable' }}` is
    // a reasonable trigger — so the row still has to name the condition.
    const text = await detailText({});
    expect(text).toContain(LUX);
    expect(text).toContain(SOURCE);
    expect(text).not.toContain('Target 0');
  });

  it('draws no meter bar — there is no interval to be partway through', async () => {
    const hass = makeHass({ tasks: [TASK] });
    hass.states = { [LUX]: { state: '780', attributes: {} } };
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: '/tasks/tmpl1' };
    document.body.appendChild(panel);
    panel.hass = hass;
    await waitFor(() => panel.shadowRoot?.querySelector('.hk-detail-card'));
    expect(panel.shadowRoot.querySelector('.hk-meter')).toBeNull();
  });

  it('offers no Done button while the task is dormant', async () => {
    // #231's shape: the page said Monitored and offered Done in the same breath, and
    // pressing it recorded a completion that moved nothing.
    const hass = makeHass({ tasks: [TASK] });
    hass.states = { [LUX]: { state: '780', attributes: {} } };
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: '/tasks/tmpl1' };
    document.body.appendChild(panel);
    panel.hass = hass;
    await waitFor(() => panel.shadowRoot?.querySelector('.hk-detail-card'));
    expect(panel.shadowRoot.querySelector('.d-done')).toBeNull();
  });
});
