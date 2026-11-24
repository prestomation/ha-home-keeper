import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

// Deleting a notification asked nothing, though the profile beside it did. It now asks,
// names the notification, puts the action word on the red button, and saves only on that
// button. Cancel, Escape and a tap outside save nothing.

beforeAll(() => definePanelStubs());

afterEach(() => {
  document.body.innerHTML = '';
  document.querySelectorAll('.hk-confirm-scrim').forEach((el) => el.remove());
});

const FILTER = {
  status: 'overdue',
  labels: [],
  areas: [],
  devices: [],
  exclude_labels: [],
  exclude_areas: [],
  exclude_devices: [],
};

const SYNC = { entity_id: '', two_way: true, vanish_as_completed: true };
const CHORES = { id: 'p1', name: 'Chores', filter: FILTER, sync: SYNC };
/** The stored shape the notification row renders from — `auto` and the style fields
 *  are what `notifyFormData` reads, so a fixture without them cannot be drawn. */
const notification = (id, name, profileId) => ({
  id,
  name,
  profile_id: profileId,
  targets: [],
  actions: [],
  snooze_hours: 3,
  style: 'walk',
  channel: '',
  urgency: 'normal',
  icon: '',
  color: '',
  auto: { overdue: false, due_soon: false },
});

const WALK = notification('n1', 'Walk', 'p1');
const EVENING = notification('n2', 'Evening', 'p1');

/** A `hass` whose options round-trip through a mutable store. `failSetOptions` makes
 *  the next save reject, the way the backend's profile-in-use guard does. */
function makeHass({ profiles = [], notifications = [], failSetOptions = null } = {}) {
  const saves = [];
  const options = {
    sync_problem_sensors: false,
    problem_sensor_exclude_entities: [],
    problem_sensor_exclude_devices: [],
    problem_sensor_exclude_areas: [],
    problem_sensor_exclude_labels: [],
    one_off_retention_days: 0,
    shopping_list_entity: '',
    profiles,
    notifications,
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
          saves.push(msg.options);
          if (failSetOptions) return Promise.reject(new Error(failSetOptions));
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
  return { hass, saves };
}

async function mountSettings(hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('#hk-notifications'));
  return panel;
}

const rows = (panel) =>
  [...panel.shadowRoot.querySelectorAll('#hk-notifications .hk-item-card')];
const deleteButton = (row) => row.querySelector('.hk-notify-delete');
const scrim = () => document.querySelector('.hk-confirm-scrim');
const buttonLabelled = (text) =>
  [...scrim().querySelectorAll('ha-button')].find((b) => b.textContent === text);

describe('Settings → Notifications — deleting a notification', () => {
  it('asks first, names the notification, and saves only on the action button', async () => {
    const { hass, saves } = makeHass({ profiles: [CHORES], notifications: [WALK, EVENING] });
    const panel = await mountSettings(hass);
    deleteButton(rows(panel)[0]).click();

    expect(scrim()).toBeTruthy();
    expect(scrim().querySelector('h2').textContent).toBe('Delete "Walk"?');
    expect(saves).toEqual([]);

    buttonLabelled('Delete notification').click();
    await waitFor(() => saves.length === 1);
    expect(saves[0].notifications.map((n) => n.id)).toEqual(['n2']);
  });

  it('saves nothing on Cancel, on Escape or on a tap outside', async () => {
    const { hass, saves } = makeHass({ profiles: [CHORES], notifications: [WALK] });
    const panel = await mountSettings(hass);
    for (const close of [
      () => buttonLabelled('Cancel').click(),
      () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })),
      () => scrim().click(),
    ]) {
      deleteButton(rows(panel)[0]).click();
      expect(scrim()).toBeTruthy();
      close();
      expect(scrim()).toBeNull();
    }
    await new Promise((r) => setTimeout(r, 30));
    expect(saves).toEqual([]);
  });
});
