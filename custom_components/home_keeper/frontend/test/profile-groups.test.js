import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

// A profile's filter groups inside the real Settings tab. `group-editor.test.js`
// covers the editor on its own; this covers the half it cannot see — that the panel
// hands it the stored groups, and that adding or deleting one reaches the backend as a
// `home_keeper/set_options` write with the profile's other halves intact.

beforeAll(() => definePanelStubs());

afterEach(() => {
  document.body.innerHTML = '';
});

const TWO_GROUPS = {
  id: 'p1',
  name: 'Dog or garage',
  filter: {
    status: 'overdue',
    groups: [
      { labels: ['dog'], labels_match: 'any', areas: [], devices: [] },
      { labels: [], labels_match: 'any', areas: ['garage'], devices: [] },
    ],
  },
  sync: { entity_id: 'todo.family', two_way: true, vanish_as_completed: true },
};

/** A `hass` whose options round-trip through a mutable store, the way the backend's
 *  `set_options` does — it answers with the options it just merged. */
function makeHass({ profiles = [] } = {}) {
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
  };
  const hass = {
    language: 'en',
    states: {},
    devices: {},
    callWS(msg) {
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks: [] });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [] });
        case 'home_keeper/get_options':
          return Promise.resolve({ options, own_todo_entities: [] });
        case 'home_keeper/set_options':
          Object.assign(options, msg.options);
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
  await waitFor(() => panel.shadowRoot?.querySelector('#hk-profiles'));
  return panel;
}

const rows = (panel) => [...panel.shadowRoot.querySelectorAll('#hk-profiles .hk-item-card')];
const groupsOf = (row) => [...row.querySelectorAll('.hk-filter-groups .hk-filter-group')];
const headForm = (row) => row.querySelector('.hk-item-body > ha-form');
const addBtn = (panel, id) => panel.shadowRoot.querySelector(`#hk-profile-${id}-group-add`);
const savedGroups = (calls) => calls.lastSetOptions.profiles[0].filter.groups;
const emit = (form, value) =>
  form.dispatchEvent(new CustomEvent('value-changed', { detail: { value } }));

describe('Settings → Profiles — filter groups', () => {
  it('renders one card per stored group, with a divider between them', async () => {
    const { hass } = makeHass({ profiles: [TWO_GROUPS] });
    const panel = await mountSettings(hass);
    const row = rows(panel)[0];
    expect(groupsOf(row)).toHaveLength(2);
    expect(row.querySelectorAll('.hk-filter-or')).toHaveLength(1);
    // Each group's form is seeded from the group it draws, not from the profile.
    const forms = groupsOf(row).map((g) => g.querySelector('ha-form'));
    expect(forms[0].data.labels).toEqual(['dog']);
    expect(forms[1].data.areas).toEqual(['garage']);
    // The head form carries the profile itself, and no filter field.
    expect(headForm(row).data).toEqual({ name: 'Dog or garage', status: 'overdue' });
  });

  it('gives a profile saved with no groups one to type into', async () => {
    // An empty group selects everything, so seeding one changes nothing — and the
    // section is never a bare Add button with nothing above it.
    const { hass } = makeHass({ profiles: [{ id: 'p9', name: 'Old', filter: { status: 'all' } }] });
    const panel = await mountSettings(hass);
    expect(groupsOf(rows(panel)[0])).toHaveLength(1);
    expect(rows(panel)[0].querySelector('.hk-filter-group-delete')).toBeNull();
  });

  it('persists the added group, keeping the profile around it', async () => {
    const { hass, calls } = makeHass({ profiles: [TWO_GROUPS] });
    const panel = await mountSettings(hass);
    addBtn(panel, 'p1').click();
    await waitFor(() => calls.lastSetOptions);

    expect(savedGroups(calls)).toHaveLength(3);
    expect(savedGroups(calls)[0].labels).toEqual(['dog']);
    // The new group constrains nothing, so the profile still selects what it did.
    expect(savedGroups(calls)[2]).toEqual({
      labels: [],
      labels_match: 'any',
      areas: [],
      devices: [],
      companions: [],
      exclude_labels: [],
      exclude_areas: [],
      exclude_devices: [],
      exclude_companions: [],
      exclude_shopping: false,
    });
    // The rest of the profile rides along — an add must not be a rename or a
    // silently switched-off to-do list sync.
    expect(calls.lastSetOptions.profiles[0].name).toBe('Dog or garage');
    expect(calls.lastSetOptions.profiles[0].filter.status).toBe('overdue');
    expect(calls.lastSetOptions.profiles[0].sync).toEqual(TWO_GROUPS.sync);
  });

  it('persists a delete, keeping the group that was not deleted', async () => {
    const { hass, calls } = makeHass({ profiles: [TWO_GROUPS] });
    const panel = await mountSettings(hass);
    rows(panel)[0].querySelectorAll('.hk-filter-group-delete')[0].click();
    await waitFor(() => calls.lastSetOptions);

    expect(savedGroups(calls)).toHaveLength(1);
    expect(savedGroups(calls)[0].areas).toEqual(['garage']);
    expect(savedGroups(calls)[0].labels).toEqual([]);
  });

  it('persists an edit inside one group without disturbing the other', async () => {
    const { hass, calls } = makeHass({ profiles: [TWO_GROUPS] });
    const panel = await mountSettings(hass);
    const forms = groupsOf(rows(panel)[0]).map((g) => g.querySelector('ha-form'));
    emit(forms[1], { ...forms[1].data, areas: ['garage', 'shed'], labels_match: 'all' });
    await waitFor(() => calls.lastSetOptions);

    expect(savedGroups(calls)).toHaveLength(2);
    expect(savedGroups(calls)[0].labels).toEqual(['dog']);
    expect(savedGroups(calls)[1].areas).toEqual(['garage', 'shed']);
    expect(savedGroups(calls)[1].labels_match).toBe('all');
  });

  it('seeds a new profile with one empty group', async () => {
    const { hass, calls } = makeHass();
    const panel = await mountSettings(hass);
    panel.shadowRoot.querySelector('#hk-profile-add').click();
    await waitFor(() => calls.lastSetOptions);
    expect(savedGroups(calls)).toHaveLength(1);
    expect(savedGroups(calls)[0].labels).toEqual([]);
    expect(savedGroups(calls)[0].exclude_shopping).toBe(false);
  });
});
