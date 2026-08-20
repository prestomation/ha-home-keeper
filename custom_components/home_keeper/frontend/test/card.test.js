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

describe('HomeKeeperCard hide_when_empty', () => {
  it('stays visible and shows the "no match" alert by default', async () => {
    const card = makeCard({ type: 'custom:home-keeper-card', labels: ['no-such-label'] });
    card.hass = { callWS: async () => ({ tasks: sampleTasks }), language: 'en' };

    const shown = await waitFor(() => sr(card)?.querySelector('.hk-empty'));
    expect(shown).toBe(true);
    expect(card.style.display).toBe('');
  });

  it('hides the whole card when configured and nothing matches, and reappears once a task matches', async () => {
    let tasks = [];
    const card = makeCard({
      type: 'custom:home-keeper-card',
      labels: ['no-such-label'],
      hide_when_empty: true,
    });
    card.hass = { callWS: async () => ({ tasks }), language: 'en' };

    await waitFor(() => card.style.display === 'none');
    expect(card.style.display, 'card should collapse when its filter matches nothing').toBe(
      'none',
    );

    // A later hass update whose tasks satisfy the filter should reveal the card again.
    tasks = [{ ...sampleTasks[0], labels: ['no-such-label'] }];
    card.hass = {
      callWS: async () => ({ tasks }),
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

    await waitFor(() => card.style.display === '');
    expect(card.style.display, 'card should reappear once a task matches').toBe('');
    expect(sr(card).querySelector('.hk-row')).not.toBeNull();
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

describe('HomeKeeperCard document chips', () => {
  // Regression guard for the iOS/WKWebView fix: an uploaded *file* document must render
  // as a plain <a href> with a pre-signed URL (a native tap), NOT a <button> that signs
  // on click — WKWebView blocks a window.open issued after the async signing round-trip.
  it('renders an uploaded file document as a pre-signed anchor (not a button)', async () => {
    const card = makeCard();
    const fileTask = {
      id: 't1',
      name: 'Replace filter',
      recurrence_type: 'floating',
      interval: 1,
      unit: 'months',
      next_due: new Date(Date.now() + 86_400_000).toISOString(),
      completions: [],
      card_links: [{ asset_id: 'a1', entry_id: 'd1' }],
    };
    let signCalls = 0;
    card.hass = {
      language: 'en',
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_tasks') return { tasks: [fileTask] };
        if (msg.type === 'home_keeper/get_assets') {
          return {
            assets: [
              {
                id: 'a1',
                name: 'Heater',
                documents: [{ id: 'd1', kind: 'file', name: 'Manual', filename: 'm.pdf' }],
              },
            ],
          };
        }
        if (msg.type === 'home_keeper/sign_document_url') {
          signCalls++;
          return { url: '/api/home_keeper/document/a1/d1?authSig=xyz' };
        }
        return {};
      },
    };

    await waitFor(() => sr(card)?.querySelector('a.hk-link-chip'));
    const anchor = sr(card).querySelector('a.hk-link-chip');
    expect(anchor, 'a file document renders as a link-chip anchor').toBeTruthy();
    expect(anchor.getAttribute('href')).toBe('/api/home_keeper/document/a1/d1?authSig=xyz');
    expect(anchor.getAttribute('target')).toBe('_blank');
    // The async-window.open path (a <button>) is gone — that's what failed on iOS.
    expect(sr(card).querySelector('button.hk-link-chip'), 'no JS-driven file button').toBeNull();
    expect(signCalls, 'the file URL was pre-signed').toBe(1);
  });

  it('renders a linked part\'s product URL as a chip when the part has one', async () => {
    const card = makeCard();
    const linkedTask = {
      id: 't2',
      name: 'Replace anode rod',
      recurrence_type: 'floating',
      interval: 12,
      unit: 'months',
      next_due: new Date(Date.now() + 86_400_000).toISOString(),
      completions: [],
      source: { part: { asset_id: 'a1', part_id: 'p1' } },
    };
    card.hass = {
      language: 'en',
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_tasks') return { tasks: [linkedTask] };
        if (msg.type === 'home_keeper/get_assets') {
          return {
            assets: [
              {
                id: 'a1',
                name: 'Water heater',
                parts: [
                  { id: 'p1', name: 'Anode rod', type: 'wear', url: 'https://example.com/anode' },
                ],
              },
            ],
          };
        }
        return {};
      },
    };

    await waitFor(() => sr(card)?.querySelector('a.hk-link-chip'));
    const anchor = sr(card).querySelector('a.hk-link-chip');
    expect(anchor, 'the linked part renders as a chip').toBeTruthy();
    expect(anchor.getAttribute('href')).toBe('https://example.com/anode');
    expect(anchor.querySelector('ha-assist-chip')?.getAttribute('label')).toBe('Anode rod');
  });

  it('renders no chip for a linked part without a product URL', async () => {
    const card = makeCard();
    const linkedTask = {
      id: 't3',
      name: 'Replace T&P valve',
      recurrence_type: 'floating',
      interval: 36,
      unit: 'months',
      next_due: new Date(Date.now() + 86_400_000).toISOString(),
      completions: [],
      source: { part: { asset_id: 'a1', part_id: 'p2' } },
    };
    card.hass = {
      language: 'en',
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_tasks') return { tasks: [linkedTask] };
        if (msg.type === 'home_keeper/get_assets') {
          return {
            assets: [
              { id: 'a1', name: 'Water heater', parts: [{ id: 'p2', name: 'T&P valve', type: 'wear' }] },
            ],
          };
        }
        return {};
      },
    };

    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(sr(card).querySelector('a.hk-link-chip')).toBeNull();
  });
});

describe('Card notes render as Markdown (issue #163)', () => {
  beforeAll(() => {
    if (!customElements.get('ha-markdown')) {
      customElements.define('ha-markdown', class extends HTMLElement {});
    }
  });

  const noted = [{ ...sampleTasks[0], notes: 'Use a **HEPA** filter' }];

  it('renders the note through ha-markdown when show_notes is on', async () => {
    const card = makeCard({ type: 'custom:home-keeper-card', show_notes: true });
    card.hass = { callWS: async () => ({ tasks: noted }), language: 'en' };

    const shown = await waitFor(() => sr(card)?.querySelector('.hk-notes ha-markdown'));
    expect(shown).toBe(true);
    // `content` is a property, so `_hydrate` has to move `data-md` onto it.
    expect(sr(card).querySelector('.hk-notes ha-markdown').content).toBe('Use a **HEPA** filter');
  });

  it('still honours show_notes being off', async () => {
    const card = makeCard({ type: 'custom:home-keeper-card' });
    card.hass = { callWS: async () => ({ tasks: noted }), language: 'en' };

    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(sr(card).querySelector('.hk-notes')).toBeNull();
  });

  it('does not inject the note as raw markup', async () => {
    const nasty = [{ ...sampleTasks[0], notes: '<img src=x onerror=alert(1)>' }];
    const card = makeCard({ type: 'custom:home-keeper-card', show_notes: true });
    card.hass = { callWS: async () => ({ tasks: nasty }), language: 'en' };

    await waitFor(() => sr(card)?.querySelector('.hk-notes ha-markdown'));
    expect(sr(card).querySelector('img')).toBeNull();
    expect(sr(card).querySelector('.hk-notes ha-markdown').content).toBe(
      '<img src=x onerror=alert(1)>',
    );
  });
});

// NFC/RFID tag binding (issue #211). The card shows that a task is tag-bound and,
// when the tag is the only way to complete it, refuses its own mark-done — the
// backend rejects that completion, and the sidebar panel would refuse it too, so
// there is nowhere to send the user but back to the tag.
describe('HomeKeeperCard NFC tag binding (issue #211)', () => {
  const tagged = (extra) => [{ ...sampleTasks[0], tag_id: 'tag_kitchen', ...extra }];
  const chipLabels = (card) =>
    [...sr(card).querySelectorAll('.hk-chips ha-assist-chip')].map((c) => c.getAttribute('label'));

  it('renders an NFC chip for a tag-bound task', async () => {
    const card = makeCard();
    card.hass = { callWS: async () => ({ tasks: tagged() }), language: 'en' };

    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(chipLabels(card)).toContain('NFC tag');
    const chip = sr(card).querySelector('ha-assist-chip.hk-tag');
    expect(chip.querySelector('ha-icon').getAttribute('icon')).toBe('mdi:nfc-variant');
  });

  it('shows no NFC chip for a task with no tag', async () => {
    const card = makeCard();
    card.hass = { callWS: async () => ({ tasks: sampleTasks }), language: 'en' };

    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(sr(card).querySelector('ha-assist-chip.hk-tag')).toBeNull();
  });

  it('swaps the chip glyph for a padlock once a scan is required', async () => {
    const card = makeCard();
    card.hass = {
      callWS: async () => ({ tasks: tagged({ require_tag_scan: true }) }),
      language: 'en',
    };

    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    const chip = sr(card).querySelector('ha-assist-chip.hk-tag');
    expect(chip.querySelector('ha-icon').getAttribute('icon')).toBe('mdi:lock');
    expect(chip.getAttribute('title')).toBe(
      'This task can only be completed by scanning its tag.',
    );
  });

  it('leaves mark-done live when a tag is bound but no scan is required', async () => {
    const card = makeCard();
    let completes = 0;
    card.hass = {
      language: 'en',
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_tasks') return { tasks: tagged() };
        if (msg.type === 'home_keeper/complete_task') completes++;
        return {};
      },
    };

    await waitFor(() => sr(card)?.querySelector('.hk-done'));
    const done = sr(card).querySelector('.hk-done');
    expect(done.classList.contains('blocked')).toBe(false);
    done.click();
    await new Promise((r) => setTimeout(r, 50));
    expect(completes, 'an unlocked tag-bound task still completes from the card').toBe(1);
  });

  it('blocks mark-done for a scan-locked task and explains instead', async () => {
    const card = makeCard();
    const sent = [];
    card.hass = {
      language: 'en',
      callWS: async (msg) => {
        sent.push(msg.type);
        if (msg.type === 'home_keeper/get_tasks') {
          return { tasks: tagged({ require_tag_scan: true }) };
        }
        return {};
      },
    };
    const toasts = [];
    card.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));

    await waitFor(() => sr(card)?.querySelector('.hk-done'));
    const done = sr(card).querySelector('.hk-done');
    expect(done.classList.contains('blocked')).toBe(true);

    done.click();
    await new Promise((r) => setTimeout(r, 50));
    // The completion never leaves the browser — the backend would reject it.
    expect(sent).not.toContain('home_keeper/complete_task');
    expect(toasts).toEqual(["Scan this task's tag to complete it."]);
  });

  it('does not send a scan-locked task to the panel — it is refused there too', async () => {
    const card = makeCard();
    card.hass = {
      language: 'en',
      callWS: async (msg) =>
        msg.type === 'home_keeper/get_tasks'
          ? { tasks: tagged({ require_tag_scan: true }) }
          : {},
    };
    const navigations = [];
    window.addEventListener('location-changed', () => navigations.push(location.pathname));

    await waitFor(() => sr(card)?.querySelector('.hk-done'));
    sr(card).querySelector('.hk-done').click();
    await new Promise((r) => setTimeout(r, 50));
    expect(navigations).toEqual([]);
  });
});
