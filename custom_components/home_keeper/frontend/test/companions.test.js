import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { HomeKeeperPanel } from '../src/panel.ts';

beforeAll(() => {
  for (const tag of [
    'ha-card',
    'ha-form',
    'ha-button',
    'ha-icon-button',
    'ha-tab-group',
    'ha-tab-group-tab',
    'ha-alert',
    'ha-assist-chip',
    'ha-menu-button',
    'ha-svg-icon',
    'ha-spinner',
    'ha-icon',
  ]) {
    if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
  }
  if (!customElements.get('home-keeper-panel')) {
    customElements.define('home-keeper-panel', HomeKeeperPanel);
  }
});

async function waitFor(fn, timeout = 2000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const v = fn();
    if (v) return v;
    await new Promise((r) => setTimeout(r, 20));
  }
  return null;
}

function makeHass(companions) {
  const calls = {};
  const options = {
    sync_problem_sensors: false,
    problem_sensor_exclude_entities: [],
    problem_sensor_exclude_areas: [],
    problem_sensor_exclude_labels: [],
    dismissed_companions: [],
  };
  const hass = {
    language: 'en',
    states: {},
    callWS(msg) {
      calls[msg.type] = (calls[msg.type] || 0) + 1;
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks: [] });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [] });
        case 'config_entries/get':
          return Promise.resolve([]);
        case 'config/label_registry/list':
          return Promise.resolve([]);
        case 'home_keeper/get_options':
          return Promise.resolve({ options });
        case 'home_keeper/set_options':
          Object.assign(options, msg.options);
          calls.lastSetOptions = msg.options;
          return Promise.resolve({ options });
        case 'home_keeper/get_companions':
          return Promise.resolve({ companions });
        default:
          return Promise.resolve({});
      }
    },
  };
  return { hass, calls };
}

afterEach(() => {
  document.body.innerHTML = '';
});

const CONNECTED = {
  domain: 'pawsistant',
  name: 'Pawsistant',
  icon: 'mdi:paw',
  description: 'Pet care schedules.',
  status: 'connected',
  configure_domain: 'pawsistant',
  config_entry_id: 'entry1',
};
const SUGGESTED = {
  domain: 'home_keeper_battery_notes',
  name: 'Battery Notes',
  icon: 'mdi:battery-alert',
  description: 'You have Battery Notes installed.',
  status: 'suggested',
  install_url: 'https://example.com/glue',
  upstream_domain: 'battery_notes',
};

async function mountSettings(hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('#hk-companions'));
  return panel;
}

describe('Settings tab — Companions section', () => {
  it('renders connected and suggested companion rows', async () => {
    const { hass } = makeHass([CONNECTED, SUGGESTED]);
    const panel = await mountSettings(hass);
    const root = panel.shadowRoot;
    expect(root.querySelector('#hk-companions')).toBeTruthy();
    // One connected (Configure) and one suggested (Install + Dismiss).
    expect(root.querySelector('.hk-comp-configure')).toBeTruthy();
    expect(root.querySelector('.hk-comp-install')).toBeTruthy();
    expect(root.querySelector('.hk-comp-dismiss')).toBeTruthy();
    expect(root.textContent).toContain('Pawsistant');
    expect(root.textContent).toContain('Battery Notes');
  });

  it('dismissing a suggestion persists its domain to dismissed_companions', async () => {
    const { hass, calls } = makeHass([SUGGESTED]);
    const panel = await mountSettings(hass);
    panel.shadowRoot.querySelector('.hk-comp-dismiss').click();
    const saved = await waitFor(() => calls['home_keeper/set_options'] > 0);
    expect(saved).toBeTruthy();
    expect(calls.lastSetOptions.dismissed_companions).toContain(
      'home_keeper_battery_notes',
    );
  });

  it('shows an empty state when there are no companions', async () => {
    const { hass } = makeHass([]);
    const panel = await mountSettings(hass);
    expect(panel.shadowRoot.querySelector('#hk-companions ha-alert')).toBeTruthy();
  });
});
