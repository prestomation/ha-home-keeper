import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

// Settings → Notifications → "Send to" offers every notify service Home Keeper may use,
// not only the phones (#521). `persistent_notification` is allowed on the server, but the
// picker once listed `mobile_app_*` only, so a user without a phone could not choose it.
// A phone is still what gives buttons, so the hint to install the app stays until one is
// listed, while the amber mark fires only when there is no target at all.

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

function makeHass({ notifyTargets }) {
  const profiles = [profile('p1', 'My chores', 'all')];
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
          return Promise.resolve({ options, notify_targets: notifyTargets, own_todo_entities: [] });
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

const card = (panel) => panel.shadowRoot.querySelector('#hk-notifications');
const alerts = (panel) => [...card(panel).querySelectorAll('ha-alert')].map((a) => a.textContent);
const hasPhoneHint = (panel) => alerts(panel).some((text) => text.includes('companion app'));
const deliveryForm = (panel) =>
  [...card(panel).querySelectorAll('ha-form')].find((f) => f.data && 'targets' in f.data);
const targetOptions = (panel) =>
  deliveryForm(panel)
    .schema.find((f) => f.name === 'targets')
    .selector.select.options.map((o) => o.value);
const railDot = (panel) => panel.shadowRoot.querySelector('.hk-rail-dot.warn');

describe('Settings → Notifications — Send to targets', () => {
  it('lists persistent_notification for a user with no phone', async () => {
    const { hass } = makeHass({ notifyTargets: ['persistent_notification'] });
    const panel = await mountSettings(hass);
    expect(targetOptions(panel)).toEqual(['persistent_notification']);
  });

  it('says what persistent_notification does under the picker', async () => {
    const { hass } = makeHass({ notifyTargets: ['persistent_notification'] });
    const panel = await mountSettings(hass);
    const helper = deliveryForm(panel).computeHelper({ name: 'targets' });
    expect(helper).toContain('no buttons');
  });

  it('labels the field without limiting it to mobile apps', async () => {
    const { hass } = makeHass({ notifyTargets: ['persistent_notification'] });
    const panel = await mountSettings(hass);
    const label = deliveryForm(panel).computeLabel({ name: 'targets' });
    expect(label).toBe('Send to');
  });

  it('keeps the phone hint, and no warning, while only persistent_notification is listed', async () => {
    const { hass } = makeHass({ notifyTargets: ['persistent_notification'] });
    const panel = await mountSettings(hass);
    expect(hasPhoneHint(panel)).toBe(true);
    expect(railDot(panel)).toBeNull();
  });

  it('drops the phone hint once a phone is listed', async () => {
    const { hass } = makeHass({
      notifyTargets: ['mobile_app_phone', 'persistent_notification'],
    });
    const panel = await mountSettings(hass);
    expect(hasPhoneHint(panel)).toBe(false);
    expect(railDot(panel)).toBeNull();
  });

  it('warns when no target is listed at all', async () => {
    const { hass } = makeHass({ notifyTargets: [] });
    const panel = await mountSettings(hass);
    expect(hasPhoneHint(panel)).toBe(true);
    expect(railDot(panel)).not.toBeNull();
  });
});
