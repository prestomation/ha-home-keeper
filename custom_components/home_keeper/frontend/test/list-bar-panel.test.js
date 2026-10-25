/**
 * The task list bar in the panel (#488): the Filters button and the fold it
 * remembers, the chips of the active filters, the spend button and its sheet, and
 * the compact spend strip above the list.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { definePanelStubs, makeHass, mountPanel, waitFor } from './panel-harness.js';

const NOW = Date.now();
const ago = (days) => new Date(NOW - days * 86400000).toISOString();

const SPEND = {
  windows: [
    { days: 30, total: 28.18, count: 2, since: ago(30) },
    { days: 60, total: 208.18, count: 3, since: ago(60) },
  ],
  all_time: { total: 258.18, count: 3, first: ago(400) },
  purchases: { total: 2100.5, count: 2 },
  records: [
    { ts: ago(5), cost: 3.19, who: null, task_id: 't1', task_name: 'Fix shower', asset_id: null, archived: false },
    { ts: ago(19), cost: 24.99, who: null, task_id: 't1', task_name: 'Fix shower', asset_id: null, archived: false },
    { ts: ago(48), cost: 180, who: null, task_id: 't1', task_name: 'Fix shower', asset_id: null, archived: false },
  ],
};

const TASKS = [
  { id: 't1', name: 'Fix shower', completions: [], next_due: ago(3), recurrence_type: 'interval' },
  { id: 't2', name: 'Clean gutters', completions: [], next_due: ago(-40), recurrence_type: 'interval' },
];

function hass({ spend = SPEND, profiles = [] } = {}) {
  const h = makeHass({ tasks: TASKS });
  h.config = { currency: 'USD' };
  const callWS = h.callWS;
  h.callWS = (msg) => {
    if (msg.type === 'home_keeper/get_spend') return Promise.resolve(spend);
    if (msg.type === 'home_keeper/get_options') return Promise.resolve({ options: { profiles } });
    return callWS(msg);
  };
  return h;
}

const $ = (panel, sel) => panel.shadowRoot.querySelector(sel);

beforeAll(definePanelStubs);
beforeEach(() => localStorage.clear());
afterEach(() => {
  document.body.innerHTML = '';
  localStorage.clear();
});

describe('the Filters button', () => {
  it('starts folded, and names the controls that it shows', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    const btn = $(panel, '#hk-filters-btn');
    expect(btn.getAttribute('aria-expanded')).toBe('false');
    expect(btn.getAttribute('aria-controls')).toBe('hk-list-controls');
    expect(btn.textContent).toContain('Filters');
    const controls = $(panel, '#hk-list-controls');
    expect(controls.hasAttribute('data-open')).toBe(false);
    expect(controls.querySelector('.hk-seg[data-seg="filter"]')).toBeTruthy();
    // Search and Add stay in the bar, outside the fold.
    expect($(panel, '.hk-listbar .hk-search-input')).toBeTruthy();
    expect($(panel, '.hk-listbar #add-btn')).toBeTruthy();
    expect(controls.querySelector('#labels-btn')).toBeTruthy();
  });

  it('opens and folds, and stores the choice per browser', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    $(panel, '#hk-filters-btn').click();
    expect($(panel, '#hk-list-controls').hasAttribute('data-open')).toBe(true);
    expect($(panel, '#hk-filters-btn').getAttribute('aria-expanded')).toBe('true');
    expect(localStorage.getItem('home-keeper.controls')).toBe('open');
    expect(panel.shadowRoot.activeElement?.id).toBe('hk-filters-btn');
    $(panel, '#hk-filters-btn').click();
    expect($(panel, '#hk-list-controls').hasAttribute('data-open')).toBe(false);
    expect(localStorage.getItem('home-keeper.controls')).toBe('folded');
  });

  it('opens on load when the stored choice is open', async () => {
    localStorage.setItem('home-keeper.controls', 'open');
    const { panel } = await mountPanel('/tasks', hass());
    expect($(panel, '#hk-list-controls').hasAttribute('data-open')).toBe(true);
  });

  it('while the bar is pinned, opens the controls and goes back to them', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    panel._barStuck = true;
    $(panel, '#hk-filters-btn').click();
    expect($(panel, '#hk-list-controls').hasAttribute('data-open')).toBe(true);
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(scroll.mock.contexts[0].classList.contains('hk-listbar-sentinel')).toBe(true);
    // Pinned again, a second press does not fold the controls the reader went back to.
    panel._barStuck = true;
    $(panel, '#hk-filters-btn').click();
    expect($(panel, '#hk-list-controls').hasAttribute('data-open')).toBe(true);
    delete Element.prototype.scrollIntoView;
  });

  it('marks a pinned bar for the stylesheet', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    panel._barStuck = true;
    panel._render();
    expect($(panel, '.hk-listbar').hasAttribute('data-stuck')).toBe(true);
    expect($(panel, '.hk-listbar-sentinel').getAttribute('aria-hidden')).toBe('true');
  });
});

describe('the active-filter chips', () => {
  it('show nothing and no count for the whole list', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    expect(panel.shadowRoot.querySelectorAll('.hk-filter-chip')).toHaveLength(0);
    expect($(panel, '.hk-filters-badge')).toBeNull();
    expect($(panel, '#hk-filters-btn').hasAttribute('aria-label')).toBe(false);
    expect($(panel, '.hk-active-filters').getAttribute('aria-label')).toBe('Active filters');
  });

  it('name the scope pill, count it on the button, and clear it', async () => {
    localStorage.setItem('home-keeper.filter', 'overdue');
    const { panel } = await mountPanel('/tasks', hass());
    const chip = $(panel, '.hk-filter-chip');
    expect(chip.querySelector('.hk-filter-chip-text').textContent).toBe('Overdue');
    expect($(panel, '.hk-filters-badge').textContent).toBe('1');
    expect($(panel, '.hk-filters-badge').getAttribute('aria-hidden')).toBe('true');
    expect($(panel, '#hk-filters-btn').getAttribute('aria-label')).toBe('Filters: 1 on');
    const clear = chip.querySelector('[data-clear-filter="scope"]');
    expect(clear.getAttribute('aria-label')).toBe('Clear filter: Overdue');
    clear.click();
    expect(panel._filter).toBe('all');
    expect(localStorage.getItem('home-keeper.filter')).toBe('all');
    expect(panel.shadowRoot.querySelectorAll('.hk-filter-chip')).toHaveLength(0);
    expect(panel.shadowRoot.activeElement?.id).toBe('hk-filters-btn');
  });

  it('follow the search box as it is typed in, and keep the box', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    const input = $(panel, '.hk-search-input');
    input.value = 'gutter';
    input.dispatchEvent(new Event('input'));
    expect($(panel, '.hk-search-input')).toBe(input);
    const chip = await waitFor(() => $(panel, '.hk-filter-chip'));
    expect(chip.textContent).toContain('Search: gutter');
    expect($(panel, '.hk-filters-badge').textContent).toBe('1');
    expect($(panel, '#hk-filters-btn').getAttribute('aria-label')).toBe('Filters: 1 on');
    // The patched chip is live too.
    chip.querySelector('[data-clear-filter="query"]').click();
    expect(panel._query).toBe('');
    expect($(panel, '.hk-filters-badge')).toBeNull();
    expect($(panel, '#hk-filters-btn').hasAttribute('aria-label')).toBe(false);
  });

  it('offer Clear all for 2 filters, and it clears both', async () => {
    localStorage.setItem('home-keeper.filter', 'soon');
    const { panel } = await mountPanel('/tasks', hass());
    panel._setQuery('shower');
    expect(panel.shadowRoot.querySelectorAll('.hk-filter-chip')).toHaveLength(2);
    expect($(panel, '.hk-filters-badge').textContent).toBe('2');
    $(panel, '[data-clear-filter="all"]').click();
    expect(panel._filter).toBe('all');
    expect(panel._query).toBe('');
    expect(panel.shadowRoot.querySelectorAll('.hk-filter-chip')).toHaveLength(0);
    expect($(panel, '[data-clear-filter="all"]')).toBeNull();
  });

  it('name a Profile instead of the scope pill, and clear it', async () => {
    localStorage.setItem('home-keeper.profile', 'p1');
    localStorage.setItem('home-keeper.filter', 'overdue');
    const profiles = [
      { id: 'p1', name: 'Chores <b>', filter: { status: 'all', labels: [], areas: [], devices: [] }, sync: {} },
    ];
    const { panel } = await mountPanel('/tasks', hass({ profiles }));
    const chips = await waitFor(() => {
      const found = panel.shadowRoot.querySelectorAll('.hk-filter-chip');
      return found.length ? found : null;
    });
    expect(chips).toHaveLength(1);
    expect(chips[0].querySelector('.hk-filter-chip-text').textContent).toBe('Profile: Chores <b>');
    expect(chips[0].querySelector('b')).toBeNull();
    chips[0].querySelector('[data-clear-filter="profile"]').click();
    expect(panel._profile).toBe('');
    expect(localStorage.getItem('home-keeper.profile')).toBe('');
  });
});

describe('the spend button', () => {
  it('shows the first period as a whole number, with a full name', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    const btn = await waitFor(() => $(panel, '#hk-spend-btn'));
    expect(btn.querySelector('.hk-spend-btn-text').textContent).toBe('28');
    expect(btn.querySelector('ha-icon').getAttribute('icon')).toBe('mdi:currency-usd');
    expect(btn.getAttribute('aria-label')).toBe('Maintenance spend, Last 30 days: $28.18');
    expect(btn.getAttribute('aria-haspopup')).toBe('dialog');
    expect(btn.getAttribute('aria-expanded')).toBe('false');
    expect(btn.getAttribute('aria-controls')).toBe('hk-spend-sheet');
  });

  it('uses all time when no period is set', async () => {
    const { panel } = await mountPanel('/tasks', hass({ spend: { ...SPEND, windows: [] } }));
    const btn = await waitFor(() => $(panel, '#hk-spend-btn'));
    expect(btn.querySelector('.hk-spend-btn-text').textContent).toBe('258');
    expect(btn.getAttribute('aria-label')).toBe('Maintenance spend, All time: $258.18');
  });

  it('is not there with no cost data', async () => {
    const { panel } = await mountPanel('/tasks', hass({ spend: {} }));
    expect($(panel, '#hk-spend-btn')).toBeNull();
    expect($(panel, '.hk-spend')).toBeNull();
  });

  it('opens a modal sheet, and Escape closes it and returns focus', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    const btn = await waitFor(() => $(panel, '#hk-spend-btn'));
    btn.click();
    const sheet = $(panel, '.hk-spend-sheet');
    expect(sheet.getAttribute('role')).toBe('dialog');
    expect(sheet.getAttribute('aria-modal')).toBe('true');
    expect(sheet.id).toBe('hk-spend-sheet');
    expect(sheet.getAttribute('aria-labelledby')).toBe('hk-spend-sheet-title');
    expect($(panel, '#hk-spend-sheet-title').textContent).toBe('Maintenance spend');
    expect(sheet.querySelectorAll('.hk-spend-total')).toHaveLength(4);
    expect($(panel, '#hk-spend-btn').getAttribute('aria-expanded')).toBe('true');
    expect($(panel, '.hk-wrap').hasAttribute('inert')).toBe(true);
    expect($(panel, '.hk-bottombar').hasAttribute('inert')).toBe(true);
    expect(sheet.contains(panel.shadowRoot.activeElement)).toBe(true);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect($(panel, '.hk-spend-sheet')).toBeNull();
    expect($(panel, '.hk-wrap').hasAttribute('inert')).toBe(false);
    expect(panel.shadowRoot.activeElement?.id).toBe('hk-spend-btn');
    // The listener goes with the sheet.
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(panel._spendSheet).toBe(false);
  });

  it('closes from the scrim and from Close', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    (await waitFor(() => $(panel, '#hk-spend-btn'))).click();
    $(panel, '.hk-spend-scrim').click();
    expect($(panel, '.hk-spend-sheet')).toBeNull();
    $(panel, '#hk-spend-btn').click();
    $(panel, '.hk-spend-sheet-close').click();
    expect($(panel, '.hk-spend-sheet')).toBeNull();
    expect(panel.shadowRoot.activeElement?.id).toBe('hk-spend-btn');
  });

  it('opens a total inside the sheet and keeps the sheet', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    (await waitFor(() => $(panel, '#hk-spend-btn'))).click();
    const total = $(panel, '.hk-spend-sheet [data-spend="w30"]');
    // A browser focuses a button that a click pressed. jsdom does not.
    total.focus();
    total.click();
    const sheet = $(panel, '.hk-spend-sheet');
    expect(sheet.querySelectorAll('.hk-spend-row')).toHaveLength(2);
    expect(panel.shadowRoot.activeElement?.dataset.spend).toBe('w30');
    expect(sheet.contains(panel.shadowRoot.activeElement)).toBe(true);
  });

  it('closes when a record opens its task', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    (await waitFor(() => $(panel, '#hk-spend-btn'))).click();
    $(panel, '.hk-spend-sheet [data-spend="w30"]').click();
    $(panel, '.hk-spend-sheet [data-spend-open]').click();
    expect(panel._spendSheet).toBe(false);
  });
});

describe('the compact spend strip', () => {
  it('shows 1 line of totals above the list, and a total opens its records', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    const strip = await waitFor(() => $(panel, '#hk-list .hk-spend-compact'));
    expect(strip.getAttribute('aria-label')).toBe('Maintenance spend');
    expect(strip.querySelectorAll('.hk-spend-total')).toHaveLength(4);
    expect(strip.querySelector('.hk-spend-count')).toBeNull();
    strip.querySelector('[data-spend="w60"]').click();
    const records = await waitFor(() => $(panel, '#hk-list #hk-spend-strip-records'));
    expect(records.querySelectorAll('.hk-spend-row')).toHaveLength(3);
    expect($(panel, '#hk-list [data-spend="w60"]').getAttribute('aria-controls')).toBe(
      'hk-spend-strip-records',
    );
  });
});

describe('the Appliances tab', () => {
  it('keeps its own control row with no list bar', async () => {
    const { panel } = await mountPanel('/appliances', hass());
    expect($(panel, '.hk-listbar')).toBeNull();
    expect($(panel, '#hk-filters-btn')).toBeNull();
    expect($(panel, '.hk-controls .hk-search-input')).toBeTruthy();
  });
});
