import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
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
//
// `userDataStore` optionally backs HA's per-user `frontend/get_user_data` /
// `frontend/set_user_data` commands with a shared object, so two `makeHass()` mocks
// (simulating the same HA user on two different browsers/devices) can see each
// other's writes — the fixture used to reproduce issue #182.
function makeHass(userDataStore = {}) {
  const calls = {};
  const options = {
    sync_problem_sensors: true,
    problem_sensor_exclude_entities: [],
    problem_sensor_exclude_areas: [],
    problem_sensor_exclude_labels: [],
    shopping_list_entity: 'todo.shopping_list',
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
          return Promise.resolve({
            options,
            own_todo_entities: ['todo.home_keeper_tasks'],
          });
        case 'home_keeper/set_options':
          calls.lastSetOptions = msg.options;
          Object.assign(options, msg.options);
          return Promise.resolve({ options });
        case 'frontend/get_user_data':
          return Promise.resolve({ value: userDataStore[msg.key] ?? null });
        case 'frontend/set_user_data':
          userDataStore[msg.key] = msg.value;
          return Promise.resolve({});
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

describe('first-run intro banner — dismissal persists server-side per-user (#182)', () => {
  it('stays dismissed for the same user on a different browser/device', async () => {
    // A shared per-user data store, standing in for HA's server-side storage that a
    // real user's account keeps regardless of which browser/device talks to it.
    const userDataStore = {};

    // "Device A": banner shows, user dismisses it.
    const a = makeHass(userDataStore);
    const panelA = document.createElement('home-keeper-panel');
    panelA.route = { prefix: '/home-keeper', path: '/tasks' };
    document.body.appendChild(panelA);
    panelA.hass = a.hass;

    const introA = await waitFor(() => panelA.shadowRoot?.querySelector('.hk-intro'));
    expect(introA, 'intro banner should render on first load').toBeTruthy();

    panelA.shadowRoot.querySelector('ha-button.hk-intro-dismiss').click();

    const dismissedRemotely = await waitFor(
      () => (a.calls['frontend/set_user_data'] || 0) > 0,
    );
    expect(dismissedRemotely, 'dismissing should persist via frontend/set_user_data').toBeTruthy();
    expect(userDataStore['home_keeper_intro_dismissed']).toBe(true);
    panelA.remove();

    // "Device B": a fresh panel instance for the same user (no shared localStorage —
    // only the shared per-user data store) should never show the banner.
    const b = makeHass(userDataStore);
    const panelB = document.createElement('home-keeper-panel');
    panelB.route = { prefix: '/home-keeper', path: '/tasks' };
    document.body.appendChild(panelB);
    panelB.hass = b.hass;

    const loadedB = await waitFor(() => (b.calls['frontend/get_user_data'] || 0) > 0);
    expect(loadedB, 'the new device should query the per-user dismissed state').toBeTruthy();
    // Wait for the initial load to finish rendering (the add-task button only
    // appears once `_reload` — which fetched the dismissed state — has resolved).
    const addBtnB = await waitFor(() => panelB.shadowRoot?.querySelector('#add-btn'));
    expect(addBtnB, 'panel should finish its initial load').toBeTruthy();
    expect(
      panelB.shadowRoot?.querySelector('.hk-intro'),
      'the banner must not reappear on a new device once dismissed',
    ).toBeFalsy();
    panelB.remove();
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
    // An appliance's notes live under its Details sub-tab, which is a URL of its own.
    const panel = await mountPanel(hass, '/appliances/a1/details');

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
    // Editing from a detail page opens the form beside that page — no navigation, so
    // nothing here has to stand in for HA's router.

    const partForm = await waitFor(() => {
      const forms = [...(panel.shadowRoot?.querySelectorAll('#hk-asset-form ha-form') || [])];
      return forms.find((f) => schemaFieldNames(f.schema).includes('part_name'));
    });
    expect(partForm, 'the part editor should render').toBeTruthy();
    expect(schemaFieldNames(partForm.schema)).toContain('notes');
    expect(partForm.data.notes).toBe('Torque to 40 Nm');
  });

  // Issue #220: stock that isn't a count of whole things — millilitres of softener,
  // a bottle topped up a third at a time.
  it('offers a unit and a per-completion amount once a part tracks stock', async () => {
    const asset = {
      id: 'a1',
      kind: 'virtual',
      name: 'Laundry',
      parts: [
        {
          id: 'p1',
          name: 'Fabric softener',
          type: 'consumable',
          stock: 1.5,
          stock_unit: 'bottles',
          consume_quantity: 0.33,
        },
      ],
    };
    const panel = await mountPanel(makeHassWith({ assets: [asset] }).hass, '/appliances/a1');

    const editBtn = await waitFor(() => panel.shadowRoot?.querySelector('.d-edit'));
    editBtn.click();

    const partForm = await waitFor(() => {
      const forms = [...(panel.shadowRoot?.querySelectorAll('#hk-asset-form ha-form') || [])];
      return forms.find((f) => schemaFieldNames(f.schema).includes('part_name'));
    });
    const names = schemaFieldNames(partForm.schema);
    expect(names).toContain('stock_unit');
    expect(names).toContain('consume_quantity');
    expect(partForm.data.stock_unit).toBe('bottles');
    expect(partForm.data.consume_quantity).toBe(0.33);
    // The quantities must accept decimals, or the field silently refuses 0.33.
    const flat = partForm.schema.flatMap((f) => f.schema || [f]);
    for (const field of ['stock', 'reorder_at', 'consume_quantity']) {
      const found = flat.find((f) => f.name === field);
      expect(found?.selector?.number?.step, `${field} should accept decimals`).toBe('any');
    }
  });

  it('hides the per-completion amount until the part tracks stock', async () => {
    const asset = {
      id: 'a1',
      kind: 'virtual',
      name: 'Laundry',
      parts: [{ id: 'p1', name: 'Fabric softener', type: 'consumable' }],
    };
    const panel = await mountPanel(makeHassWith({ assets: [asset] }).hass, '/appliances/a1');

    const editBtn = await waitFor(() => panel.shadowRoot?.querySelector('.d-edit'));
    editBtn.click();

    const partForm = await waitFor(() => {
      const forms = [...(panel.shadowRoot?.querySelectorAll('#hk-asset-form ha-form') || [])];
      return forms.find((f) => schemaFieldNames(f.schema).includes('part_name'));
    });
    // A unit is always offered; how much a completion uses needs something to use.
    expect(schemaFieldNames(partForm.schema)).toContain('stock_unit');
    expect(schemaFieldNames(partForm.schema)).not.toContain('consume_quantity');
  });

  it("shows a measured part's stock with its unit, not as a bare count", async () => {
    const asset = {
      id: 'a1',
      kind: 'virtual',
      name: 'Laundry',
      parts: [
        {
          id: 'p1',
          name: 'Fabric softener',
          type: 'consumable',
          stock: 0.67,
          reorder_at: 0.5,
          stock_unit: 'bottles',
          consume_quantity: 0.33,
        },
      ],
    };
    const panel = await mountPanel(makeHassWith({ assets: [asset] }).hass, '/appliances/a1');

    const chips = await waitFor(() => {
      const found = [...(panel.shadowRoot?.querySelectorAll('.hk-part-chips ha-assist-chip') || [])];
      return found.length ? found : null;
    });
    const labels = chips.map((c) => c.getAttribute('label'));
    expect(labels).toContain('In stock: 0.67 bottles');
    expect(labels).toContain('Uses 0.33 bottles per completion');
  });
});

describe('Markdown preview teardown (issue #163)', () => {
  beforeAll(() => {
    if (!customElements.get('ha-markdown')) {
      customElements.define('ha-markdown', class extends HTMLElement {});
    }
  });

  const noted = {
    id: 't1',
    name: 'Replace filter',
    notes: '**bold**',
    recurrence_type: 'floating',
    interval: 1,
    unit: 'months',
    completions: [],
  };

  it('cancels a pending preview render when the panel unmounts mid-typing', async () => {
    const panel = await mountPanel(makeHassWith({ tasks: [noted] }).hass, '/tasks/t1');
    (await waitFor(() => panel.shadowRoot?.querySelector('.d-note-edit'))).click();
    const input = await waitFor(() => panel.shadowRoot?.querySelector('.d-note-input'));

    // Type Markdown, then unmount before the debounce elapses. Nothing should fire
    // against the detached subtree afterwards.
    input.value = '## typing';
    input.dispatchEvent(new Event('input'));
    const preview = panel.shadowRoot.querySelector('.d-note-preview .hk-md-preview');
    expect(preview, 'the editor should have a preview attached').toBeTruthy();

    panel.remove(); // disconnectedCallback

    await new Promise((r) => setTimeout(r, 400)); // longer than the 200ms debounce
    expect(
      preview.querySelector('ha-markdown'),
      'a disposed preview must not render after unmount',
    ).toBeNull();
  });

  it('disposes previews when navigating away with a preview timer armed', async () => {
    // The unmount case isn't the only teardown path: a view change re-renders, which
    // detaches every preview. Pin the integration, not just `dispose()` in isolation.
    const panel = await mountPanel(makeHassWith({ tasks: [noted] }).hass, '/tasks/t1');
    (await waitFor(() => panel.shadowRoot?.querySelector('.d-note-edit'))).click();
    const input = await waitFor(() => panel.shadowRoot?.querySelector('.d-note-input'));

    input.value = '## typing';
    input.dispatchEvent(new Event('input'));
    const preview = panel.shadowRoot.querySelector('.d-note-preview .hk-md-preview');
    expect(preview).toBeTruthy();

    // Navigate to the list — HA drives this by pushing a new `route`.
    panel.route = { prefix: '/home-keeper', path: '/tasks' };
    await waitFor(() => panel.shadowRoot?.querySelector('#add-btn'));

    await new Promise((r) => setTimeout(r, 400)); // past the 200ms debounce
    expect(
      preview.querySelector('ha-markdown'),
      'the detached preview must not render after the view changed',
    ).toBeNull();
  });

  it('registers every preview it builds so one teardown covers them all', async () => {
    // `_attachNotePreview` is the only constructor precisely so that disposal is a
    // single loop. If a future path builds one directly it escapes that teardown, so
    // pin the count against what is actually on screen.
    const panel = await mountPanel(makeHassWith({ tasks: [noted] }).hass, '/tasks/t1');
    (await waitFor(() => panel.shadowRoot?.querySelector('.d-note-edit'))).click();
    await waitFor(() => panel.shadowRoot?.querySelector('.d-note-input'));

    const onScreen = panel.shadowRoot.querySelectorAll('.hk-md-preview').length;
    expect(onScreen).toBeGreaterThan(0);
    expect(panel._previews.length).toBe(onScreen);

    panel.remove();
    expect(panel._previews.length, 'teardown should clear the registry').toBe(0);
  });

  it('does not re-render onto a detached panel when ha-markdown registers late', async () => {
    // `ensureMarkdown()` awaits a lazy chunk load, so it can settle after unmount.
    // The callback must check isConnected — otherwise it rebuilds the whole panel,
    // and the previews it creates would never be torn down.
    const panel = await mountPanel(makeHassWith({ tasks: [noted] }).hass, '/tasks/t1');
    await waitFor(() => panel.shadowRoot?.querySelector('ha-markdown'));

    panel.remove();
    const htmlAtUnmount = panel.shadowRoot.innerHTML;
    await new Promise((r) => setTimeout(r, 300));
    expect(panel.shadowRoot.innerHTML).toBe(htmlAtUnmount);
  });
});

// An appliance with one of each openable thing: an external link document, an uploaded
// file document, and a part carrying an attached file.
const DOC_ASSET = {
  id: 'a1',
  name: 'Garage water heater',
  kind: 'virtual',
  documents: [
    { id: 'd1', kind: 'link', name: "Owner's manual", url: 'https://example.com/manual' },
    { id: 'd2', kind: 'file', name: 'Installation guide', filename: 'guide.pdf' },
  ],
  parts: [{ id: 'p1', name: 'Anode rod', type: 'wear', file_name: 'receipt.pdf' }],
};

// hass stub serving that appliance, counting the signing round-trips.
function makeDocHass(overrides = {}) {
  const { hass, calls } = makeHass();
  const signed = { document: 0, part: 0 };
  const base = hass.callWS.bind(hass);
  hass.callWS = (msg) => {
    switch (msg.type) {
      case 'home_keeper/get_assets':
        return Promise.resolve({ assets: [DOC_ASSET] });
      case 'home_keeper/sign_document_url':
        signed.document++;
        if (overrides.failDocumentSign) return Promise.reject(new Error('nope'));
        // The signature varies per mint, so a re-sign is observable on the anchor.
        return Promise.resolve({
          url: `/api/home_keeper/document/a1/${msg.document_id}?authSig=abc${signed.document}&x=1`,
        });
      case 'home_keeper/sign_part_file_url':
        signed.part++;
        return Promise.resolve({ url: `/api/home_keeper/part_file/a1/${msg.part_id}?authSig=def` });
      default:
        return base(msg);
    }
  };
  return { hass, calls, signed };
}

// Open one of the appliance detail's sub-tabs and wait for its contents to render.
// Each sub-tab is its own URL, and only the open one renders — so a test has to say
// which section it is about.
async function openApplianceDetail(hass, tab = 'documents') {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: `/appliances/a1/${tab}` };
  document.body.appendChild(panel);
  panel.hass = hass;
  const selector = tab === 'parts' ? '.hk-part-row' : 'a.hk-doc-file';
  const link = await waitFor(() => panel.shadowRoot?.querySelector(selector));
  expect(link, `the ${tab} section should render`).toBeTruthy();
  return panel;
}

describe('Appliance detail — file links are real, pre-signed anchors (issue #164)', () => {
  it('renders an uploaded document as an anchor whose href is a pre-signed URL', async () => {
    const { hass, signed } = makeDocHass();
    const panel = await openApplianceDetail(hass);

    const file = await waitFor(() => {
      const el = panel.shadowRoot?.querySelector('a.hk-doc-file[data-doc="d2"]');
      return el?.getAttribute('href') ? el : null;
    });
    // The bug: tapping did nothing on mobile because the anchor had no href and the
    // click handler ran `window.open` *after* an async sign — which WKWebView blocks.
    expect(file, 'the file document should end up with a signed href').toBeTruthy();
    expect(file.getAttribute('href')).toBe('/api/home_keeper/document/a1/d2?authSig=abc1&x=1');
    expect(file.getAttribute('target')).toBe('_blank');
    expect(file.getAttribute('rel')).toContain('noopener');
    // A link masquerading as a button is what lost the native affordances.
    expect(file.getAttribute('role'), 'a real link, not role=button').toBeNull();
    expect(signed.document, 'the URL was minted ahead of the click').toBe(1);
  });

  it('renders an external link document as a plain anchor to its own URL', async () => {
    const { hass } = makeDocHass();
    const panel = await openApplianceDetail(hass);
    const link = panel.shadowRoot.querySelector('a.hk-doc-file:not([data-doc])');
    expect(link.getAttribute('href')).toBe('https://example.com/manual');
    expect(link.getAttribute('target')).toBe('_blank');
  });

  it("gives a part's attached file a pre-signed href too", async () => {
    const { hass, signed } = makeDocHass();
    // A part's paperclip lives with the parts, not with the documents.
    const panel = await openApplianceDetail(hass, 'parts');
    const clip = await waitFor(() => {
      const el = panel.shadowRoot?.querySelector('a.hk-part-file[data-part="p1"]');
      return el?.getAttribute('href') ? el : null;
    });
    expect(clip, "the part's paperclip should end up with a signed href").toBeTruthy();
    expect(clip.getAttribute('href')).toBe('/api/home_keeper/part_file/a1/p1?authSig=def');
    expect(signed.part).toBe(1);
  });

  it('keeps a JS fallback only while the href is missing (a failed sign)', async () => {
    const { hass } = makeDocHass({ failDocumentSign: true });
    const panel = await openApplianceDetail(hass);
    const file = panel.shadowRoot.querySelector('a.hk-doc-file[data-doc="d2"]');
    // Signing failed, so there is no href — the anchor still has to be focusable and
    // clickable rather than becoming dead text.
    expect(file.getAttribute('href')).toBeNull();
    expect(file.getAttribute('tabindex')).toBe('0');
    let opened = 0;
    const realOpen = window.open;
    window.open = () => {
      opened++;
      return null;
    };
    try {
      // The fallback signs on demand; the stub rejects, so nothing opens — what matters
      // is that the click is still handled (preventDefault) rather than navigating away.
      const evt = new MouseEvent('click', { bubbles: true, cancelable: true });
      file.dispatchEvent(evt);
      expect(evt.defaultPrevented, 'the fallback handles the click').toBe(true);
    } finally {
      window.open = realOpen;
      void opened;
    }
  });

  it('does not double-open once the anchor is signed (native navigation owns the tap)', async () => {
    const { hass } = makeDocHass();
    const panel = await openApplianceDetail(hass);
    const file = await waitFor(() => {
      const el = panel.shadowRoot?.querySelector('a.hk-doc-file[data-doc="d2"]');
      return el?.getAttribute('href') ? el : null;
    });
    const evt = new MouseEvent('click', { bubbles: true, cancelable: true });
    file.dispatchEvent(evt);
    expect(evt.defaultPrevented, 'the browser follows the href itself').toBe(false);
  });
});

describe('Appliance detail — signed hrefs are refreshed before they expire', () => {
  it('re-signs an open appliance page on a timer, so a long-lived tab never clicks into a 403', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { hass, signed } = makeDocHass();
      const panel = await openApplianceDetail(hass);
      const file = await waitFor(() => {
        const el = panel.shadowRoot?.querySelector('a.hk-doc-file[data-doc="d2"]');
        return el?.getAttribute('href') ? el : null;
      });
      expect(signed.document).toBe(1);
      const first = file.getAttribute('href');

      // Unlike the dashboard card, the panel doesn't re-render on hass updates — it
      // renders on navigation. Left alone, the href would outlive the backend's 1h TTL.
      await vi.advanceTimersByTimeAsync(46 * 60 * 1000);
      await vi.waitFor(() => expect(signed.document).toBe(2));

      // The refreshed URL is stamped onto the live anchor, not just the cache.
      await vi.waitFor(() =>
        expect(
          panel.shadowRoot.querySelector('a.hk-doc-file[data-doc="d2"]').getAttribute('href'),
        ).not.toBe(first),
      );
    } finally {
      vi.useRealTimers();
    }
  });
});

// The detail page grew an area chip alongside the device chip: once a task can be
// given an area from the form (issue #204), the page has to show which one it
// landed in — otherwise "Group by → Area" is the only confirmation the save took.
describe('Task detail — area chip (issue #204)', () => {
  const baseTask = {
    id: 't1',
    name: 'Water the plants',
    recurrence_type: 'floating',
    interval: 1,
    unit: 'weeks',
    completions: [],
  };
  const chipLabels = (panel) =>
    [...panel.shadowRoot.querySelectorAll('.hk-chips ha-assist-chip')].map((c) =>
      c.getAttribute('label'),
    );

  it('names the area of a device-less task — the case that had no UI at all', async () => {
    const { hass } = makeHassWith({ tasks: [{ ...baseTask, area_id: 'a_kitchen' }] });
    hass.areas = { a_kitchen: { area_id: 'a_kitchen', name: 'Kitchen' } };
    const panel = await mountPanel(hass, '/tasks/t1');

    await waitFor(() => panel.shadowRoot?.querySelector('.hk-chips'));
    expect(chipLabels(panel)).toContain('Kitchen');
  });

  it('falls back to the attached device’s area, matching how tasks are grouped', async () => {
    const { hass } = makeHassWith({ tasks: [{ ...baseTask, device_id: 'd1' }] });
    hass.areas = { a_garage: { area_id: 'a_garage', name: 'Garage' } };
    hass.devices = { d1: { id: 'd1', name: 'Furnace', area_id: 'a_garage' } };
    const panel = await mountPanel(hass, '/tasks/t1');

    await waitFor(() => panel.shadowRoot?.querySelector('.hk-chips'));
    expect(chipLabels(panel)).toContain('Garage');
  });

  it('prefers the task’s own area over the device’s when both are set', async () => {
    const { hass } = makeHassWith({
      tasks: [{ ...baseTask, device_id: 'd1', area_id: 'a_kitchen' }],
    });
    hass.areas = {
      a_kitchen: { area_id: 'a_kitchen', name: 'Kitchen' },
      a_garage: { area_id: 'a_garage', name: 'Garage' },
    };
    hass.devices = { d1: { id: 'd1', name: 'Furnace', area_id: 'a_garage' } };
    const panel = await mountPanel(hass, '/tasks/t1');

    await waitFor(() => panel.shadowRoot?.querySelector('.hk-chips'));
    const labels = chipLabels(panel);
    expect(labels).toContain('Kitchen');
    expect(labels).not.toContain('Garage');
  });

  it('shows no area chip when the task is unplaced', async () => {
    const { hass } = makeHassWith({ tasks: [baseTask] });
    hass.areas = { a_kitchen: { area_id: 'a_kitchen', name: 'Kitchen' } };
    const panel = await mountPanel(hass, '/tasks/t1');

    await waitFor(() => panel.shadowRoot?.querySelector('.hk-chips'));
    expect(chipLabels(panel)).not.toContain('Kitchen');
  });
});

// NFC/RFID tag binding (issue #211). The detail page names the bound tag, and a
// task that can only be completed by a scan keeps a *disabled* Done that says so —
// the backend refuses the completion, so offering a live button would only produce
// an error the user can do nothing about.
describe('Task detail — NFC tag chip and scan lock (issue #211)', () => {
  const baseTask = {
    id: 't1',
    name: 'Water the plants',
    recurrence_type: 'floating',
    interval: 1,
    unit: 'weeks',
    completions: [],
  };
  const withTags = (tasks, tags = []) => {
    const { hass, calls } = makeHassWith({ tasks });
    const inner = hass.callWS.bind(hass);
    hass.callWS = (msg) => (msg.type === 'tag/list' ? Promise.resolve(tags) : inner(msg));
    return { hass, calls };
  };
  const chipLabels = (panel) =>
    [...panel.shadowRoot.querySelectorAll('.hk-chips ha-assist-chip')].map((c) =>
      c.getAttribute('label'),
    );

  it('names the bound tag using HA’s tag registry', async () => {
    const { hass } = withTags([{ ...baseTask, tag_id: 'tag_kitchen' }], [
      { id: 'tag_kitchen', name: 'Kitchen sticker' },
    ]);
    const panel = await mountPanel(hass, '/tasks/t1');

    await waitFor(() => panel.shadowRoot?.querySelector('ha-assist-chip.hk-tag'));
    expect(chipLabels(panel)).toContain('Kitchen sticker');
  });

  it('falls back to the raw tag id when the registry does not know it', async () => {
    // A sticker can be bound before HA has ever seen a scan from it.
    const { hass } = withTags([{ ...baseTask, tag_id: 'a1b2c3' }]);
    const panel = await mountPanel(hass, '/tasks/t1');

    await waitFor(() => panel.shadowRoot?.querySelector('ha-assist-chip.hk-tag'));
    expect(chipLabels(panel)).toContain('a1b2c3');
  });

  it('shows no tag chip for an unbound task', async () => {
    const { hass } = withTags([baseTask]);
    const panel = await mountPanel(hass, '/tasks/t1');

    await waitFor(() => panel.shadowRoot?.querySelector('.hk-chips'));
    expect(panel.shadowRoot.querySelector('ha-assist-chip.hk-tag')).toBeNull();
  });

  it('keeps Done live for a tag-bound task that does not require a scan', async () => {
    const { hass } = withTags([{ ...baseTask, tag_id: 'a1b2c3' }]);
    const panel = await mountPanel(hass, '/tasks/t1');

    await waitFor(() => panel.shadowRoot?.querySelector('ha-assist-chip.hk-tag'));
    expect(panel.shadowRoot.querySelector('.d-done')).not.toBeNull();
    expect(panel.shadowRoot.querySelector('.d-done-blocked-wrap')).toBeNull();
  });

  it('blocks Done for a scan-locked task and explains on tap', async () => {
    const { hass, calls } = withTags([
      { ...baseTask, tag_id: 'a1b2c3', require_tag_scan: true },
    ]);
    const panel = await mountPanel(hass, '/tasks/t1');

    const blocked = await waitFor(() => panel.shadowRoot?.querySelector('.d-done-blocked-wrap'));
    expect(blocked, 'a scan-locked task shows a disabled Done').toBeTruthy();
    expect(panel.shadowRoot.querySelector('.d-done')).toBeNull();
    expect(blocked.getAttribute('title')).toBe("Scan this task's tag to complete it.");
    // The padlock glyph carries the same message on the chip.
    expect(
      panel.shadowRoot.querySelector('ha-assist-chip.hk-tag ha-icon').getAttribute('icon'),
    ).toBe('mdi:lock');

    const toasts = [];
    panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));
    blocked.click();
    await new Promise((r) => setTimeout(r, 20));
    expect(toasts).toEqual(["Scan this task's tag to complete it."]);
    expect(calls['home_keeper/complete_task']).toBeUndefined();
  });
});

describe('Settings tab — the Shopping list card', () => {
  it("keeps Home Keeper's own to-do list out of the picker", async () => {
    const { hass } = makeHass();
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: '/settings' };
    document.body.appendChild(panel);
    panel.hass = hass;

    const form = await waitFor(() =>
      panel.shadowRoot?.querySelector('#hk-settings-shopping ha-form'),
    );
    expect(form, 'shopping list card should render').toBeTruthy();
    expect(form.schema[0].selector.entity.exclude_entities).toEqual([
      'todo.home_keeper_tasks',
    ]);
  });

  it('turns the mirror off when the picker is cleared', async () => {
    // Clearing an entity picker emits `undefined`, which JSON drops on the way to
    // the backend — the key would never reach the partial-update merge and the
    // old list would quietly stay configured. Nothing about that is visible in
    // the UI, which is exactly why it is pinned here.
    const { hass, calls } = makeHass();
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: '/settings' };
    document.body.appendChild(panel);
    panel.hass = hass;

    const form = await waitFor(() =>
      panel.shadowRoot?.querySelector('#hk-settings-shopping ha-form'),
    );
    form.dispatchEvent(
      new CustomEvent('value-changed', { detail: { value: { shopping_list_entity: undefined } } }),
    );

    await waitFor(() => (calls['home_keeper/set_options'] || 0) > 0);
    expect(calls.lastSetOptions.shopping_list_entity).toBe('');
  });

  it('saves the list the user picked', async () => {
    const { hass, calls } = makeHass();
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: '/settings' };
    document.body.appendChild(panel);
    panel.hass = hass;

    const form = await waitFor(() =>
      panel.shadowRoot?.querySelector('#hk-settings-shopping ha-form'),
    );
    form.dispatchEvent(
      new CustomEvent('value-changed', {
        detail: { value: { shopping_list_entity: 'todo.groceries' } },
      }),
    );

    await waitFor(() => (calls['home_keeper/set_options'] || 0) > 0);
    expect(calls.lastSetOptions.shopping_list_entity).toBe('todo.groceries');
  });
});

describe('the sheet-threshold media query is bound and unbound with the element', () => {
  // jsdom has no `matchMedia`, and `_syncDrawerModality` skips the whole block without
  // one — so the panel's only viewport read is invisible to every other test here.
  // This stubs a MediaQueryList that counts its own listeners.
  function stubMatchMedia() {
    const listeners = { added: 0, removed: 0 };
    const mql = {
      matches: false,
      addEventListener: () => {
        listeners.added += 1;
      },
      removeEventListener: () => {
        listeners.removed += 1;
      },
    };
    const prior = window.matchMedia;
    window.matchMedia = () => mql;
    return { listeners, restore: () => { window.matchMedia = prior; } };
  }

  it('unbinds on unmount and binds again when the element comes back', async () => {
    const { listeners, restore } = stubMatchMedia();
    try {
      const hass = makeHassWith({ tasks: [] }).hass;

      const panel = await mountPanel(hass, '/tasks');
      await waitFor(() => panel.shadowRoot?.querySelector('.hk-wrap'));
      expect(listeners.added, 'mounting binds the threshold listener').toBe(1);

      // Unmounting takes it off: it closes over the element, so leaving it attached to
      // a live MediaQueryList keeps the whole detached shadow tree reachable.
      panel.remove();
      expect(listeners.removed, 'unmounting unbinds it').toBe(1);

      // …and coming back binds a fresh one. Clearing only the handler and leaving the
      // query behind would make this silently skip the rebind — `_syncDrawerModality`
      // only binds when the query is unset — and the panel would stop noticing the
      // sheet threshold for the rest of its life.
      document.body.appendChild(panel);
      panel.route = { prefix: '/home-keeper', path: '/appliances' };
      await waitFor(() => panel.shadowRoot?.querySelector('.hk-wrap'));
      expect(listeners.added, 're-attaching binds a new listener').toBe(2);
    } finally {
      restore();
    }
  });
});
