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
import {
  SPEND_ALL,
  showSpend,
  spendButton,
  spendRecordsFor,
  spendSheet,
  spendStrip,
  wireSpend,
} from '../src/panel-spend.ts';
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
    _spendSheet: false,
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

describe('spend edges', () => {
  it('a record at the start of a window is inside it', () => {
    const data = spend();
    data.records = [{ ...data.records[0], ts: data.windows[0].since }];
    expect(spendRecordsFor(data, 'w30')).toHaveLength(1);
  });

  it('shows with records and no priced appliance', () => {
    expect(showSpend(host({ _spend: spend({ purchases: { total: 0, count: 0 } }) }))).toBe(true);
  });

  it('names the heading, the help and who did it', () => {
    const data = spend();
    data.records = [{ ...data.records[0], who: 'person.kay' }];
    const p = host({ _spend: data, _spendOpen: SPEND_ALL });
    p._hass.states = { 'person.kay': { attributes: { friendly_name: 'Kay' } } };
    const div = document.createElement('div');
    div.innerHTML = spendStrip(p);
    expect(div.querySelector('section.hk-spend').getAttribute('aria-label')).toBe(
      'Maintenance spend',
    );
    expect(div.querySelector('.hk-spend-heading').textContent).toBe('Maintenance spend');
    expect(div.querySelector('.hk-spend-help').textContent).toContain('Select a total');
    expect(div.querySelector('.hk-spend-who').textContent).toBe('Kay');
    expect(div.querySelector('.hk-spend-tag')).toBeNull();
    expect(div.querySelectorAll('.hk-spend-list')).toHaveLength(1);
  });

  it('an archived record with no appliance opens its task', () => {
    const data = spend();
    data.records = [{ ...data.records[3], asset_id: null, task_id: 'gone' }];
    const div = document.createElement('div');
    div.innerHTML = spendStrip(host({ _spend: data, _spendOpen: SPEND_ALL }));
    expect(div.querySelector('.hk-spend-task').dataset.spendOpen).toBe('task:gone');
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
    const ev = new MouseEvent('click', { bubbles: true, cancelable: true });
    links[0].dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
    links[3].click();
    expect(p.navigated).toEqual([
      { view: 'tasks', detail: { kind: 'task', id: 't1', tab: 'history' } },
      { view: 'appliances', detail: { kind: 'asset', id: 'heater', tab: 'history' } },
    ]);
  });

  it('a link with no id goes nowhere', () => {
    const p = host({ _spendOpen: SPEND_ALL });
    const div = wired(p);
    const link = div.querySelector('[data-spend-open]');
    link.dataset.spendOpen = 'task:';
    link.click();
    link.removeAttribute('data-spend-open');
    expect(p.navigated).toEqual([]);
  });

  it('the purchases total opens the appliance list, and closes the sheet', () => {
    const p = host({ _spendSheet: true });
    wired(p).querySelector('[data-spend-purchases]').click();
    expect(p.navigated).toEqual([{ view: 'appliances', detail: null }]);
    expect(p._spendSheet).toBe(false);
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

describe('the strip kinds, the spend button and the sheet (#488)', () => {
  const html = (markup) => {
    const div = document.createElement('div');
    div.innerHTML = markup;
    return div;
  };

  it('the full strip has the help, the counts and its own records id', () => {
    const div = html(spendStrip(host({ _spendOpen: 'w30' })));
    const section = div.querySelector('section.hk-spend');
    expect(section.classList.contains('hk-spend-compact')).toBe(false);
    expect(div.querySelector('.hk-spend-help')).toBeTruthy();
    expect(div.querySelectorAll('.hk-spend-count')).toHaveLength(4);
    expect(div.querySelector('#hk-spend-records')).toBeTruthy();
    expect(div.querySelector('[data-spend="w30"]').getAttribute('aria-controls')).toBe(
      'hk-spend-records',
    );
  });

  it('the compact strip is a heading and label-value totals, with no stray text', () => {
    const div = html(spendStrip(host(), 'compact'));
    const section = div.querySelector('section.hk-spend.hk-spend-compact');
    expect(section).toBeTruthy();
    expect(div.querySelector('.hk-spend-help')).toBeNull();
    expect(div.querySelector('.hk-spend-heading').textContent).toBe('Maintenance spend');
    expect(div.querySelector('.hk-spend-count')).toBeNull();
    expect(div.querySelector('.hk-spend-records')).toBeNull();
    const words = (el) => el.textContent.replace(/\s+/g, ' ').trim();
    expect(words(div.querySelector('[data-spend="w30"]'))).toBe('Last 30 days $28.18');
    expect(words(div.querySelector('[data-spend-purchases]'))).toBe('Appliance purchases $2,100.50');
    expect(words(div.querySelector('.hk-spend-totals'))).toBe(
      'Last 30 days $28.18 Last 60 days $208.18 All time $258.18 Appliance purchases $2,100.50',
    );
    expect(words(section)).toBe(
      'Maintenance spend Last 30 days $28.18 Last 60 days $208.18 All time $258.18 Appliance purchases $2,100.50',
    );
  });

  it('the compact strip names its own records list', () => {
    const div = html(spendStrip(host({ _spendOpen: 'w30' }), 'compact'));
    expect(div.querySelector('#hk-spend-strip-records')).toBeTruthy();
    expect(div.querySelector('#hk-spend-records')).toBeNull();
  });

  it('the button and the sheet are empty with no data or a closed sheet', () => {
    expect(spendButton(host({ _spend: null }))).toBe('');
    expect(spendSheet(host({ _spendSheet: true, _spend: null }))).toBe('');
    expect(spendSheet(host())).toBe('');
  });

  it('the button reads with no hass', () => {
    const div = html(spendButton(host({ _hass: undefined })));
    expect(div.querySelector('.hk-spend-btn-text').textContent).toBe('28');
  });

  it('the sheet holds the full strip and a named Close', () => {
    const div = html(spendSheet(host({ _spendSheet: true })));
    const sheet = div.querySelector('.hk-spend-sheet');
    expect(sheet.querySelector('.hk-spend-help')).toBeTruthy();
    expect(sheet.querySelectorAll('.hk-spend-count')).toHaveLength(4);
    expect(sheet.querySelector('.hk-spend-sheet-close').getAttribute('aria-label')).toBe('Close');
    expect(div.querySelector('.hk-spend-scrim')).toBeTruthy();
  });
});
