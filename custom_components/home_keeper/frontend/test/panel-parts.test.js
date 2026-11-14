/**
 * The Parts mode of the Appliances tab (#547): one list of every part of every
 * appliance, at `/appliances/parts`.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

beforeAll(() => {
  definePanelStubs();
});

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const FURNACE = {
  id: 'a1',
  name: 'Furnace',
  kind: 'existing',
  metadata: [],
  parts: [
    {
      id: 'p1',
      name: 'Filter 16x25',
      type: 'wear',
      part_number: 'MERV 11',
      vendor: 'Home Depot',
      stock: 1,
      reorder_at: 2,
      replace_interval: 3,
      replace_unit: 'months',
    },
    { id: 'p2', name: 'Pilot light', type: 'consumable', stock: 5, reorder_at: 1 },
    { id: 'p3', name: 'Gasket', type: 'wear', stock: null },
  ],
};
const FRIDGE = {
  id: 'a2',
  name: 'Fridge',
  kind: 'existing',
  metadata: [],
  parts: [{ id: 'p4', name: 'Water filter', type: 'wear', stock: 3, reorder_at: 1 }],
};
const OLD = {
  id: 'a3',
  name: 'Old oven',
  kind: 'existing',
  metadata: [],
  archived_at: '2026-02-01T00:00:00+00:00',
  parts: [{ id: 'p5', name: 'Oven bulb', type: 'consumable', stock: 2, reorder_at: 1 }],
};
const POOL = {
  id: 'a4',
  name: 'Battery pool',
  kind: 'existing',
  metadata: [],
  managed_by: { integration: 'bat', display_name: 'Battery notes', locked_fields: ['name'] },
  parts: [{ id: 'p6', name: 'AA battery', type: 'consumable', stock: 12, reorder_at: 6 }],
};
const BUY = {
  id: 't9',
  name: 'Buy Filter 16x25',
  recurrence_type: 'one-off',
  enabled: true,
  completions: [],
  source: { buy: { asset_id: 'a1', part_id: 'p1' } },
};
const REPLACE = {
  id: 't8',
  name: 'Replace Filter 16x25',
  recurrence_type: 'floating',
  interval: 3,
  unit: 'months',
  enabled: true,
  completions: [],
  next_due: '2099-01-01T00:00:00+00:00',
  source: { part: { asset_id: 'a1', part_id: 'p1', role: 'replace' } },
};

function makeHass({ admin, tasks = [BUY, REPLACE], assets = [FURNACE, FRIDGE, OLD, POOL], calls = [] } = {}) {
  return {
    language: 'en',
    states: {},
    devices: {},
    ...(admin === undefined ? {} : { user: { is_admin: admin } }),
    callWS(msg) {
      calls.push(msg);
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
        case 'home_keeper/adjust_part_stock':
          return Promise.resolve({ asset: { ...FURNACE, parts: [{ ...FURNACE.parts[0], stock: 2 }] } });
        default:
          return Promise.resolve({});
      }
    },
  };
}

async function mount(path, hass, selector = '.hk-parts-view') {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  panel.hass = hass;
  const el = await waitFor(() => panel.shadowRoot?.querySelector(selector), 5000);
  expect(el, `${selector} should paint on ${path}`).toBeTruthy();
  return panel;
}

const names = (panel) =>
  [...panel.shadowRoot.querySelectorAll('.hk-pt-row .hk-pt-name')].map((a) => a.textContent);

describe('Parts mode', () => {
  it('lists every part of every active appliance, grouped by appliance', async () => {
    const panel = await mount('/appliances/parts', makeHass({ admin: true }));
    const root = panel.shadowRoot;
    expect(panel._view).toBe('appliances');
    expect(panel._partsView).toBe(true);
    expect(root.querySelector('#tab-appliances')?.hasAttribute('active')).toBe(true);
    expect([...root.querySelectorAll('.hk-pt-group-title')].map((h) => h.textContent)).toEqual([
      'Battery pool',
      'Fridge',
      'Furnace',
    ]);
    expect(names(panel)).toEqual([
      'AA battery',
      'Water filter',
      'Filter 16x25',
      'Gasket',
      'Pilot light',
    ]);
  });

  it('hides the parts of archived appliances until the Archived scope is on', async () => {
    const panel = await mount('/appliances/parts', makeHass({ admin: true }));
    expect(names(panel)).not.toContain('Oven bulb');
    panel._setAssetFilter('archived');
    await waitFor(() => names(panel).includes('Oven bulb'));
    expect(names(panel)).toEqual(['Oven bulb']);
  });

  it('shows the parts of an integration-owned appliance, with a working stepper', async () => {
    const panel = await mount('/appliances/parts', makeHass({ admin: true }));
    const row = panel.shadowRoot.querySelector('[data-part-row="p6"]');
    expect(row).toBeTruthy();
    expect(row.querySelector('.hk-stock[data-part="p6"]')).toBeTruthy();
  });

  it('has the Appliances | Parts switch, no Add button and no Print labels', async () => {
    const panel = await mount('/appliances/parts', makeHass({ admin: true }));
    const root = panel.shadowRoot;
    const buttons = [...root.querySelectorAll('.hk-mode .hk-seg-btn')];
    expect(buttons.map((b) => b.textContent)).toEqual(['Appliances', 'Parts']);
    expect(buttons.map((b) => b.getAttribute('aria-pressed'))).toEqual(['false', 'true']);
    expect(root.querySelector('#add-btn')).toBeNull();
    expect(root.querySelector('#labels-btn')).toBeNull();
  });

  it('shows the switch on the appliance list too, with Appliances pressed', async () => {
    const panel = await mount('/appliances', makeHass({ admin: true }), '.hk-mode');
    const buttons = [...panel.shadowRoot.querySelectorAll('.hk-mode .hk-seg-btn')];
    expect(buttons.map((b) => b.getAttribute('aria-pressed'))).toEqual(['true', 'false']);
    expect(panel.shadowRoot.querySelector('.hk-parts-view')).toBeNull();
  });

  it('keeps /appliances/<id> working', async () => {
    const panel = await mount('/appliances/a1', makeHass({ admin: true }), '.hk-detail-pane');
    expect(panel._partsView).toBe(false);
    expect(panel._detail?.id).toBe('a1');
  });

  it('marks a low part, and links its Buy task only if one exists', async () => {
    const panel = await mount('/appliances/parts', makeHass({ admin: true }));
    const root = panel.shadowRoot;
    const low = root.querySelector('[data-part-row="p1"]');
    expect(low.classList.contains('low')).toBe(true);
    expect(low.querySelector('.hk-pt-status ha-assist-chip').getAttribute('label')).toBe('Low stock');
    const buy = low.querySelector('a.hk-pt-buy');
    expect(buy?.getAttribute('data-open-task')).toBe('t9');
    expect(root.querySelectorAll('a.hk-pt-buy')).toHaveLength(1);
    const ok = root.querySelector('[data-part-row="p2"]');
    expect(ok.classList.contains('low')).toBe(false);
    expect(ok.querySelector('.hk-pt-status ha-assist-chip').getAttribute('label')).toBe('In stock');
  });

  it('shows no Buy link on a low part without a Buy task', async () => {
    const panel = await mount('/appliances/parts', makeHass({ admin: true, tasks: [REPLACE] }));
    expect(panel.shadowRoot.querySelector('[data-part-row="p1"]').classList.contains('low')).toBe(true);
    expect(panel.shadowRoot.querySelector('a.hk-pt-buy')).toBeNull();
  });

  it('says Not counted for a part with no stock, and shows its due date', async () => {
    const panel = await mount('/appliances/parts', makeHass({ admin: true }));
    const root = panel.shadowRoot;
    const gasket = root.querySelector('[data-part-row="p3"]');
    expect(gasket.querySelector('.hk-stock')).toBeNull();
    expect(gasket.querySelector('.hk-pt-status ha-assist-chip').getAttribute('label')).toBe('Not counted');
    expect(root.querySelector('[data-part-row="p1"] .hk-pt-next').textContent.trim()).not.toBe('–');
  });

  it('filters by chip, with counts, and remembers the chip in this browser', async () => {
    const panel = await mount('/appliances/parts', makeHass({ admin: true }));
    const chip = (v) => panel.shadowRoot.querySelector(`.hk-pt-filters [data-seg-val="${v}"]`);
    expect(chip('all').textContent).toBe('All5');
    expect(chip('low').textContent).toBe('Low stock1');
    expect(chip('wear').textContent).toBe('Wear items3');
    expect(chip('uncounted').textContent).toBe('Not counted1');
    chip('low').click();
    await waitFor(() => names(panel).length === 1);
    expect(names(panel)).toEqual(['Filter 16x25']);
    expect(localStorage.getItem('home-keeper.partsFilter')).toBe('low');
  });

  it('searches name, part number and vendor, and the counts follow the search', async () => {
    const panel = await mount('/appliances/parts', makeHass({ admin: true }));
    panel._setQuery('depot');
    await waitFor(() => names(panel).length === 1);
    expect(names(panel)).toEqual(['Filter 16x25']);
    expect(panel.shadowRoot.querySelector('.hk-pt-filters [data-seg-val="all"]').textContent).toBe('All1');
    panel._setQuery('merv');
    await waitFor(() => names(panel).length === 1);
    panel._setQuery('zzz');
    await waitFor(() => !panel.shadowRoot.querySelector('.hk-pt-row'));
    expect(panel.shadowRoot.querySelector('ha-alert')?.textContent).toContain('No parts match');
  });

  it('groups by type and sorts by stock, and remembers both', async () => {
    const panel = await mount('/appliances/parts', makeHass({ admin: true }));
    panel._setPartsGroup('type');
    await waitFor(() => panel.shadowRoot.querySelector('.hk-pt-by-type'));
    expect([...panel.shadowRoot.querySelectorAll('.hk-pt-group-title')].map((h) => h.textContent)).toEqual([
      'wear item',
      'consumable',
    ]);
    panel._setPartsSort('stock');
    await waitFor(() => names(panel)[0] === 'Filter 16x25');
    expect(names(panel)).toEqual(['Filter 16x25', 'Water filter', 'Gasket', 'Pilot light', 'AA battery']);
    expect(localStorage.getItem('home-keeper.partsGroup')).toBe('type');
    expect(localStorage.getItem('home-keeper.partsSort')).toBe('stock');
  });

  it('reads stored choices on load, and ignores an unknown value', async () => {
    localStorage.setItem('home-keeper.partsFilter', 'wear');
    localStorage.setItem('home-keeper.partsGroup', 'nope');
    const panel = await mount('/appliances/parts', makeHass({ admin: true }));
    expect(panel._partsFilter).toBe('wear');
    expect(panel._partsGroup).toBe('appliance');
    expect(names(panel)).not.toContain('Pilot light');
  });

  it('changes stock through adjust_part_stock', async () => {
    const calls = [];
    const panel = await mount('/appliances/parts', makeHass({ admin: true, calls }));
    const inc = panel.shadowRoot.querySelector('[data-part-row="p1"] .hk-stock-inc');
    inc.click();
    await waitFor(() => calls.some((c) => c.type === 'home_keeper/adjust_part_stock'));
    const call = calls.find((c) => c.type === 'home_keeper/adjust_part_stock');
    expect(call).toMatchObject({ asset_id: 'a1', part_id: 'p1', delta: 1 });
  });

  it('is read only for a non-admin: banner, text stock, no stepper', async () => {
    const panel = await mount('/appliances/parts', makeHass({ admin: false }));
    const root = panel.shadowRoot;
    expect(root.querySelector('.hk-view-only-banner')).toBeTruthy();
    expect(root.querySelector('.hk-stock')).toBeNull();
    expect(root.querySelector('[data-part-row="p1"] .hk-pt-stock ha-assist-chip').getAttribute('label')).toBe(
      'In stock: 1',
    );
    expect(names(panel)).toHaveLength(5);
  });

  it('says so when there are no parts at all', async () => {
    const panel = await mount('/appliances/parts', makeHass({ admin: true, assets: [OLD] }), 'ha-alert');
    expect(panel.shadowRoot.querySelector('.hk-parts-view')).toBeNull();
    expect(panel.shadowRoot.querySelector('ha-alert').textContent).toContain('No parts yet');
  });
});

describe('mode switch and memory', () => {
  it('moves to the URL of the mode, replacing the entry', async () => {
    const panel = await mount('/appliances', makeHass({ admin: true }), '.hk-mode');
    panel._setAssetMode('parts');
    expect(location.pathname).toBe('/home-keeper/appliances/parts');
    // Home Assistant's router hands the new path back to the panel.
    panel.route = { prefix: '/home-keeper', path: '/appliances/parts' };
    await waitFor(() => panel._partsView);
    panel._setAssetMode('appliances');
    expect(location.pathname).toBe('/home-keeper/appliances');
  });

  it('remembers the last mode and opens the tab in it', async () => {
    const panel = await mount('/appliances/parts', makeHass({ admin: true }));
    expect(localStorage.getItem('home-keeper.assetMode')).toBe('parts');
    panel._navigate({ view: 'tasks', detail: null }, true);
    panel.route = { prefix: '/home-keeper', path: '/tasks' };
    await waitFor(() => panel._view === 'tasks');
    panel.shadowRoot.getElementById('tab-appliances').click();
    expect(location.pathname).toBe('/home-keeper/appliances/parts');
  });

  it('keeps an explicit /appliances URL on the list, and stores that mode', async () => {
    localStorage.setItem('home-keeper.assetMode', 'parts');
    const panel = await mount('/appliances', makeHass({ admin: true }), '.hk-mode');
    expect(panel._partsView).toBe(false);
    expect(localStorage.getItem('home-keeper.assetMode')).toBe('appliances');
  });
});
