import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

/**
 * The preset picker mounted in the real panel: the groups, the search box and Show
 * all. The fake backend serves two general presets and three integration presets,
 * and reports Roborock as the one installed integration.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const spec = (tasks) => ({
  name: 'x',
  description: '',
  enabled: true,
  preset_id: null,
  selection: {},
  trigger: { mode: 'state', state: 'on', clear_on_recover: true },
  task_template: { name_template: '{{ task_name }}', notes_template: '', labels: [], task_names: tasks },
  per_entity_overrides: {},
});
const PRESETS = [
  {
    id: 'firmware_update_available',
    name: 'Firmware update available',
    description: 'Watches every update entity.',
    icon: 'mdi:update',
    requires_integration: null,
    group: 'general',
    default_spec: spec(undefined),
  },
  {
    id: 'device_pulse',
    name: 'Device Pulse',
    description: 'Ping sensors.',
    icon: 'mdi:heart-pulse',
    requires_integration: 'device_pulse',
    group: 'general',
    default_spec: spec(undefined),
  },
  {
    id: 'roborock_life_low',
    name: 'Roborock: parts near the end of their life',
    description: 'Opens a task when a part has little life left.',
    icon: 'mdi:robot-vacuum',
    requires_integration: 'roborock',
    group: 'integration',
    default_spec: spec({ filter_time_left: 'Replace the filter', side: 'Replace the side brush' }),
  },
  {
    id: 'brother_percent_low',
    name: 'Brother: parts and supplies running low',
    description: 'Opens a task when toner runs low.',
    icon: 'mdi:printer',
    requires_integration: 'brother',
    group: 'integration',
    default_spec: spec({ black: 'Replace the toner' }),
  },
  {
    id: 'ecovacs_percent_low',
    name: 'Ecovacs: parts and supplies running low',
    description: 'Opens a task when a part runs low.',
    icon: 'mdi:robot-vacuum',
    requires_integration: 'ecovacs',
    group: 'integration',
    default_spec: spec({ lifespan_filter: 'Replace the filter' }),
  },
];

function makeHass() {
  return {
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
          return Promise.resolve({ options: {} });
        case 'home_keeper/list_declarative_companions':
          return Promise.resolve({ companions: [] });
        case 'home_keeper/list_declarative_presets':
          return Promise.resolve({ presets: PRESETS });
        case 'home_keeper/installed_integrations':
          return Promise.resolve({ integrations: ['roborock'] });
        case 'frontend/get_user_data':
          return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
        default:
          return Promise.resolve({});
      }
    },
  };
}

async function openPicker() {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = makeHass();
  const button = await waitFor(() => panel.shadowRoot?.querySelector('.hk-decl-preset'), 5000);
  button.click();
  await waitFor(() => panel.shadowRoot.querySelector('ha-dialog.hk-decl-picker .hk-decl-preset-card'), 5000);
  return panel;
}

const ids = (panel, group) =>
  [...panel.shadowRoot.querySelectorAll(`.hk-decl-preset-list[data-group="${group}"] .hk-decl-preset-card`)].map(
    (c) => c.dataset.presetId,
  );

describe('the preset picker', () => {
  it('lists the installed integration first, then the general presets, and hides the rest', async () => {
    const panel = await openPicker();
    expect(ids(panel, 'mine')).toEqual(['roborock_life_low']);
    expect(ids(panel, 'general')).toEqual(['firmware_update_available', 'device_pulse']);
    expect(ids(panel, 'other')).toEqual([]);
    const heads = [...panel.shadowRoot.querySelectorAll('.hk-decl-preset-group')].map((h) => h.textContent);
    expect(heads).toEqual(['For your integrations', 'General']);
    // Each integration card lists the tasks it makes.
    const chips = [
      ...panel.shadowRoot.querySelectorAll('[data-preset-id="roborock_life_low"] .hk-decl-preset-task'),
    ].map((c) => c.textContent);
    expect(chips).toEqual(['Replace the filter', 'Replace the side brush']);
    expect(panel.shadowRoot.querySelector('.hk-decl-preset-all').textContent).toBe('Show 2 more presets');
  });

  it('shows and hides the other integrations', async () => {
    const panel = await openPicker();
    panel.shadowRoot.querySelector('.hk-decl-preset-all').click();
    expect(ids(panel, 'other')).toEqual(['brother_percent_low', 'ecovacs_percent_low']);
    // A preset for an integration that is not installed cannot be picked.
    const brother = panel.shadowRoot.querySelector('[data-preset-id="brother_percent_low"]');
    expect(brother.disabled).toBe(true);
    const all = panel.shadowRoot.querySelector('.hk-decl-preset-all');
    expect(all.textContent).toBe('Hide other integrations');
    all.click();
    expect(ids(panel, 'other')).toEqual([]);
  });

  it('searches every group and keeps the focus in the search box', async () => {
    const panel = await openPicker();
    const input = panel.shadowRoot.querySelector('#hk-decl-preset-q');
    input.focus();
    input.value = 'filter';
    input.dispatchEvent(new Event('input'));
    expect(ids(panel, 'mine')).toEqual(['roborock_life_low']);
    expect(ids(panel, 'general')).toEqual([]);
    expect(ids(panel, 'other')).toEqual(['ecovacs_percent_low']);
    expect(panel.shadowRoot.querySelector('.hk-decl-preset-all')).toBeNull();
    expect(panel.shadowRoot.activeElement).toBe(input);

    input.value = 'nothing like this';
    input.dispatchEvent(new Event('input'));
    expect(panel.shadowRoot.querySelector('.hk-decl-preset-empty').textContent).toBe(
      'No preset matches your search.',
    );
  });
});
