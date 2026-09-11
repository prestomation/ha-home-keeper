/**
 * The minimal task layout: the Settings toggle, the 2-column grid it swaps in,
 * and the tap-opens-popup / press-and-hold-opens-details interaction on its
 * cards. See `panel-lists.ts` (`taskCardMinimal`, `wireMinimalGrid`,
 * `renderQuickActions`) and `panel-settings.ts` (the switch row).
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { HomeKeeperPanel } from '../src/panel.ts';

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
    'ha-switch',
    'ha-dialog',
  ]) {
    if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
  }
  if (!customElements.get('home-keeper-panel')) {
    customElements.define('home-keeper-panel', HomeKeeperPanel);
  }
});

afterEach(() => {
  document.body.innerHTML = '';
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

/** A minimal `hass`, backed by a shared per-user data store the way HA's own
 *  `frontend/get_user_data`/`set_user_data` would be — so a toggle made by one
 *  panel instance is visible to the next, the same fixture shape the intro-
 *  banner cross-device test (#182) uses. */
function makeHass(tasks, userDataStore = {}) {
  const calls = {};
  const hass = {
    language: 'en',
    states: {},
    devices: {},
    callWS(msg) {
      calls[msg.type] = (calls[msg.type] || 0) + 1;
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [] });
        case 'home_keeper/get_options':
          return Promise.resolve({ options: {} });
        case 'home_keeper/complete_task':
          calls.completed = calls.completed || [];
          calls.completed.push(msg.task_id);
          return Promise.resolve({ task: tasks.find((t) => t.id === msg.task_id) });
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

async function mountPanel(hass, path = '/tasks') {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('#add-btn'));
  return panel;
}

const mkTask = (over) => ({
  recurrence_type: 'floating',
  interval: 3,
  unit: 'months',
  next_due: '2030-01-01T00:00:00+00:00',
  completions: [],
  ...over,
});

describe('Minimal layout — Settings toggle', () => {
  it('defaults off: the standard row list renders, with no switch checked', async () => {
    const { hass } = makeHass([mkTask({ id: 't1', name: 'Replace filter' })]);
    const panel = await mountPanel(hass, '/tasks');
    const rows = panel.shadowRoot.querySelectorAll('#hk-list .hk-card-row');
    expect(rows.length).toBe(1);
    expect(panel.shadowRoot.querySelector('.hk-card-minimal')).toBeNull();
  });

  it('switching it on swaps the row list for the 2-column grid, and persists per-user', async () => {
    const userDataStore = {};
    const { hass, calls } = makeHass([mkTask({ id: 't1', name: 'Replace filter' })], userDataStore);
    const panel = await mountPanel(hass, '/settings');
    const sw = await waitFor(() => panel.shadowRoot?.querySelector('#hk-settings-general ha-switch'));
    expect(sw, 'the minimal-layout switch should render in the General card').toBeTruthy();
    expect(sw.checked).toBeFalsy();

    sw.checked = true;
    sw.dispatchEvent(new Event('change'));

    const saved = await waitFor(() => (calls['frontend/set_user_data'] || 0) > 0);
    expect(saved, 'the toggle should persist via frontend/set_user_data').toBeTruthy();
    expect(userDataStore['home_keeper_minimal_layout']).toBe(true);

    panel.route = { prefix: '/home-keeper', path: '/tasks' };
    const grid = await waitFor(() => panel.shadowRoot.querySelector('.hk-minimal-grid'));
    expect(grid, 'the task list should switch to the minimal grid').toBeTruthy();
    const cards = panel.shadowRoot.querySelectorAll('.hk-card-minimal');
    expect(cards.length).toBe(1);
    expect(cards[0].querySelector('.hk-name').textContent.trim()).toBe('Replace filter');
    // Only the name and a status pill — no chips, no meta line, no inline button.
    expect(cards[0].querySelector('.hk-meta')).toBeNull();
    expect(cards[0].querySelector('ha-button')).toBeNull();

    // A second panel instance for the same user (a different browser/device)
    // should boot straight into the minimal layout.
    panel.remove();
    const { hass: hassB } = makeHass([mkTask({ id: 't1', name: 'Replace filter' })], userDataStore);
    const panelB = await mountPanel(hassB, '/tasks');
    expect(panelB.shadowRoot.querySelector('.hk-minimal-grid')).toBeTruthy();
  });
});

describe('Minimal grid card — tap opens quick actions, hold opens details', () => {
  async function mountMinimal(tasks) {
    const { hass, calls } = makeHass(tasks, { home_keeper_minimal_layout: true });
    const panel = await mountPanel(hass, '/tasks');
    await waitFor(() => panel.shadowRoot.querySelector('.hk-card-minimal'));
    return { panel, hass, calls };
  }

  it('a tap opens the quick-actions popup with Done / Skip / Snooze / View details', async () => {
    const { panel } = await mountMinimal([mkTask({ id: 't1', name: 'Replace filter' })]);
    const card = panel.shadowRoot.querySelector('.hk-card-minimal');
    card.dispatchEvent(new Event('pointerdown'));
    card.dispatchEvent(new Event('pointerup'));
    card.dispatchEvent(new Event('click'));

    const dialog = await waitFor(() => panel.shadowRoot.querySelector('#hk-dialog-host ha-dialog'));
    expect(dialog, 'a tap should open the quick-actions dialog').toBeTruthy();
    const labels = [...dialog.querySelectorAll('.hk-quick-row span')].map((s) => s.textContent);
    expect(labels).toEqual(['Done', 'Skip', 'Snooze', 'View details']);
  });

  it('clicking Mark done in the popup completes the task and closes it', async () => {
    const { panel, calls } = await mountMinimal([mkTask({ id: 't1', name: 'Replace filter' })]);
    const card = panel.shadowRoot.querySelector('.hk-card-minimal');
    card.click();
    const dialog = await waitFor(() => panel.shadowRoot.querySelector('#hk-dialog-host ha-dialog'));
    [...dialog.querySelectorAll('.hk-quick-row')]
      .find((b) => b.textContent.includes('Done'))
      .click();

    await waitFor(() => calls.completed?.length);
    expect(calls.completed).toEqual(['t1']);
    expect(panel.shadowRoot.querySelector('#hk-dialog-host ha-dialog')).toBeNull();
  });

  it('a monitored (dormant) task has no Done row in the popup', async () => {
    const { panel } = await mountMinimal([
      mkTask({ id: 't1', name: 'Leak sensor', recurrence_type: 'triggered', next_due: undefined }),
    ]);
    const card = panel.shadowRoot.querySelector('.hk-card-minimal');
    card.click();
    const dialog = await waitFor(() => panel.shadowRoot.querySelector('#hk-dialog-host ha-dialog'));
    const labels = [...dialog.querySelectorAll('.hk-quick-row span')].map((s) => s.textContent);
    expect(labels).toEqual(['View details']);
  });

  it('press-and-hold opens the task detail page instead of the popup', async () => {
    const { panel } = await mountMinimal([mkTask({ id: 't1', name: 'Replace filter' })]);
    vi.useFakeTimers();
    try {
      const card = panel.shadowRoot.querySelector('.hk-card-minimal');
      card.dispatchEvent(new Event('pointerdown'));
      await vi.advanceTimersByTimeAsync(600);
      card.dispatchEvent(new Event('pointerup'));
      card.dispatchEvent(new Event('click'));

      // _navigate only pushes history and asks HA's router for the route back —
      // nothing supplies that in jsdom (see the sub-tab test above), so the URL
      // it pushed is the observable signal that the detail page was opened.
      expect(location.pathname).toBe('/home-keeper/tasks/t1');
      expect(panel.shadowRoot.querySelector('#hk-dialog-host ha-dialog')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('releasing before the long-press threshold opens the popup, not the details page', async () => {
    const { panel } = await mountMinimal([mkTask({ id: 't1', name: 'Replace filter' })]);
    const before = location.pathname;
    vi.useFakeTimers();
    try {
      const card = panel.shadowRoot.querySelector('.hk-card-minimal');
      card.dispatchEvent(new Event('pointerdown'));
      await vi.advanceTimersByTimeAsync(100);
      card.dispatchEvent(new Event('pointerup'));
      card.dispatchEvent(new Event('click'));

      expect(location.pathname).toBe(before);
      expect(panel.shadowRoot.querySelector('#hk-dialog-host ha-dialog')).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });
});
