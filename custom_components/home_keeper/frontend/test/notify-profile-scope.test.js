import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

// Settings → Notifications states what the notification will actually send, and heads
// its two switches "Triggers".
//
// The two answer different questions and the panel used to answer neither. A user set
// "Auto-send when overdue" and got a digest of tasks due months out, because the tasks
// come from the *profile's* Include field, in a card further up the page, and the
// switch only decides the moment (#313). So the row now names the profile's scope
// under the picker that chose it, offers a way through to that profile, and captions
// the switches with what a trigger decides.

beforeAll(() => definePanelStubs());

afterEach(() => {
  document.body.innerHTML = '';
});

const filter = (status) => ({
  status,
  labels: [],
  areas: [],
  devices: [],
  companions: [],
  exclude_labels: [],
  exclude_areas: [],
  exclude_devices: [],
  exclude_companions: [],
  exclude_shopping: false,
});

const profile = (id, name, status) => ({
  id,
  name,
  filter: filter(status),
  sync: { entity_id: '', two_way: true, vanish_as_completed: true },
});

const NOTIFICATION = {
  id: 'n1',
  name: 'Walk my chores',
  profile_id: 'p1',
  targets: ['mobile_app_phone'],
  actions: ['complete'],
  style: 'digest',
  channel: 'Chores',
  urgency: 'normal',
  icon: '',
  color: '',
  snooze_hours: 24,
  auto: { overdue: true, due_soon: false },
};

function makeHass({ profiles = [profile('p1', 'My chores', 'all')] } = {}) {
  const options = {
    sync_problem_sensors: false,
    problem_sensor_exclude_entities: [],
    problem_sensor_exclude_devices: [],
    problem_sensor_exclude_areas: [],
    problem_sensor_exclude_labels: [],
    one_off_retention_days: 0,
    shopping_list_entity: '',
    profiles,
    notifications: [NOTIFICATION],
  };
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
  return { hass, options };
}

async function mountSettings(hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('#hk-notifications'));
  return panel;
}

const row = (panel) => panel.shadowRoot.querySelector('#hk-notifications .hk-item-card');
const scope = (panel) => row(panel).querySelector('.hk-notify-scope');
const triggers = (panel) => row(panel).querySelector('.hk-indent');
const formFor = (panel, field) =>
  [...row(panel).querySelectorAll('ha-form')].find((f) => f.data && field in f.data);

describe('Settings → Notifications — what this profile sends', () => {
  it('states the scope of the chosen profile under the picker', async () => {
    const { hass } = makeHass();
    const panel = await mountSettings(hass);
    expect(scope(panel).textContent).toContain('My chores includes every scheduled task.');
  });

  it('reads each stored status back in words a user can act on', async () => {
    for (const [status, text] of [
      ['overdue', 'overdue tasks only'],
      ['due_soon', 'overdue tasks and tasks due within 3 days'],
      ['all', 'every scheduled task'],
    ]) {
      const { hass } = makeHass({ profiles: [profile('p1', 'My chores', status)] });
      const panel = await mountSettings(hass);
      expect(scope(panel).textContent).toContain(text);
      document.body.innerHTML = '';
    }
  });

  it('follows the profile picked in the form, without a re-render', async () => {
    // The line is only useful while the picker is being used, and nothing repaints the
    // row on its own: the save runs with `render: false`. So the change handler has to
    // repaint it, the same way it already repaints the footer.
    const { hass } = makeHass({
      profiles: [profile('p1', 'My chores', 'all'), profile('p2', 'Upstairs', 'overdue')],
    });
    const panel = await mountSettings(hass);
    const picker = formFor(panel, 'profile_id');
    picker.dispatchEvent(
      new CustomEvent('value-changed', { detail: { value: { ...picker.data, profile_id: 'p2' } } }),
    );
    await waitFor(() => scope(panel).textContent.includes('Upstairs'));
    expect(scope(panel).textContent).toContain('Upstairs includes overdue tasks only.');
  });

  it('says nothing at all when the profile is gone', async () => {
    // A notification whose profile was deleted has no scope to describe. An empty line
    // is hidden by CSS; a guess would be worse than silence.
    const { hass } = makeHass({ profiles: [] });
    const panel = await mountSettings(hass);
    expect(scope(panel).textContent).toBe('');
  });

  it('opens the Profiles section with that profile expanded', async () => {
    const { hass } = makeHass();
    const panel = await mountSettings(hass);
    const link = scope(panel).querySelector('button');
    expect(link.textContent).toBe('Edit this profile');
    link.click();
    await waitFor(() => panel.shadowRoot.querySelector('#hk-profiles .hk-item-body ha-form'));
    // The URL names the section, because that is the panel's single source of truth
    // for where it is. Asserted on the URL rather than on `_settingsSection`: only
    // HA's router sets that, by feeding the new path back through `route`, and there
    // is no router here.
    expect(location.pathname).toBe('/home-keeper/settings/profiles');
    // And the row is open rather than merely present — a folded row would land the
    // user on a list and make them find it again.
    expect(panel._itemExpanded.has('p1')).toBe(true);
  });
});

describe('Settings → Notifications — the Triggers group', () => {
  it('heads the two switches, and says what a trigger decides', async () => {
    const { hass } = makeHass();
    const panel = await mountSettings(hass);
    const group = triggers(panel);
    expect(group.querySelector('.hk-eyebrow').textContent).toBe('Triggers');
    expect(group.querySelector('.hk-indent-note').textContent).toBe(
      'Profiles determine which tasks a notification includes. ' +
        'Triggers determine when that notification is sent.',
    );
  });

  it('holds both switches and nothing else', async () => {
    const { hass } = makeHass();
    const panel = await mountSettings(hass);
    const form = triggers(panel).querySelector('ha-form');
    expect(Object.keys(form.data).sort()).toEqual(['auto_due_soon', 'auto_overdue']);
    expect(form.data.auto_overdue).toBe(true);
  });

  it('points at the automation examples for a trigger it cannot express', async () => {
    const { hass } = makeHass();
    const panel = await mountSettings(hass);
    const link = triggers(panel).querySelector('.hk-notify-trigger-docs a');
    expect(link.getAttribute('href')).toContain('/docs/guide/notifications#automation-examples');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
  });

  it('saves a trigger without dropping the fields the other two forms own', async () => {
    // Three forms edit one notification. Each is seeded with only its own fields, so a
    // half that re-asserted a stale snapshot of the others would quietly wipe them.
    const { hass, options } = makeHass();
    const panel = await mountSettings(hass);
    const form = triggers(panel).querySelector('ha-form');
    form.dispatchEvent(
      new CustomEvent('value-changed', {
        detail: { value: { auto_overdue: false, auto_due_soon: true } },
      }),
    );
    await waitFor(() => options.notifications[0].auto.due_soon);
    expect(options.notifications[0]).toMatchObject({
      name: 'Walk my chores',
      profile_id: 'p1',
      channel: 'Chores',
      targets: ['mobile_app_phone'],
      auto: { overdue: false, due_soon: true },
    });
  });
});
