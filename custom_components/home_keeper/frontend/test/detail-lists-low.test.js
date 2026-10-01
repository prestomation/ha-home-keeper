import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { definePanelStubs, makeHass, waitFor } from './panel-harness.js';
import { consumableLinkLabel } from '../src/panel-task-form.ts';
import { assetTitle } from '../src/utils.ts';

/**
 * Low findings on the appliance and task pages and in the lists: skip rows on the
 * appliance History tab, Delete on a buy reminder, the Related and History tab
 * counts, the meter note, the appliance sort, the tree toggle, the greyed Done from
 * the keyboard, and the linked-consumable row.
 */

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
  localStorage.clear();
  vi.restoreAllMocks();
});

const DEVICES = {
  dev1: { id: 'dev1', name: 'Washer' },
  dev2: { id: 'dev2', name: 'Dryer plug' },
  dev3: { id: 'dev3', name: 'Thermostat' },
};

function hassWith({ tasks = [], assets = [], states = {} } = {}) {
  const hass = makeHass({ tasks, assets });
  hass.devices = DEVICES;
  hass.states = states;
  return hass;
}

/** Boot the panel on *path* and wait for *selector* to render. */
async function boot(path, hass, selector) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  panel.hass = hass;
  const el = await waitFor(() => panel._loaded && panel.shadowRoot?.querySelector(selector));
  expect(el, `${selector} should render on ${path}`).toBeTruthy();
  return panel;
}

const q = (panel, sel) => panel.shadowRoot.querySelector(sel);
const qa = (panel, sel) => [...panel.shadowRoot.querySelectorAll(sel)];
const tabCount = (panel, tab) =>
  q(panel, `.hk-subtab[data-tab="${tab}"] .hk-subtab-count`)?.textContent ?? '';

const washer = { id: 'X', name: 'Washer', device_id: 'dev1', parts: [], documents: [] };
const skipped = {
  id: 'T1',
  name: 'Clean the filter',
  recurrence_type: 'floating',
  interval: 1,
  unit: 'months',
  enabled: true,
  device_id: 'dev1',
  completions: [],
  skips: [{ ts: '2026-09-01T10:00:00+00:00', note: 'Away' }],
};

describe('F07-1: skip rows on the appliance History tab', () => {
  it('get their icons and handlers', async () => {
    const panel = await boot(
      '/appliances/X/history',
      hassWith({ tasks: [skipped], assets: [washer] }),
      '.hk-hist-skip-del',
    );
    for (const cls of ['.hk-hist-skip-del', '.hk-hist-skip-edit', '.hk-hist-skip-move']) {
      const b = q(panel, cls);
      expect(b, `${cls} should render`).toBeTruthy();
      expect(b.path, `${cls} should have an icon`).toBeTruthy();
    }
    q(panel, '.hk-hist-skip-edit').click();
    expect(panel._skip.open).toBe(true);
    expect(panel._skip.ts).toBe('2026-09-01T10:00:00+00:00');
  });
});

describe('F07-8: the appliance History count', () => {
  it('counts entries, not related tasks', async () => {
    const quiet = { ...skipped, id: 'T2', name: 'Descale', skips: [] };
    const busy = {
      ...skipped,
      id: 'T3',
      name: 'Run a hot wash',
      skips: [],
      completions: [
        { ts: '2026-08-01T10:00:00+00:00' },
        { ts: '2026-07-01T10:00:00+00:00' },
        { ts: '2026-06-01T10:00:00+00:00' },
      ],
    };
    const panel = await boot(
      '/appliances/X',
      hassWith({ tasks: [skipped, quiet, busy], assets: [washer] }),
      '.hk-subtab[data-tab="history"]',
    );
    // 1 skip + 0 + 3 completions, where the old count gave 1 per task (3).
    expect(tabCount(panel, 'history')).toBe('4');
  });
});

describe('F07-4: the appliance Related tab', () => {
  it('lists the related devices it counts', async () => {
    const asset = { ...washer, related_device_ids: ['dev2', 'gone'] };
    const panel = await boot(
      '/appliances/X/related',
      hassWith({ assets: [asset] }),
      '.hk-subtab[data-tab="related"]',
    );
    // A device that left the registry has no chip, so it is not counted either.
    expect(tabCount(panel, 'related')).toBe('1');
    const body = q(panel, '.hk-subtab-body');
    expect(body.textContent).toContain('Related devices');
    const chip = body.querySelector('.hk-device-chip');
    expect(chip, 'the related device should show as a chip').toBeTruthy();
    expect(chip.getAttribute('label')).toContain('Dryer plug');
  });
});

describe('F07-2: Delete on an auto-created buy reminder', () => {
  it('is replaced by a caption that says how the reminder ends', async () => {
    const buy = {
      id: 'B1',
      name: 'Buy filter',
      recurrence_type: 'one-off',
      enabled: true,
      next_due: '2026-09-01T10:00:00+00:00',
      source: { buy: { asset_id: 'X', part_id: 'P1' } },
    };
    const panel = await boot('/tasks/B1', hassWith({ tasks: [buy], assets: [washer] }), '.d-edit');
    expect(q(panel, '.d-del')).toBeNull();
    const captions = qa(panel, '.hk-managed-info').map((e) => e.textContent);
    expect(captions).toContain(
      'To remove this reminder, restock the part or turn off its auto-buy option.',
    );
  });

  it('stays on an ordinary task', async () => {
    const panel = await boot('/tasks/T1', hassWith({ tasks: [skipped] }), '.d-edit');
    expect(q(panel, '.d-del')).toBeTruthy();
  });
});

describe('F07-9: the usage meter note', () => {
  it('reads 0 to go, not a negative number, past the target', async () => {
    const usage = {
      id: 'U1',
      name: 'Service the pump',
      recurrence_type: 'sensor',
      enabled: true,
      sensor: { entity_id: 'sensor.pump_hours', mode: 'usage', target: 300, unit: 'h', baseline: 1000 },
    };
    const panel = await boot(
      '/tasks/U1',
      hassWith({ tasks: [usage], states: { 'sensor.pump_hours': { state: '1350', attributes: {} } } }),
      '.hk-meter-note',
    );
    expect(q(panel, '.hk-meter-note').textContent).toBe('0 h to go');
    expect(q(panel, '.hk-meter').getAttribute('aria-label')).toBe('0 h to go');
  });

  it('puts the backstop unit in the singular for 1', async () => {
    const usage = {
      id: 'U2',
      name: 'Service the pump',
      recurrence_type: 'sensor',
      enabled: true,
      sensor: {
        entity_id: 'sensor.pump_hours',
        mode: 'usage',
        target: 300,
        also_every: { interval: 1, unit: 'months' },
      },
    };
    const panel = await boot('/tasks/U2', hassWith({ tasks: [usage] }), '.hk-meter-note');
    expect(q(panel, '.hk-meter-note').textContent).toContain('1 month');
    expect(q(panel, '.hk-meter-note').textContent).not.toContain('1 months');
  });
});

describe('F07-6: the appliance list order', () => {
  it('sorts on the title the row shows', async () => {
    const assets = [
      { id: 'a1', name: '', device_id: 'dev3', parts: [] },
      { id: 'a2', name: 'Boiler', parts: [] },
      { id: 'a3', name: '', device_id: 'dev1', parts: [] },
      { id: 'a4', name: 'Air purifier', parts: [] },
    ];
    const panel = await boot('/appliances', hassWith({ assets }), '#hk-list .hk-name');
    const names = qa(panel, '#hk-list .hk-name').map((e) => e.textContent);
    expect(names).toEqual(['Air purifier', 'Boiler', 'Thermostat', 'Washer']);
  });
});

describe('F07-10 and X11-4: the tree view toggle', () => {
  const tree = [
    { id: 'p', name: 'HVAC', parts: [] },
    { id: 'c', name: 'HVAC filter', parent_asset_id: 'p', parts: [] },
  ];

  it('is a labelled button that reports and toggles its state', async () => {
    localStorage.setItem('home-keeper.assetView', 'tree');
    const panel = await boot('/appliances', hassWith({ assets: tree }), '.hk-chevron');
    const ch = q(panel, '.hk-chevron');
    expect(ch.tagName).toBe('BUTTON');
    expect(ch.getAttribute('type')).toBe('button');
    expect(ch.getAttribute('aria-expanded')).toBe('true');
    expect(ch.getAttribute('aria-label')).toBe('Collapse HVAC');
    ch.click();
    expect(ch.closest('.hk-tree-group').classList.contains('hk-tree-open')).toBe(false);
    expect(ch.getAttribute('aria-expanded')).toBe('false');
    expect(ch.getAttribute('aria-label')).toBe('Expand HVAC');
    expect(JSON.parse(localStorage.getItem('home-keeper.treeCollapsed'))).toEqual(['p']);
  });

  it('opens a collapsed group while a search runs', async () => {
    localStorage.setItem('home-keeper.assetView', 'tree');
    localStorage.setItem('home-keeper.treeCollapsed', JSON.stringify(['p']));
    const panel = await boot('/appliances', hassWith({ assets: tree }), '.hk-chevron');
    expect(q(panel, '.hk-tree-group').classList.contains('hk-tree-open')).toBe(false);
    expect(q(panel, '.hk-chevron').getAttribute('aria-expanded')).toBe('false');
    panel._query = 'hvac';
    panel._render();
    expect(q(panel, '.hk-tree-group').classList.contains('hk-tree-open')).toBe(true);
    expect(q(panel, '.hk-chevron').getAttribute('aria-expanded')).toBe('true');
    // The saved choice is not changed by the search.
    expect(panel._treeCollapsed.has('p')).toBe(true);
  });
});

describe('F07-7: a greyed Done answers the keyboard', () => {
  const locked = {
    ...skipped,
    skips: [],
    tag_id: 'tag-1',
    require_tag_scan: true,
  };

  it('on a list row', async () => {
    const panel = await boot('/tasks', hassWith({ tasks: [locked] }), '.done-blocked-wrap');
    const spy = vi.spyOn(panel, '_notifyBlocked').mockImplementation(() => {});
    const wrap = q(panel, '.done-blocked-wrap');
    for (const key of ['Enter', ' ']) {
      const ev = new KeyboardEvent('keydown', { key, cancelable: true });
      wrap.dispatchEvent(ev);
      expect(ev.defaultPrevented).toBe(true);
    }
    wrap.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }));
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy.mock.calls[0][0].id).toBe('T1');
  });

  it('on the task page', async () => {
    const panel = await boot('/tasks/T1', hassWith({ tasks: [locked] }), '.d-done-blocked-wrap');
    const spy = vi.spyOn(panel, '_notifyBlocked').mockImplementation(() => {});
    q(panel, '.d-done-blocked-wrap').dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Enter', cancelable: true }),
    );
    expect(spy).toHaveBeenCalledTimes(1);
  });
});

describe('F07-11: the linked consumable row', () => {
  it('names a blank-named appliance by its device', () => {
    const asset = {
      id: 'X',
      name: '',
      device_id: 'dev1',
      parts: [{ id: 'P1', name: 'Rinse aid', stock: 3 }],
    };
    const p = {
      _assets: [asset],
      _hass: { devices: DEVICES },
      _hrefFor: () => '/home-keeper/appliances/X/parts/P1',
    };
    const task = { id: 'T', source: { part: { asset_id: 'X', part_id: 'P1', manual: true } } };
    const html = consumableLinkLabel(p, task);
    expect(html).toContain('>Washer</a>');
    expect(assetTitle({ name: '', device_id: 'nope' }, DEVICES)).toBe('Appliance');
    expect(assetTitle({ name: 'Mine', device_id: 'dev1' }, DEVICES)).toBe('Mine');
  });
});
