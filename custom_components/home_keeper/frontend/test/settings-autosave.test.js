import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

// The Settings tab autosaves each row's `ha-form` on a debounce, so nothing in
// Profiles or Notifications has a Save button. That makes the debounce the whole
// durability story for those two cards, and it used to lose edits (#255): the timer
// was keyed by the *list*, so a second row touched inside the window cancelled the
// first row's pending save, and the payload had been built from a snapshot of the
// options taken before that row was edited. The user saw "Saved" and the value was
// gone on the next load.
//
// Two rows edited in quick succession is the ordinary case for this card — configure
// one notification, then the next — so it is worth a test of its own rather than
// leaving it to the panel's other suites, none of which open two rows.

beforeAll(() => definePanelStubs());

afterEach(() => {
  document.body.innerHTML = '';
});

const PROFILE = {
  id: 'p1',
  name: 'Everything',
  filter: {
    status: 'all',
    labels: [],
    areas: [],
    devices: [],
    exclude_labels: [],
    exclude_areas: [],
    exclude_devices: [],
  },
  sync: { entity_id: '', two_way: true, vanish_as_completed: true },
};

const notification = (id, name) => ({
  id,
  name,
  profile_id: 'p1',
  targets: ['mobile_app_phone'],
  actions: ['complete'],
  style: 'walk',
  channel: '',
  urgency: 'normal',
  snooze_hours: 24,
  auto: { overdue: false, due_soon: false },
});

/** A `hass` whose `set_options` merges like the backend's, so a write that drops a
 *  key is visible here exactly as it would be after a reload. */
function makeHass(notifications) {
  const options = {
    sync_problem_sensors: false,
    problem_sensor_exclude_entities: [],
    problem_sensor_exclude_devices: [],
    problem_sensor_exclude_areas: [],
    problem_sensor_exclude_labels: [],
    one_off_retention_days: 0,
    shopping_list_entity: '',
    profiles: [PROFILE],
    notifications,
  };
  const saves = [];
  const hass = {
    language: 'en',
    states: { 'notify.mobile_app_phone': { entity_id: 'notify.mobile_app_phone' } },
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
          saves.push(structuredClone(msg.options));
          Object.assign(options, msg.options);
          return Promise.resolve({ options });
        case 'home_keeper/get_companions':
          return Promise.resolve({ companions: [] });
        case 'frontend/get_user_data':
          return Promise.resolve({ value: true });
        default:
          return Promise.resolve({});
      }
    },
  };
  return { hass, options, saves };
}

async function mountSettings(hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('#hk-notifications'));
  return panel;
}

const rows = (panel) => [...panel.shadowRoot.querySelectorAll('#hk-notifications .hk-item-card')];
const formOf = (row) => row.querySelector('.hk-item-body > ha-form');

/** Edit one row the way `ha-form` does — the whole form value, one field changed. */
function edit(panel, index, patch) {
  const row = rows(panel)[index];
  const form = formOf(row);
  form.dispatchEvent(
    new CustomEvent('value-changed', { detail: { value: { ...form.data, ...patch } } }),
  );
}

describe('Settings → Notifications — autosave across rows', () => {
  it('keeps both edits when a second row is touched inside the debounce window', async () => {
    // The reported failure: configure one notification, start on the next before the
    // first has saved, and the first one's channel is silently back to empty.
    const { hass, options } = makeHass([notification('n1', 'Bins'), notification('n2', 'Meds')]);
    const panel = await mountSettings(hass);

    edit(panel, 0, { channel: 'Trash' });
    edit(panel, 1, { channel: 'Medication' });

    await waitFor(() => options.notifications.every((n) => n.channel));
    expect(options.notifications.map((n) => n.channel)).toEqual(['Trash', 'Medication']);
  });

  it('saves each row once rather than re-writing the whole card per row', async () => {
    // A per-row timer must not become a per-row *storm*: each row still coalesces its
    // own keystrokes, so two edited rows are two writes, not four.
    const { hass, saves, options } = makeHass([
      notification('n1', 'Bins'),
      notification('n2', 'Meds'),
    ]);
    const panel = await mountSettings(hass);

    edit(panel, 0, { channel: 'Tr' });
    edit(panel, 0, { channel: 'Trash' });
    edit(panel, 1, { channel: 'Me' });
    edit(panel, 1, { channel: 'Medication' });

    await waitFor(() => options.notifications.every((n) => n.channel));
    expect(saves).toHaveLength(2);
  });
});

describe('Settings → Profiles — autosave across rows', () => {
  it('keeps both renames when two profiles are edited in quick succession', async () => {
    // Profiles autosave through the same helper, so they had the same defect.
    const second = { ...PROFILE, id: 'p2', name: 'Downstairs' };
    const { hass, options } = makeHass([notification('n1', 'Bins')]);
    options.profiles = [PROFILE, second];
    const panel = await mountSettings(hass);

    const profileRows = [...panel.shadowRoot.querySelectorAll('#hk-profiles .hk-item-card')];
    expect(profileRows).toHaveLength(2);
    for (const [i, name] of [
      [0, 'Everything renamed'],
      [1, 'Downstairs renamed'],
    ]) {
      const form = profileRows[i].querySelector('.hk-item-body > ha-form');
      form.dispatchEvent(
        new CustomEvent('value-changed', { detail: { value: { ...form.data, name } } }),
      );
    }

    await waitFor(() => options.profiles.every((p) => p.name.endsWith('renamed')));
    expect(options.profiles.map((p) => p.name)).toEqual([
      'Everything renamed',
      'Downstairs renamed',
    ]);
  });
});
