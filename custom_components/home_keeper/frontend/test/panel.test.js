import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { HomeKeeperPanel } from '../src/panel.ts';

// The panel waits for HA's lazy components before first paint. Register
// lightweight stand-ins so `whenDefined` resolves and the markup is valid in
// jsdom, then register the panel element itself.
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

// Mock hass whose callWS records how many times each command type was invoked.
function makeHass() {
  const calls = {};
  const options = {
    sync_problem_sensors: true,
    problem_sensor_exclude_entities: [],
    problem_sensor_exclude_areas: [],
    problem_sensor_exclude_labels: [],
  };
  const hass = {
    language: 'en',
    states: {},
    devices: {},
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
          return Promise.resolve({ options });
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

describe('Settings tab — exclusions take effect immediately', () => {
  it('re-fetches tasks after an exclusion is saved (so the change is reflected right away)', async () => {
    const { hass, calls } = makeHass();
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: '/settings' };
    document.body.appendChild(panel); // connectedCallback -> boot
    panel.hass = hass; // first hass -> initial load + render

    // The settings form should render once the initial load completes.
    const form = await waitFor(() => panel.shadowRoot?.querySelector('#hk-settings ha-form'));
    expect(form, 'settings form should render').toBeTruthy();

    // Baseline: how many task fetches happened during the initial load.
    const tasksBefore = calls['home_keeper/get_tasks'] || 0;

    // Simulate the user adding an entity to the skip list. `ha-form` emits a
    // `value-changed` with the full form value; the panel autosaves it.
    form.dispatchEvent(
      new CustomEvent('value-changed', {
        detail: {
          value: {
            sync_problem_sensors: true,
            problem_sensor_exclude_entities: ['binary_sensor.sump_pump_problem'],
            problem_sensor_exclude_areas: [],
            problem_sensor_exclude_labels: [],
          },
        },
      }),
    );

    // The save must persist the option AND refresh the cached tasks — otherwise the
    // excluded sensor's synced task lingers in the panel until the next refresh.
    const saved = await waitFor(() => (calls['home_keeper/set_options'] || 0) > 0);
    expect(saved, 'set_options should be sent').toBeTruthy();

    const refreshed = await waitFor(
      () => (calls['home_keeper/get_tasks'] || 0) > tasksBefore,
    );
    expect(
      refreshed,
      'tasks should be re-fetched after saving an exclusion so it takes effect right away',
    ).toBeTruthy();
  });
});

// Field names present in an ha-form schema, including those nested in `grid` groups.
function schemaFieldNames(schema) {
  const names = [];
  for (const field of schema) {
    if (field.name) names.push(field.name);
    if (field.type === 'grid' && field.schema) names.push(...schemaFieldNames(field.schema));
  }
  return names;
}

// The real `ha-form` updates its own `.data` before emitting `value-changed` (the
// event carries the form's current snapshot); the `ha-form` stand-in registered in
// `beforeAll` is a bare custom element that doesn't, so tests simulate that ordering.
function emitChange(form, value) {
  form.data = { ...form.data, ...value };
  form.dispatchEvent(new CustomEvent('value-changed', { detail: { value } }));
}

describe('Appliance form — existing-device identity fields (issue #145)', () => {
  it('shows manufacturer/model/serial number for an existing-device appliance, prefilled from the linked HA device without clobbering user input', async () => {
    const { hass } = makeHass();
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: '/appliances' };
    document.body.appendChild(panel);
    panel.hass = hass;

    const addBtn = await waitFor(() => panel.shadowRoot?.querySelector('#add-btn'));
    expect(addBtn, 'add button should render').toBeTruthy();
    addBtn.click();

    const identityVirtual = await waitFor(() =>
      panel.shadowRoot?.querySelector('#hk-asset-form ha-form'),
    );
    expect(identityVirtual, 'identity form should render for a new (virtual) appliance').toBeTruthy();
    const virtualNames = schemaFieldNames(identityVirtual.schema);
    expect(virtualNames).toContain('parent_asset_id');
    expect(virtualNames).not.toContain('device_id');

    // Switch to "existing device" — this swaps the schema (a full re-render), so the
    // form element itself is replaced.
    emitChange(identityVirtual, {
      kind: 'existing',
      name: '',
      manufacturer: '',
      model: '',
      serial_number: '',
      icon: '',
      area_id: undefined,
    });

    const identityExisting = await waitFor(() => {
      const f = panel.shadowRoot?.querySelector('#hk-asset-form ha-form');
      return f && schemaFieldNames(f.schema).includes('device_id') ? f : null;
    });
    expect(identityExisting, 'identity form should re-render with device_id once kind is existing').toBeTruthy();
    const existingNames = schemaFieldNames(identityExisting.schema);
    // The gap issue #145 reports: an existing-device appliance previously only got a
    // device picker, none of the fields a virtual appliance gets.
    expect(existingNames).toEqual(
      expect.arrayContaining(['device_id', 'name', 'manufacturer', 'model', 'serial_number', 'icon']),
    );
    // Only a device Home Keeper owns can nest under another via via_device
    // (normalize_fields forces an existing-device asset's parent_asset_id to None).
    expect(existingNames).not.toContain('parent_asset_id');

    // Picking a linked device prefills empty manufacturer/model/serial_number from it.
    hass.devices.device1 = {
      id: 'device1',
      name: 'Furnace',
      manufacturer: 'Acme',
      model: 'Widget 3000',
      serial_number: 'SN-123',
    };
    emitChange(identityExisting, {
      kind: 'existing',
      device_id: 'device1',
      name: '',
      manufacturer: '',
      model: '',
      serial_number: '',
      icon: '',
      area_id: undefined,
    });
    expect(identityExisting.data.manufacturer).toBe('Acme');
    expect(identityExisting.data.model).toBe('Widget 3000');
    expect(identityExisting.data.serial_number).toBe('SN-123');

    // Re-pointing to a different device never overwrites a value the user already has
    // set (whether typed manually or kept from the previous device's prefill).
    hass.devices.device2 = {
      id: 'device2',
      name: 'Boiler',
      manufacturer: 'OtherCo',
      model: 'Different model',
      serial_number: 'SN-999',
    };
    emitChange(identityExisting, {
      kind: 'existing',
      device_id: 'device2',
      name: '',
      manufacturer: 'MyCustomMfg',
      model: 'Widget 3000',
      serial_number: 'SN-123',
      icon: '',
      area_id: undefined,
    });
    expect(identityExisting.data.manufacturer).toBe('MyCustomMfg');
    expect(identityExisting.data.model).toBe('Widget 3000');
    expect(identityExisting.data.serial_number).toBe('SN-123');
  });
});
