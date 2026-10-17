/**
 * The spend totals above the task list, and the Cost tracking settings (#460).
 *
 * The windows are cleaned the way the backend cleans them, the strip shows only
 * when there is something to show, a total opens the records of its window, and a
 * record opens the history of its task or, for a deleted task, of its appliance.
 */

import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import {
  coerceCost,
  costSchema,
  costWindows,
  normalizeCostWindows,
} from '../src/forms.ts';
import { SPEND_ALL, showSpend, spendRecordsFor, spendStrip, wireSpend } from '../src/panel-spend.ts';
import { definePanelStubs, makeHass, mountPanel, waitFor } from './panel-harness.js';

const NOW = Date.parse('2026-10-17T12:00:00Z');
const ago = (days) => new Date(NOW - days * 86400000).toISOString();

function spend(overrides = {}) {
  return {
    windows: [
      { days: 30, total: 28.18, count: 2, since: ago(30) },
      { days: 60, total: 208.18, count: 3, since: ago(60) },
    ],
    all_time: { total: 258.18, count: 4, first: ago(400) },
    purchases: { total: 2100.5, count: 2 },
    records: [
      { ts: ago(5), cost: 3.19, who: null, task_id: 't1', task_name: 'Fix <shower>', asset_id: null, archived: false },
      { ts: ago(19), cost: 24.99, who: null, task_id: 't2', task_name: 'HVAC filter', asset_id: null, archived: false },
      { ts: ago(48), cost: 180, who: null, task_id: 't3', task_name: 'Gutters', asset_id: null, archived: false },
      { ts: ago(400), cost: 50, who: null, task_id: 'gone', task_name: '', asset_id: 'heater', archived: true },
    ],
    ...overrides,
  };
}

function host(overrides = {}) {
  const navigated = [];
  let renders = 0;
  return {
    _hass: { language: 'en', config: { currency: 'USD' }, states: {} },
    _options: {},
    _spend: spend(),
    _spendOpen: '',
    _lang: () => 'en',
    _navigate: (loc) => navigated.push(loc),
    _render: () => {
      renders += 1;
    },
    navigated,
    renders: () => renders,
    ...overrides,
  };
}

describe('normalizeCostWindows', () => {
  it.each([
    [[60, 30], [30, 60]],
    [[30, '30', 30.9], [30]],
    [['7', 90], [7, 90]],
    [[0, -1, 3651, 'x', null, 5], [5]],
    [[1, 3650], [1, 3650]],
    [[5, 4, 3, 2, 1], [1, 2, 3, 4]],
    [[], [30, 60]],
    [['bad'], [30, 60]],
    [undefined, [30, 60]],
    ['30', [30, 60]],
    [[Infinity], [30, 60]],
  ])('%j gives %j', (value, expected) => {
    expect(normalizeCostWindows(value)).toEqual(expected);
  });

  it('reads the windows of an options object', () => {
    expect(costWindows(null)).toEqual([30, 60]);
    expect(costWindows({})).toEqual([30, 60]);
    expect(costWindows({ cost_windows: [90, 7] })).toEqual([7, 90]);
  });
});

describe('the Cost tracking form', () => {
  it('has the windows picker and the panel switch', () => {
    const [windows, panel] = costSchema();
    expect(windows.name).toBe('cost_windows');
    expect(windows.selector.select).toMatchObject({ multiple: true, custom_value: true, sort: false });
    expect(windows.selector.select.options.map((o) => o.value)).toEqual([
      '7', '14', '30', '60', '90', '180', '365',
    ]);
    expect(panel).toEqual({ name: 'cost_summary_panel', selector: { boolean: {} } });
  });

  it('saves numbers, and the switch on unless it is off', () => {
    expect(coerceCost({ cost_windows: ['60', '7'], cost_summary_panel: false })).toEqual({
      cost_windows: [7, 60],
      cost_summary_panel: false,
    });
    expect(coerceCost({ cost_windows: [] })).toEqual({
      cost_windows: [30, 60],
      cost_summary_panel: true,
    });
  });
});

describe('spendRecordsFor', () => {
  it('gives the records inside a window', () => {
    expect(spendRecordsFor(spend(), 'w30').map((r) => r.task_id)).toEqual(['t1', 't2']);
    expect(spendRecordsFor(spend(), 'w60').map((r) => r.task_id)).toEqual(['t1', 't2', 't3']);
  });

  it('gives every record for all time, and none for an unknown key', () => {
    expect(spendRecordsFor(spend(), SPEND_ALL)).toHaveLength(4);
    expect(spendRecordsFor(spend(), 'w7')).toEqual([]);
    expect(spendRecordsFor(spend(), '')).toEqual([]);
  });
});

describe('showSpend', () => {
  it('shows with records or with a priced appliance', () => {
    expect(showSpend(host())).toBe(true);
    expect(showSpend(host({ _spend: spend({ records: [] }) }))).toBe(true);
    expect(
      showSpend(host({ _spend: spend({ records: [], purchases: { total: 0, count: 0 } }) })),
    ).toBe(false);
  });

  it('hides with no data or when the option is off', () => {
    expect(showSpend(host({ _spend: null }))).toBe(false);
    expect(showSpend(host({ _options: { cost_summary_panel: false } }))).toBe(false);
    expect(showSpend(host({ _options: null }))).toBe(true);
  });
});

describe('spendStrip', () => {
  it('renders 1 total per window, all time and the purchases', () => {
    const html = spendStrip(host());
    const div = document.createElement('div');
    div.innerHTML = html;
    const totals = [...div.querySelectorAll('.hk-spend-total')];
    expect(totals.map((b) => b.querySelector('.hk-spend-label').textContent)).toEqual([
      'Last 30 days',
      'Last 60 days',
      'All time',
      'Appliance purchases',
    ]);
    expect(totals.map((b) => b.querySelector('.hk-spend-value').textContent)).toEqual([
      '$28.18',
      '$208.18',
      '$258.18',
      '$2,100.50',
    ]);
    expect(totals[0].querySelector('.hk-spend-count').textContent).toBe('2 records');
    expect(totals[3].querySelector('.hk-spend-count').textContent).toBe('2 appliances');
    expect(totals[0].getAttribute('aria-pressed')).toBe('false');
    expect(div.querySelector('#hk-spend-records')).toBeNull();
  });

  it('is empty when there is nothing to show', () => {
    expect(spendStrip(host({ _spend: null }))).toBe('');
  });

  it('lists the records of the open total, escaped', () => {
    const div = document.createElement('div');
    div.innerHTML = spendStrip(host({ _spendOpen: 'w30' }));
    const pressed = div.querySelector('[aria-pressed="true"]');
    expect(pressed.dataset.spend).toBe('w30');
    expect(pressed.classList.contains('open')).toBe(true);
    expect(div.querySelector('.hk-spend-records-head').textContent).toBe('Last 30 days');
    const rows = [...div.querySelectorAll('.hk-spend-row')];
    expect(rows).toHaveLength(2);
    expect(rows[0].querySelector('.hk-spend-task').textContent).toBe('Fix <shower>');
    expect(rows[0].querySelector('.hk-spend-cost').textContent).toBe('$3.19');
    expect(div.innerHTML).not.toContain('<shower>');
  });

  it('names a deleted task and points at its appliance', () => {
    const div = document.createElement('div');
    div.innerHTML = spendStrip(host({ _spendOpen: SPEND_ALL }));
    const last = [...div.querySelectorAll('.hk-spend-row')].at(-1);
    expect(last.querySelector('.hk-spend-task').textContent).toBe('Unnamed task');
    expect(last.querySelector('.hk-spend-task').dataset.spendOpen).toBe('asset:heater');
    expect(last.querySelector('.hk-spend-tag').textContent).toBe('Deleted task');
  });

  it('says so when the open window has no records', () => {
    const div = document.createElement('div');
    div.innerHTML = spendStrip(
      host({ _spend: spend({ records: [spend().records[3]] }), _spendOpen: 'w30' }),
    );
    expect(div.querySelector('.hk-spend-empty').textContent).toBe(
      'No records with a cost in this period.',
    );
  });
});

describe('wireSpend', () => {
  function wired(p) {
    const div = document.createElement('div');
    div.innerHTML = spendStrip(p);
    wireSpend(p, div);
    return div;
  }

  it('a total opens, and a second press closes', () => {
    const p = host();
    wired(p).querySelector('[data-spend="w60"]').click();
    expect(p._spendOpen).toBe('w60');
    expect(p.renders()).toBe(1);
    wired(p).querySelector('[data-spend="w60"]').click();
    expect(p._spendOpen).toBe('');
  });

  it('a record opens the task history, or the appliance history', () => {
    const p = host({ _spendOpen: SPEND_ALL });
    const links = [...wired(p).querySelectorAll('[data-spend-open]')];
    links[0].click();
    links[3].click();
    expect(p.navigated).toEqual([
      { view: 'tasks', detail: { kind: 'task', id: 't1', tab: 'history' } },
      { view: 'appliances', detail: { kind: 'asset', id: 'heater', tab: 'history' } },
    ]);
  });

  it('the purchases total opens the appliance list', () => {
    const p = host();
    wired(p).querySelector('[data-spend-purchases]').click();
    expect(p.navigated).toEqual([{ view: 'appliances', detail: null }]);
  });
});

describe('the strip in the panel', () => {
  beforeAll(definePanelStubs);
  afterEach(() => {
    document.body.innerHTML = '';
  });

  function hassWithSpend(data) {
    const hass = makeHass({ tasks: [{ id: 't1', name: 'Fix shower', completions: [] }] });
    const callWS = hass.callWS;
    hass.callWS = (msg) =>
      msg.type === 'home_keeper/get_spend' ? Promise.resolve(data) : callWS(msg);
    return hass;
  }

  it('shows above the task list and opens a total', async () => {
    const { panel } = await mountPanel('/tasks', hassWithSpend(spend()));
    const button = await waitFor(() => panel.shadowRoot.querySelector('[data-spend="w30"]'));
    expect(button).toBeTruthy();
    button.click();
    const rows = await waitFor(() => {
      const found = panel.shadowRoot.querySelectorAll('.hk-spend-row');
      return found.length ? found : null;
    });
    expect(rows).toHaveLength(2);
  });

  it('shows no strip for an answer with no data', async () => {
    const { panel } = await mountPanel('/tasks', hassWithSpend({}));
    expect(panel.shadowRoot.querySelector('.hk-spend')).toBeNull();
  });
});
