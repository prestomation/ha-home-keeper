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

// ── Markdown notes (issue #163) ──────────────────────────────────────────────
// `ha-markdown` is one of HA's lazily-loaded elements, so the panel renders an
// escaped `pre-wrap` fallback until it registers. Both branches are exercised: the
// panel tests below register a stand-in so the `ha-markdown` path is the live one.

/** Build a hass whose get_tasks/get_assets return the supplied fixtures. */
function makeHassWith({ tasks = [], assets = [] } = {}) {
  const { hass, calls } = makeHass();
  const inner = hass.callWS.bind(hass);
  hass.callWS = (msg) => {
    if (msg.type === 'home_keeper/get_tasks') return Promise.resolve({ tasks });
    if (msg.type === 'home_keeper/get_assets') return Promise.resolve({ assets });
    if (msg.type === 'home_keeper/update_task' || msg.type === 'home_keeper/update_asset') {
      calls[msg.type] = (calls[msg.type] || 0) + 1;
      calls.lastUpdate = msg;
      return Promise.resolve({ task: tasks[0], asset: assets[0] });
    }
    return inner(msg);
  };
  return { hass, calls };
}

async function mountPanel(hass, path) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  panel.hass = hass;
  return panel;
}

describe('Notes render as Markdown (issue #163)', () => {
  beforeAll(() => {
    if (!customElements.get('ha-markdown')) {
      customElements.define('ha-markdown', class extends HTMLElement {});
    }
  });

  it('renders a task note through ha-markdown, with the source on .content', async () => {
    const task = {
      id: 't1',
      name: 'Replace filter',
      notes: '**Bold** and a [link](https://example.com)',
      recurrence_type: 'floating',
      interval: 3,
      unit: 'months',
      next_due: '2030-01-01T00:00:00+00:00',
      completions: [],
    };
    const panel = await mountPanel(makeHassWith({ tasks: [task] }).hass, '/tasks/t1');

    const md = await waitFor(() => panel.shadowRoot?.querySelector('ha-markdown'));
    expect(md, 'the note should render through ha-markdown').toBeTruthy();
    // `content` is a property, so `_hydrate` must move `data-md` onto it — otherwise
    // ha-markdown renders nothing at all.
    expect(md.content).toBe('**Bold** and a [link](https://example.com)');
  });

  it('never injects the note as raw markup', async () => {
    const task = {
      id: 't1',
      name: 'Nasty',
      notes: '<img src=x onerror=alert(1)>',
      recurrence_type: 'floating',
      interval: 1,
      unit: 'days',
      completions: [],
    };
    const panel = await mountPanel(makeHassWith({ tasks: [task] }).hass, '/tasks/t1');

    const md = await waitFor(() => panel.shadowRoot?.querySelector('ha-markdown'));
    expect(md).toBeTruthy();
    // The payload survives verbatim as *text* on the property (ha-markdown sanitizes
    // when it renders) but never becomes an element in our shadow root.
    expect(md.content).toBe('<img src=x onerror=alert(1)>');
    expect(panel.shadowRoot.querySelector('img')).toBeNull();
  });

  it('offers an inline note editor on an ordinary task, and saves via update_task', async () => {
    const task = {
      id: 't1',
      name: 'Replace filter',
      notes: 'old note',
      recurrence_type: 'floating',
      interval: 3,
      unit: 'months',
      completions: [],
    };
    const { hass, calls } = makeHassWith({ tasks: [task] });
    const panel = await mountPanel(hass, '/tasks/t1');

    // Previously this affordance existed only for problem-sensor tasks.
    const edit = await waitFor(() => panel.shadowRoot?.querySelector('.d-note-edit'));
    expect(edit, 'every task detail should offer an inline note editor').toBeTruthy();
    edit.click();

    const input = await waitFor(() => panel.shadowRoot?.querySelector('.d-note-input'));
    expect(input, 'the editor should open a textarea').toBeTruthy();
    expect(input.value).toBe('old note');
    // The live preview lives directly under the textarea.
    expect(panel.shadowRoot.querySelector('.d-note-preview .hk-md-preview')).toBeTruthy();

    input.value = '# new note';
    panel.shadowRoot.querySelector('.d-note-save').click();

    const saved = await waitFor(() => calls['home_keeper/update_task']);
    expect(saved, 'saving should go through the ordinary partial update path').toBeTruthy();
    expect(calls.lastUpdate.updates).toEqual({ notes: '# new note' });
  });

  it('keeps a source-locked note read-only', async () => {
    const task = {
      id: 't1',
      name: 'Replace battery',
      notes: 'managed note',
      recurrence_type: 'triggered',
      completions: [],
      managed_by: { domain: 'battery_notes', display_name: 'Battery Notes', locked_fields: ['notes'] },
    };
    const panel = await mountPanel(makeHassWith({ tasks: [task] }).hass, '/tasks/t1');

    await waitFor(() => panel.shadowRoot?.querySelector('ha-markdown'));
    expect(
      panel.shadowRoot.querySelector('.d-note-edit'),
      'a note its integration locks must not be editable',
    ).toBeNull();
  });

  it('gives an appliance its own Notes card, saved via update_asset', async () => {
    const asset = { id: 'a1', kind: 'virtual', name: 'Fridge', notes: 'Filter is *behind* the kick plate' };
    const { hass, calls } = makeHassWith({ assets: [asset] });
    const panel = await mountPanel(hass, '/appliances/a1');

    const md = await waitFor(() => panel.shadowRoot?.querySelector('ha-markdown'));
    expect(md, 'the appliance detail should render its notes').toBeTruthy();
    expect(md.content).toBe('Filter is *behind* the kick plate');

    panel.shadowRoot.querySelector('.d-note-edit').click();
    const input = await waitFor(() => panel.shadowRoot?.querySelector('.d-note-input'));
    input.value = 'behind the kick plate';
    panel.shadowRoot.querySelector('.d-note-save').click();

    const saved = await waitFor(() => calls['home_keeper/update_asset']);
    expect(saved).toBeTruthy();
    // A partial update — `merge_update` carries every other field through untouched.
    expect(calls.lastUpdate.updates).toEqual({ notes: 'behind the kick plate' });
    expect(calls.lastUpdate.asset_id).toBe('a1');
  });

  it('renders a part note as Markdown on the appliance detail page', async () => {
    const asset = {
      id: 'a1',
      kind: 'virtual',
      name: 'Water heater',
      notes: '',
      parts: [{ id: 'p1', name: 'Anode rod', type: 'wear', notes: 'Torque to **40 Nm**' }],
    };
    const panel = await mountPanel(makeHassWith({ assets: [asset] }).hass, '/appliances/a1');

    const partNote = await waitFor(() =>
      panel.shadowRoot?.querySelector('.hk-part-notes ha-markdown'),
    );
    expect(partNote, 'a part with notes should render them').toBeTruthy();
    expect(partNote.content).toBe('Torque to **40 Nm**');
  });

  it('exposes a notes field in the part editor (it had none before)', async () => {
    const asset = {
      id: 'a1',
      kind: 'virtual',
      name: 'Water heater',
      parts: [{ id: 'p1', name: 'Anode rod', type: 'wear', notes: 'Torque to 40 Nm' }],
    };
    const panel = await mountPanel(makeHassWith({ assets: [asset] }).hass, '/appliances/a1');

    const editBtn = await waitFor(() => panel.shadowRoot?.querySelector('.d-edit'));
    editBtn.click();
    // Editing from a detail page navigates to the owning list and re-opens the form
    // there. `_navigate` only fires `location-changed`; in the real app HA's router
    // answers by pushing a new `route` down. Nothing does that in jsdom, so stand in
    // for the router here.
    panel.route = { prefix: '/home-keeper', path: '/appliances' };

    const partForm = await waitFor(() => {
      const forms = [...(panel.shadowRoot?.querySelectorAll('#hk-asset-form ha-form') || [])];
      return forms.find((f) => schemaFieldNames(f.schema).includes('part_name'));
    });
    expect(partForm, 'the part editor should render').toBeTruthy();
    expect(schemaFieldNames(partForm.schema)).toContain('notes');
    expect(partForm.data.notes).toBe('Torque to 40 Nm');
  });
});
