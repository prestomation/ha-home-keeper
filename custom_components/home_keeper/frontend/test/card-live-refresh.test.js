import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { HomeKeeperCard } from '../src/card.ts';

/**
 * A change that arrives while the card loads, or before a load that fails, must still
 * reach the card. The card loads again after such a load.
 */

beforeAll(() => {
  for (const tag of ['ha-card', 'ha-form', 'ha-button', 'ha-icon-button', 'ha-assist-chip',
    'ha-alert', 'ha-spinner', 'ha-icon']) {
    if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
  }
  if (!customElements.get('home-keeper-card')) {
    customElements.define('home-keeper-card', HomeKeeperCard);
  }
});

afterEach(() => {
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

async function waitFor(fn, timeout = 2000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (fn()) return true;
    await new Promise((r) => setTimeout(r, 20));
  }
  return false;
}

const settle = () => new Promise((r) => setTimeout(r, 30));

const task = (name) => ({
  id: 't1',
  name,
  recurrence_type: 'floating',
  interval: 1,
  unit: 'months',
  next_due: new Date(Date.now() + 86_400_000).toISOString(),
  completions: [],
});

/** A card whose `get_tasks` answers only when the test says so. */
async function setup() {
  const ctl = { server: 'v0', pending: [], stamp: 0 };
  const callWS = (msg) => {
    if (msg.type !== 'home_keeper/get_tasks') return Promise.resolve({});
    const tasks = [task(ctl.server)];
    return new Promise((resolve, reject) => {
      ctl.pending.push({ ok: () => resolve({ tasks }), fail: () => reject(new Error('boom')) });
    });
  };
  const card = document.createElement('home-keeper-card');
  card.setConfig({ type: 'custom:home-keeper-card' });
  document.body.appendChild(card);
  const hass = { callWS, language: 'en', states: {} };
  card.hass = hass;
  await waitFor(() => ctl.pending.length === 1);
  ctl.pending.shift().ok();
  await waitFor(() => card.shadowRoot?.querySelector('.hk-row'));
  ctl.change = (name) => {
    ctl.server = name;
    ctl.stamp++;
    card.hass = {
      ...hass,
      states: {
        'todo.home_keeper_tasks': {
          last_updated: new Date(Date.UTC(2026, 9, 1, 10, 0, ctl.stamp)).toISOString(),
        },
      },
    };
  };
  ctl.shown = () => card._tasks.map((t) => t.name).join();
  return { card, ctl };
}

describe('card live refresh', () => {
  it('loads again after a load that started before the change', async () => {
    const { ctl } = await setup();
    ctl.change('v1');
    await waitFor(() => ctl.pending.length === 1);
    // A second change comes while the load for the first one runs.
    ctl.change('v2');
    ctl.pending.shift().ok();
    await settle();
    await waitFor(() => ctl.pending.length === 1);
    expect(ctl.pending.length, 'a second load should start').toBe(1);
    ctl.pending.shift().ok();
    await settle();
    expect(ctl.shown()).toBe('v2');
  });

  it('loads again on a later push after a failed load', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const { card, ctl } = await setup();
    ctl.change('v1');
    await waitFor(() => ctl.pending.length === 1);
    ctl.pending.shift().fail();
    await settle();
    expect(ctl.pending.length).toBe(0);
    // The next hass push after the retry wait loads the change.
    card._live = { ...card._live, retryAt: 0 };
    card.hass = { ...card.hass };
    await waitFor(() => ctl.pending.length === 1);
    expect(ctl.pending.length, 'a load should start on the next push').toBe(1);
    ctl.pending.shift().ok();
    await settle();
    expect(ctl.shown()).toBe('v1');
  });
});
