import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { HomeKeeperCard } from '../src/card.ts';

// The card waits for HA's lazy components before first paint and renders them.
// Register lightweight stand-ins so `whenDefined` resolves and the markup is
// valid in jsdom, then register the card element itself.
beforeAll(() => {
  for (const tag of [
    'ha-card',
    'ha-form',
    'ha-button',
    'ha-icon-button',
    'ha-assist-chip',
    'ha-alert',
    'ha-spinner',
    'ha-icon',
  ]) {
    if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
  }
  if (!customElements.get('home-keeper-card')) {
    customElements.define('home-keeper-card', HomeKeeperCard);
  }
});

function makeCard(config = { type: 'custom:home-keeper-card' }) {
  const card = document.createElement('home-keeper-card');
  card.setConfig(config);
  document.body.appendChild(card); // connectedCallback -> boot
  return card;
}

async function waitFor(fn, timeout = 2000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (fn()) return true;
    await new Promise((r) => setTimeout(r, 20));
  }
  return false;
}

const sr = (card) => card.shadowRoot;

afterEach(() => {
  document.body.innerHTML = '';
});

const sampleTasks = [
  {
    id: 't1',
    name: 'Replace filter',
    recurrence_type: 'floating',
    interval: 1,
    unit: 'months',
    next_due: new Date(Date.now() + 86_400_000).toISOString(),
    completions: [],
  },
];

describe('HomeKeeperCard load states', () => {
  it('shows an error (not an endless spinner) when tasks fail to load', async () => {
    const card = makeCard();
    card.hass = { callWS: () => Promise.reject(new Error('not_loaded')), language: 'en' };

    const shown = await waitFor(() => sr(card)?.querySelector('ha-alert[alert-type="error"]'));
    expect(shown, 'an error alert should render').toBe(true);
    expect(sr(card).querySelector('ha-spinner'), 'spinner should be gone').toBeNull();
  });

  it('renders task rows on a successful load', async () => {
    const card = makeCard();
    card.hass = { callWS: async () => ({ tasks: sampleTasks }), language: 'en' };

    const shown = await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(shown).toBe(true);
    expect(sr(card).textContent).toContain('Replace filter');
    expect(sr(card).querySelector('ha-alert[alert-type="error"]')).toBeNull();
  });

  it('recovers from an error on a later state change (no manual reload)', async () => {
    const card = makeCard();
    // First load fails (integration not ready yet).
    card.hass = { callWS: () => Promise.reject(new Error('not_loaded')), language: 'en' };
    await waitFor(() => sr(card)?.querySelector('ha-alert[alert-type="error"]'));

    // A later hass update with a changed Home Keeper state signal must trigger a
    // retry — proving the card keeps trying rather than staying stuck.
    card.hass = {
      callWS: async () => ({ tasks: sampleTasks }),
      language: 'en',
      states: {
        'todo.home_keeper_tasks': {
          entity_id: 'todo.home_keeper_tasks',
          state: '1',
          last_updated: new Date().toISOString(),
          attributes: {},
        },
      },
    };

    const recovered = await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(recovered, 'rows should appear after the retry').toBe(true);
    expect(sr(card).querySelector('ha-alert[alert-type="error"]')).toBeNull();
  });
});

describe('HomeKeeperCard completion guard', () => {
  it('ignores a re-entrant complete while one is already in flight', async () => {
    const card = makeCard();
    let completeCalls = 0;
    let resolveComplete;
    card.hass = {
      language: 'en',
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_tasks') return { tasks: sampleTasks };
        if (msg.type === 'home_keeper/complete_task') {
          completeCalls++;
          // Keep the first call pending so the second tap overlaps it.
          await new Promise((r) => (resolveComplete = r));
          return { task: sampleTasks[0] };
        }
        return {};
      },
    };
    await waitFor(() => sr(card)?.querySelector('.hk-done'));

    const done = sr(card).querySelector('.hk-done');
    done.click();
    done.click(); // second tap while the first is still pending
    await new Promise((r) => setTimeout(r, 50));
    expect(completeCalls, 'only one completion should be sent').toBe(1);
    resolveComplete?.({});
  });
});
