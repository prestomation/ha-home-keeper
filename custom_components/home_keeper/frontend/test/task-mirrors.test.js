import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

// The Settings tab's "To-do list sync" card. A mirror is a standing instruction to
// write Home Keeper's tasks onto somebody else's list, so the card has to make the
// state of each one legible before it is edited: which list it writes to (or that it
// has none yet), and how many are running.

beforeAll(() => definePanelStubs());

afterEach(() => {
  document.body.innerHTML = '';
});

/** A `hass` whose options round-trip through a mutable store, the way the backend's
 *  `set_options` does — it answers with the options it just merged. */
function makeHass({ task_mirrors = [], profiles = [], states = {} } = {}) {
  const calls = {};
  const options = {
    sync_problem_sensors: false,
    problem_sensor_exclude_entities: [],
    problem_sensor_exclude_devices: [],
    problem_sensor_exclude_areas: [],
    problem_sensor_exclude_labels: [],
    one_off_retention_days: 0,
    shopping_list_entity: '',
    profiles,
    notifications: [],
    task_mirrors,
  };
  const hass = {
    language: 'en',
    states,
    devices: {},
    callWS(msg) {
      calls[msg.type] = (calls[msg.type] || 0) + 1;
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks: [] });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [] });
        case 'home_keeper/get_options':
          return Promise.resolve({ options, own_todo_entities: ['todo.home_keeper_tasks'] });
        case 'home_keeper/set_options':
          Object.assign(options, msg.options);
          // The backend mints an id for a mirror saved without one.
          options.task_mirrors = (options.task_mirrors || []).map((m, i) => ({
            ...m,
            id: m.id || `srv${i}`,
          }));
          calls.lastSetOptions = msg.options;
          return Promise.resolve({ options });
        case 'home_keeper/get_companions':
          return Promise.resolve({ companions: [] });
        case 'frontend/get_user_data':
          return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
        default:
          return Promise.resolve({});
      }
    },
  };
  return { hass, calls, options };
}

async function mountSettings(hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('#hk-task-mirrors'));
  return panel;
}

const MIRROR = {
  id: 'm1',
  entity_id: 'todo.family',
  profile_id: 'p1',
  two_way: true,
  vanish_as_completed: true,
};

describe('Settings tab — To-do list sync card', () => {
  it('shows an empty state, and the Add button, when nothing is mirrored', async () => {
    const { hass } = makeHass();
    const panel = await mountSettings(hass);
    const card = panel.shadowRoot.querySelector('#hk-task-mirrors');
    expect(card.textContent).toContain('To-do list sync');
    expect(card.querySelector('ha-alert')).toBeTruthy();
    expect(card.querySelector('#hk-mirror-add')).toBeTruthy();
    // No mirrors means no count badge and no editor rows.
    expect(card.querySelector('.hk-section-count')).toBeNull();
    expect(card.querySelectorAll('.hk-item-card').length).toBe(0);
  });

  it('sits between Notifications and Companions in the Settings column', async () => {
    // The card is about delivery, like notifications — putting it after Companions
    // would file it with "other integrations" instead.
    const { hass } = makeHass();
    const panel = await mountSettings(hass);
    const ids = [...panel.shadowRoot.querySelectorAll('ha-card')].map((c) => c.id);
    expect(ids.indexOf('hk-task-mirrors')).toBe(ids.indexOf('hk-notifications') + 1);
    expect(ids.indexOf('hk-task-mirrors')).toBe(ids.indexOf('hk-companions') - 1);
  });

  it("titles each row with the target list's friendly name", async () => {
    const { hass } = makeHass({
      task_mirrors: [MIRROR],
      profiles: [{ id: 'p1', name: 'Overdue', filter: {} }],
      states: { 'todo.family': { attributes: { friendly_name: 'Family list' } } },
    });
    const panel = await mountSettings(hass);
    const card = panel.shadowRoot.querySelector('#hk-task-mirrors');
    expect(card.querySelector('.hk-item-name').textContent).toBe('Family list');
    expect(card.querySelector('.hk-section-count').textContent).toBe('1');
    // The empty state is gone once a mirror exists.
    expect(card.querySelector('ha-alert')).toBeNull();
    // The form is seeded from the stored mirror, with the profile flattened.
    const form = card.querySelector('ha-form');
    expect(form.data).toEqual({
      entity_id: 'todo.family',
      profile_id: 'p1',
      two_way: true,
      vanish_as_completed: true,
    });
    // Home Keeper's own list stays out of the picker.
    const entityField = form.schema.find((f) => f.name === 'entity_id');
    expect(entityField.selector.entity.exclude_entities).toEqual(['todo.home_keeper_tasks']);
  });

  it('says so when a mirror has no list picked yet', async () => {
    const { hass } = makeHass({ task_mirrors: [{ ...MIRROR, entity_id: '' }] });
    const panel = await mountSettings(hass);
    expect(
      panel.shadowRoot.querySelector('#hk-task-mirrors .hk-item-name').textContent,
    ).toBe('Not configured');
  });

  it('falls back to the entity id for a list with no state yet', async () => {
    const { hass } = makeHass({ task_mirrors: [MIRROR] });
    const panel = await mountSettings(hass);
    expect(
      panel.shadowRoot.querySelector('#hk-task-mirrors .hk-item-name').textContent,
    ).toBe('todo.family');
  });

  it('adds a blank two-way mirror the backend can mint an id for', async () => {
    const { hass, calls } = makeHass();
    const panel = await mountSettings(hass);
    panel.shadowRoot.querySelector('#hk-mirror-add').click();
    await waitFor(() => calls.lastSetOptions);
    // Both switches default on, the profile is the default filter, and the id is
    // left blank for the backend to mint (bookkeeping keys reference it).
    expect(calls.lastSetOptions.task_mirrors).toEqual([
      { id: '', entity_id: '', profile_id: null, two_way: true, vanish_as_completed: true },
    ]);
    const row = await waitFor(() =>
      panel.shadowRoot.querySelector('#hk-task-mirrors .hk-item-card'),
    );
    expect(row).toBeTruthy();
  });

  it('deletes the mirror whose row was pressed, leaving the others', async () => {
    const second = { ...MIRROR, id: 'm2', entity_id: 'todo.other' };
    const { hass, calls } = makeHass({ task_mirrors: [MIRROR, second] });
    const panel = await mountSettings(hass);
    const rows = panel.shadowRoot.querySelectorAll('#hk-task-mirrors .hk-item-card');
    expect(rows.length).toBe(2);
    rows[0].querySelector('.hk-notify-delete').click();
    await waitFor(() => calls.lastSetOptions);
    expect(calls.lastSetOptions.task_mirrors).toEqual([second]);
  });
});
