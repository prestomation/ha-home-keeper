import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

// Deleting a profile used to happen on the press, with no question asked, and the
// notifications pointing at that profile went quiet without saying so. Now the button
// opens one of two dialogs: a confirmation when nothing uses the profile, and a
// blocking notice naming the notifications when something does. The backend refuses
// the save either way, so the notice is not the gate — it is there so the panel never
// offers a button whose only outcome is an error.

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
const GARDEN = { id: 'p2', name: 'Garden', filter: FILTER, sync: SYNC };
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
const ON_GARDEN = notification('n3', 'Weekend', 'p2');

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
  await waitFor(() => panel.shadowRoot?.querySelector('#hk-profiles'));
  return panel;
}

const rows = (panel) => [...panel.shadowRoot.querySelectorAll('#hk-profiles .hk-item-card')];
const deleteButton = (row) => row.querySelector('.hk-notify-delete');
const scrim = () => document.querySelector('.hk-confirm-scrim');
const scrimButtons = () => [...scrim().querySelectorAll('ha-button')];
const buttonLabelled = (text) => scrimButtons().find((b) => b.textContent === text);

describe('Settings → Profiles — deleting a profile', () => {
  it('asks before deleting a profile nothing uses, and saves only on Delete', async () => {
    // The press alone used to be the delete. A profile is the thing a notification, the
    // card and the panel filter all point at, so losing one by a mis-tap is expensive.
    const { hass, saves } = makeHass({ profiles: [CHORES] });
    const panel = await mountSettings(hass);
    deleteButton(rows(panel)[0]).click();

    expect(scrim()).toBeTruthy();
    expect(scrim().querySelector('h2').textContent).toContain('Chores');
    expect(saves).toEqual([]);

    buttonLabelled('Delete').click();
    await waitFor(() => saves.length === 1);
    expect(saves[0].profiles).toEqual([]);
  });

  it('cancels without saving', async () => {
    const { hass, saves } = makeHass({ profiles: [CHORES] });
    const panel = await mountSettings(hass);
    deleteButton(rows(panel)[0]).click();
    buttonLabelled('Cancel').click();
    expect(scrim()).toBeNull();
    expect(saves).toEqual([]);
  });

  it('refuses a profile a notification uses, and names every one of them', async () => {
    // Naming them is the whole value: the backend refuses this save, and without the
    // names the person has no way to find what is holding the profile.
    const { hass, saves } = makeHass({
      profiles: [CHORES],
      notifications: [WALK, EVENING],
    });
    const panel = await mountSettings(hass);
    deleteButton(rows(panel)[0]).click();

    const body = scrim().querySelector('p').textContent;
    expect(body).toContain('Walk');
    expect(body).toContain('Evening');
    // No way through: a Delete here could only produce the backend's error.
    expect(buttonLabelled('Delete')).toBeUndefined();
    expect(buttonLabelled('Close')).toBeTruthy();
    expect(saves).toEqual([]);
  });

  it('counts only the notifications on the profile being deleted', async () => {
    // A notification on a *different* profile is not in the way, so the row it belongs
    // to still deletes with a plain confirmation.
    const { hass } = makeHass({ profiles: [CHORES, GARDEN], notifications: [ON_GARDEN] });
    const panel = await mountSettings(hass);
    deleteButton(rows(panel)[0]).click();
    expect(buttonLabelled('Delete')).toBeTruthy();
  });

  it('puts the row back when the save is refused', async () => {
    // The check above can be out of date — a second admin binds a notification to this
    // profile in between. The optimistic write already took the row off screen, so
    // leaving it off says the profile is gone when the backend still holds it.
    const { hass } = makeHass({
      profiles: [CHORES],
      failSetOptions: 'Profile Chores is still used by: Walk.',
    });
    const panel = await mountSettings(hass);
    deleteButton(rows(panel)[0]).click();
    buttonLabelled('Delete').click();

    await waitFor(() => rows(panel).length === 1);
    expect(panel._options.profiles).toEqual([CHORES]);
  });

  it('does not roll a second delete back over a first one that already landed', async () => {
    // The rollback restores a snapshot, so the question is whether two deletes in
    // flight at once can restore each other's row. They cannot: each snapshot is taken
    // *after* the previous delete's optimistic write, and `isNewest()` stops a stale
    // save writing at all. Deleting both profiles in one go leaves both gone.
    const { hass, saves } = makeHass({ profiles: [CHORES, GARDEN] });
    const panel = await mountSettings(hass);
    deleteButton(rows(panel)[0]).click();
    buttonLabelled('Delete').click();
    await waitFor(() => saves.length === 1);
    deleteButton(rows(panel)[0]).click();
    buttonLabelled('Delete').click();
    await waitFor(() => saves.length === 2);
    expect(panel._options.profiles).toEqual([]);
  });

  it('keeps what the user typed when an edit is refused', async () => {
    // The opposite rule, and the reason the rollback is opt-in: a rejected *edit* has
    // text in a field, and taking it back out under them loses the retry.
    const { hass } = makeHass({ profiles: [CHORES], failSetOptions: 'nope' });
    const panel = await mountSettings(hass);
    const form = rows(panel)[0].querySelector('.hk-item-body > ha-form');
    form.dispatchEvent(
      new CustomEvent('value-changed', { detail: { value: { name: 'Renamed' } } }),
    );
    await waitFor(() => panel._options.profiles[0].name === 'Renamed');
    expect(panel._options.profiles[0].name).toBe('Renamed');
  });
});
