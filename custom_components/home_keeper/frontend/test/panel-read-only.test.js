/**
 * The view-only panel for a user who is not an admin (#444).
 *
 * The panel opens for every user. Every appliance write, every setting and the
 * cleanup actions stay admin-only on the backend, so the panel hides the controls
 * that call them. Task controls stay: the task services are open to every user. An
 * admin, and a user that Home Assistant does not name, see the full panel.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';
import { taskSchemaSections } from '../src/forms.ts';

beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const ASSET = {
  id: 'a1',
  name: 'Dishwasher',
  kind: 'existing',
  device_id: 'dev1',
  notes: 'Salt every month',
  metadata: [],
  parts: [
    { id: 'p1', name: 'Filter', type: 'consumable', stock: 3, reorder_at: 1 },
  ],
  task_history: [
    {
      task_id: 'gone-task',
      task_name: 'Old task',
      completions: [{ ts: '2026-01-02T10:00:00+00:00' }],
    },
  ],
};

const ARCHIVED = { ...ASSET, id: 'a2', name: 'Old fridge', archived_at: '2026-02-01T00:00:00+00:00' };

const TASK = {
  id: 't1',
  name: 'Clean filter',
  recurrence_type: 'floating',
  interval: 1,
  unit: 'months',
  enabled: true,
  device_id: 'dev1',
  completions: [],
  next_due: '2027-01-01T00:00:00+00:00',
};

// A task that a companion owns, with an owner that is no longer loaded.
const ORPHAN = {
  ...TASK,
  id: 't2',
  name: 'Orphan task',
  device_id: undefined,
  managed_by: { integration: 'gone', display_name: 'Gone', config_entry_id: 'gone-entry' },
};

function makeHass({ admin, tasks = [TASK], assets = [ASSET, ARCHIVED] } = {}) {
  return {
    language: 'en',
    states: {},
    devices: { dev1: { id: 'dev1', name: 'Dishwasher' } },
    ...(admin === undefined ? {} : { user: { is_admin: admin } }),
    callWS(msg) {
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets });
        case 'home_keeper/get_options':
          return Promise.resolve({ options: {} });
        case 'config_entries/get':
          return Promise.resolve([]);
        case 'frontend/get_user_data':
          return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
        default:
          return Promise.resolve({});
      }
    },
  };
}

/** Boot a panel on *path* and wait until *selector* paints. */
async function mount(path, hass, selector) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  panel.hass = hass;
  const el = await waitFor(() => panel.shadowRoot?.querySelector(selector), 5000);
  expect(el, `${selector} should paint on ${path}`).toBeTruthy();
  return panel;
}

describe('read-only flag', () => {
  it('is on only if Home Assistant says that the user is not an admin', async () => {
    const ro = await mount('/', makeHass({ admin: false }), '#hk-list');
    expect(ro._readOnly()).toBe(true);
    const admin = await mount('/', makeHass({ admin: true }), '#hk-list');
    expect(admin._readOnly()).toBe(false);
    const unknown = await mount('/', makeHass({}), '#hk-list');
    expect(unknown._readOnly()).toBe(false);
  });
});

describe('Settings tab', () => {
  it('shows 1 admin-only card and no settings to a non-admin', async () => {
    const panel = await mount('/settings', makeHass({ admin: false }), '.hk-admin-only');
    const root = panel.shadowRoot;
    expect(root.querySelector('ha-tab-group')).toBeTruthy();
    expect(root.querySelector('.hk-admin-only .hk-form-title').textContent).toContain(
      'Settings are for admins only',
    );
    expect(root.querySelector('.hk-admin-only ha-icon').getAttribute('icon')).toBe('mdi:lock');
    const text = root.querySelector('.hk-admin-only').textContent;
    expect(text).toContain('Only a Home Assistant admin can see and change them.');
    expect(text).toContain('To change a setting, ask an admin.');
    for (const id of ['hk-settings-host', 'hk-profiles-host', 'hk-companions-host', 'hk-transfer-host']) {
      expect(root.getElementById(id)).toBeNull();
    }
  });

  it('shows the settings to an admin', async () => {
    const panel = await mount('/settings', makeHass({ admin: true }), '#hk-settings-host');
    expect(panel.shadowRoot.querySelector('.hk-admin-only')).toBeNull();
  });
});

describe('appliance list', () => {
  it('has no Add appliance and shows the view-only banner to a non-admin', async () => {
    const panel = await mount('/appliances', makeHass({ admin: false }), '.hk-view-only-banner');
    const root = panel.shadowRoot;
    expect(root.querySelector('#add-btn')).toBeNull();
    expect(root.querySelector('#labels-btn')).toBeTruthy();
    const banner = root.querySelector('.hk-view-only-banner');
    expect(banner.getAttribute('alert-type')).toBe('info');
    expect(banner.querySelector('b').textContent).toBe('View only.');
    expect(banner.querySelector('.hk-view-only-long').textContent).toBe(
      'Ask an admin to add or change appliances.',
    );
    expect(banner.querySelector('.hk-view-only-short').textContent).toBe(
      'Changes need an admin account.',
    );
  });

  it('keeps Add appliance and shows no banner to an admin', async () => {
    const panel = await mount('/appliances', makeHass({ admin: true }), '#add-btn');
    expect(panel.shadowRoot.querySelector('.hk-view-only-banner')).toBeNull();
  });

  it('opens no appliance form for a non-admin', async () => {
    const panel = await mount('/appliances', makeHass({ admin: false }), '.hk-view-only-banner');
    panel._openCreateAsset();
    expect(panel._assetEdit.open).toBe(false);
    panel._openEditAsset(ASSET);
    expect(panel._assetEdit.open).toBe(false);
  });
});

describe('task list', () => {
  it('keeps Add task for a non-admin', async () => {
    const panel = await mount('/', makeHass({ admin: false }), '#add-btn');
    expect(panel.shadowRoot.querySelector('#add-btn').textContent).toContain('Add task');
  });

  it('hides the orphan banner from a non-admin', async () => {
    const tasks = [TASK, ORPHAN];
    const ro = await mount('/', makeHass({ admin: false, tasks }), '#hk-list ha-card');
    expect(ro.shadowRoot.querySelector('.hk-orphan-banner')).toBeNull();
    const admin = await mount('/', makeHass({ admin: true, tasks }), '.hk-orphan-banner');
    expect(admin.shadowRoot.querySelector('#cleanup-orphans-btn')).toBeTruthy();
  });
});

describe('appliance page', () => {
  it('shows a non-admin the page with no write controls', async () => {
    const panel = await mount('/appliances/a1', makeHass({ admin: false }), '.hk-asset-head');
    const root = panel.shadowRoot;
    for (const sel of ['.d-edit', '.d-del', '.d-archive', '.d-restore', '.d-add-part', '.hk-part-edit']) {
      expect(root.querySelector(sel), sel).toBeNull();
    }
    const chip = root.querySelector('.hk-asset-head .hk-chips .hk-view-only');
    expect(chip.getAttribute('label')).toBe('View only');
    expect(chip.classList.contains('hk-archived')).toBe(true);
    // The stock shows as a chip, with no stepper.
    expect(root.querySelector('.hk-stock')).toBeNull();
    const labels = [...root.querySelectorAll('.hk-part-spares ha-assist-chip')].map((c) =>
      c.getAttribute('label'),
    );
    expect(labels.join(' ')).toContain('3');
    // The device page is admin-only, so the device chip is not a link.
    expect(root.querySelector('.hk-asset-head .hk-device-chip')).toBeNull();
    expect(root.querySelector('.hk-asset-head .hk-dev-plain').getAttribute('label')).toBe('Dishwasher');
  });

  it('shows an admin every control', async () => {
    const panel = await mount('/appliances/a1', makeHass({ admin: true }), '.hk-asset-head');
    const root = panel.shadowRoot;
    for (const sel of ['.d-edit', '.d-del', '.d-archive', '.d-add-part', '.hk-part-edit', '.hk-stock']) {
      expect(root.querySelector(sel), sel).toBeTruthy();
    }
    expect(root.querySelector('.hk-view-only')).toBeNull();
    expect(root.querySelector('.hk-asset-head .hk-device-chip')).toBeTruthy();
  });

  it('has no Restore on an archived appliance for a non-admin', async () => {
    const ro = await mount('/appliances/a2', makeHass({ admin: false }), '.hk-asset-head');
    expect(ro.shadowRoot.querySelector('.d-restore')).toBeNull();
    const admin = await mount('/appliances/a2', makeHass({ admin: true }), '.hk-asset-head');
    expect(admin.shadowRoot.querySelector('.d-restore')).toBeTruthy();
  });

  it('shows the notes with no Edit to a non-admin', async () => {
    const ro = await mount('/appliances/a1/details', makeHass({ admin: false }), '.hk-asset-head');
    expect(ro.shadowRoot.querySelector('.d-note-edit')).toBeNull();
    const admin = await mount('/appliances/a1/details', makeHass({ admin: true }), '.hk-asset-head');
    expect(admin.shadowRoot.querySelector('.d-note-edit')).toBeTruthy();
  });

  it('has no delete on archived history for a non-admin', async () => {
    const ro = await mount('/appliances/a1/history', makeHass({ admin: false }), '.hk-asset-head');
    expect(ro.shadowRoot.querySelector('.hk-hist-del[data-del-asset]')).toBeNull();
    const admin = await mount('/appliances/a1/history', makeHass({ admin: true }), '.hk-asset-head');
    expect(admin.shadowRoot.querySelector('.hk-hist-del[data-del-asset]')).toBeTruthy();
  });

  it('does not call an appliance write for a non-admin', async () => {
    const calls = [];
    const hass = makeHass({ admin: false });
    const base = hass.callWS;
    hass.callWS = (msg) => {
      calls.push(msg.type);
      return base(msg);
    };
    const panel = await mount('/appliances/a1', hass, '.hk-asset-head');
    await panel._archiveAsset(ASSET);
    await panel._restoreAsset(ARCHIVED);
    await panel._deleteAsset(ASSET);
    panel._assetEdit = { open: true, asset: { ...ASSET } };
    await panel._submitAssetForm();
    const writes = calls.filter((c) => /_(asset|assets)$/.test(c) && c !== 'home_keeper/get_assets');
    expect(writes).toEqual([]);
  });
});

describe('task page', () => {
  it('keeps the device chip a link to the appliance page for a non-admin', async () => {
    const panel = await mount('/tasks/t1', makeHass({ admin: false }), '.hk-detail-card');
    const chip = panel.shadowRoot.querySelector('.hk-device-chip');
    expect(chip.dataset.assetId).toBe('a1');
  });
});

// A task with a template sensor. A non-admin cannot save it: the form sends the
// template binding back, and the backend refuses that for a non-admin.
const TEMPLATE_TASK = {
  ...TASK,
  id: 't3',
  name: 'Check the leak sensor',
  recurrence_type: 'sensor',
  sensor: { mode: 'template', template: "{{ is_state('binary_sensor.leak', 'on') }}" },
  device_id: undefined,
  next_due: null,
};

const USAGE_TASK = {
  ...TEMPLATE_TASK,
  id: 't4',
  name: 'Change the water filter',
  sensor: { mode: 'usage', entity_id: 'sensor.water_used', threshold: 100 },
};

describe('task page buttons', () => {
  const tasks = [TASK, TEMPLATE_TASK, USAGE_TASK];

  it('has no Edit and no Duplicate on a template task for a non-admin', async () => {
    const panel = await mount('/tasks/t3', makeHass({ admin: false, tasks }), '.hk-detail-card');
    const root = panel.shadowRoot;
    expect(root.querySelector('.d-edit')).toBeNull();
    expect(root.querySelector('.d-dup')).toBeNull();
    expect(root.querySelector('.d-dup-blocked')).toBeNull();
  });

  it('keeps Edit and Duplicate on a template task for an admin', async () => {
    const panel = await mount('/tasks/t3', makeHass({ admin: true, tasks }), '.hk-detail-card');
    expect(panel.shadowRoot.querySelector('.d-edit')).not.toBeNull();
    expect(panel.shadowRoot.querySelector('.d-dup')).not.toBeNull();
  });

  it('keeps Edit and Duplicate on other sensor tasks for a non-admin', async () => {
    const panel = await mount('/tasks/t4', makeHass({ admin: false, tasks }), '.hk-detail-card');
    expect(panel.shadowRoot.querySelector('.d-edit')).not.toBeNull();
    expect(panel.shadowRoot.querySelector('.d-dup')).not.toBeNull();
  });
});

describe('companion tabs', () => {
  /** Record each websocket command that *hass* gets. */
  function recording(hass) {
    const calls = [];
    const callWS = hass.callWS.bind(hass);
    hass.callWS = (msg) => {
      calls.push(msg.type);
      return callWS(msg);
    };
    return calls;
  }

  it('does not ask a non-admin for the admin-only tab list', async () => {
    const hass = makeHass({ admin: false });
    const calls = recording(hass);
    await mount('/', hass, '#hk-list');
    expect(calls).toContain('home_keeper/get_tasks');
    expect(calls).not.toContain('home_keeper/get_panel_tabs');
  });

  it('asks an admin for the tab list', async () => {
    const hass = makeHass({ admin: true });
    const calls = recording(hass);
    await mount('/', hass, '#hk-list');
    expect(calls).toContain('home_keeper/get_panel_tabs');
  });
});

describe('task form', () => {
  const modes = (sections) =>
    sections
      .flatMap((s) => s.fields)
      .find((f) => f.name === 'sensor_mode')
      .selector.select.options.map((o) => o.value);

  it('offers the template mode only to an admin', () => {
    const task = { recurrence_type: 'sensor', sensor_mode: 'usage' };
    expect(modes(taskSchemaSections(task))).toContain('template');
    expect(modes(taskSchemaSections(task, [], [], [], { readOnly: true }))).toEqual([
      'usage',
      'threshold',
      'state',
      'availability',
    ]);
  });

  it('keeps the template mode on a task that has one', () => {
    const task = { recurrence_type: 'sensor', sensor_mode: 'template' };
    expect(modes(taskSchemaSections(task, [], [], [], { readOnly: true }))).toContain('template');
  });
});
