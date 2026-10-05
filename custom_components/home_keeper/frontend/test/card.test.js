import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { FILTER_OPTS, HomeKeeperCard, RECURRENCE_OPTS, todoEntityId } from '../src/card.ts';

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

  it('X12-4: sends one add for a double press of Create', async () => {
    const card = makeCard();
    let addCalls = 0;
    let resolveAdd;
    card.hass = {
      language: 'en',
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_tasks') return { tasks: sampleTasks };
        if (msg.type === 'home_keeper/add_task') {
          addCalls++;
          // A device-linked add waits for an entry reload before it replies.
          await new Promise((r) => (resolveAdd = r));
          return { task: { id: 'new' } };
        }
        return {};
      },
    };
    await waitFor(() => sr(card)?.querySelector('.hk-done'));
    card._edit = { open: true, task: { name: 'Clean gutters', recurrence_type: 'floating' } };
    card._render();
    const create = sr(card).querySelector('.hk-form-actions ha-button');
    create.click();
    expect(create.hasAttribute('disabled')).toBe(true);
    create.click();
    await new Promise((r) => setTimeout(r, 50));
    expect(addCalls, 'only one add should be sent').toBe(1);
    resolveAdd?.();
    await waitFor(() => !card._edit.open);
    expect(card._edit.open).toBe(false);
  });
});

describe('HomeKeeperCard monitored rows (issue #231)', () => {
  /** The appliance behind the counted wear item below, so a part-linked row can
   *  resolve its part the way it does in the panel. */
  const WEAR_ASSET = {
    id: 'a1',
    name: 'Rain jacket',
    parts: [{ id: 'p1', name: 'DWR coating', type: 'wear', replace_interval: 25, replace_unit: 'uses' }],
  };

  /** Boot a card holding *tasks* and hand back its shadow root once a row paints.
   *  Pass `assetPayload` to answer get_assets with something other than the appliance
   *  above — `{}` is the malformed-but-resolved case the guard below is about. */
  async function rowsFor(tasks, assetPayload = { assets: [WEAR_ASSET] }) {
    const card = makeCard();
    card.hass = {
      language: 'en',
      callWS: async (msg) =>
        msg.type === 'home_keeper/get_tasks'
          ? { tasks }
          : msg.type === 'home_keeper/get_assets'
            ? assetPayload
            : {},
    };
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    return sr(card);
  }

  const monitored = {
    id: 'm1',
    name: 'Check on Hallway Sensor',
    recurrence_type: 'sensor',
    sensor: { entity_id: 'binary_sensor.hallway_ping', mode: 'availability' },
    next_due: null,
    completions: [],
  };

  // A dormant edge-mode sensor task is waiting for its condition. Pressing Done
  // recorded a completion and left the task exactly where it was.
  it('offers no mark-done on a dormant sensor task watching a condition', async () => {
    const root = await rowsFor([monitored]);

    expect(root.querySelector('.hk-row')).toBeTruthy();
    expect(root.querySelector('.hk-done')).toBeNull();
  });

  it('offers mark-done again once the watcher arms the task', async () => {
    const root = await rowsFor([{ ...monitored, next_due: new Date().toISOString() }]);

    expect(root.querySelector('.hk-done')).toBeTruthy();
  });

  // A meter is counting up to its target, and completing it early re-anchors that
  // meter — real work, so the row keeps its button.
  it('keeps mark-done on a dormant usage meter', async () => {
    const root = await rowsFor([
      {
        ...monitored,
        id: 'm2',
        sensor: { entity_id: 'sensor.pump_hours', mode: 'usage', target: 300, baseline: 0 },
      },
    ]);

    expect(root.querySelector('.hk-done')).toBeTruthy();
  });

  // A counted wear item's replacement half is the second exception, for the same
  // reason: renewing the coating at 10 of 25 wears is real work, and Done restarts
  // the count. The card is the third surface reading the one predicate.
  it('keeps mark-done on a counted wear item’s dormant replacement half', async () => {
    const root = await rowsFor([
      {
        id: 'rep1',
        name: 'Renew DWR coating (Rain jacket)',
        recurrence_type: 'triggered',
        next_due: null,
        completions: [],
        source: { part: { asset_id: 'a1', part_id: 'p1' } },
      },
    ]);

    expect(root.querySelector('.hk-done')).toBeTruthy();
  });

  // The control: `set_task_consumable` writes the same source shape, flagged manual,
  // onto a task the user owns — and that one is still waiting on its owner.
  it('offers no mark-done on a hand-linked task pointing at a part', async () => {
    const root = await rowsFor([
      {
        id: 'man1',
        name: 'Wash the jacket',
        recurrence_type: 'triggered',
        next_due: null,
        completions: [],
        source: { part: { asset_id: 'a1', part_id: 'p1', manual: true } },
      },
    ]);

    expect(root.querySelector('.hk-row')).toBeTruthy();
    expect(root.querySelector('.hk-done')).toBeNull();
  });

  // A resolved-but-empty get_assets payload is not a rejection, so the boot path's
  // `.catch(() => [])` never fired and `_assets` held undefined behind an `Asset[]`
  // type. `_resolvePartLink` then threw on the first task carrying a part source,
  // which is every half of every wear item, and the whole card painted nothing.
  it('still renders part-linked rows when the appliance payload comes back empty', async () => {
    const root = await rowsFor(
      [
        {
          id: 'rep1',
          name: 'Renew DWR coating (Rain jacket)',
          recurrence_type: 'triggered',
          next_due: null,
          completions: [],
          source: { part: { asset_id: 'a1', part_id: 'p1' } },
        },
      ],
      {},
    );

    expect(root.querySelector('.hk-row')).toBeTruthy();
    expect(root.textContent).toContain('Renew DWR coating');
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

// The line under the task name: the schedule and the completion count (issue #432).
// Each part has its own row setting. Both default to on.
describe('Card schedule and completion count settings (issue #432)', () => {
  const done = [
    {
      ...sampleTasks[0],
      completions: [
        { id: 'c1', completed_at: '2026-01-01T00:00:00+00:00' },
        { id: 'c2', completed_at: '2026-02-01T00:00:00+00:00' },
      ],
    },
  ];

  async function metaOf(config) {
    const card = makeCard({ type: 'custom:home-keeper-card', ...config });
    card.hass = { callWS: async () => ({ tasks: done }), language: 'en' };
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    return sr(card).querySelector('.hk-meta');
  }

  it('shows the schedule and the count by default', async () => {
    const meta = await metaOf({});
    expect(meta.textContent).toBe('Every month after completion · 2 completions');
  });

  it('hides only the schedule when show_schedule is off', async () => {
    const meta = await metaOf({ show_schedule: false });
    expect(meta.textContent).toBe('2 completions');
  });

  it('hides only the count when show_history_count is off', async () => {
    const meta = await metaOf({ show_history_count: false });
    expect(meta.textContent).toBe('Every month after completion');
  });

  it('removes the whole line when both are off', async () => {
    expect(await metaOf({ show_schedule: false, show_history_count: false })).toBeNull();
  });

  it('removes the line for a task with no completions when the schedule is off', async () => {
    const card = makeCard({ type: 'custom:home-keeper-card', show_schedule: false });
    card.hass = { callWS: async () => ({ tasks: sampleTasks }), language: 'en' };
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(sr(card).querySelector('.hk-meta')).toBeNull();
  });
});

// Issue #435: card options that start the groups closed.
describe('Card collapse options (issue #435)', () => {
  const day = 86_400_000;
  const mk = (id, daysFromNow) => ({
    ...sampleTasks[0],
    id,
    name: id,
    next_due: new Date(Date.now() + daysFromNow * day).toISOString(),
  });
  // 3 overdue tasks and 1 later task.
  const tasks = [mk('a', -5), mk('b', -4), mk('c', -3), mk('d', 60)];

  async function open(config) {
    const card = makeCard({ type: 'custom:home-keeper-card', group_by: 'status', ...config });
    card.hass = { callWS: async () => ({ tasks }), language: 'en' };
    await waitFor(() => sr(card)?.querySelector('details.hk-group'));
    return card;
  }
  const state = (card) =>
    Object.fromEntries(
      [...sr(card).querySelectorAll('details.hk-group')].map((d) => [d.dataset.groupKey, d.open]),
    );

  it('starts every group open by default', async () => {
    expect(state(await open({}))).toEqual({ 'status:overdue': true, 'status:later': true });
  });

  it('starts every group closed with collapsed', async () => {
    expect(state(await open({ collapsed: true }))).toEqual({
      'status:overdue': false,
      'status:later': false,
    });
  });

  it('starts only the named groups closed with collapsed_groups', async () => {
    expect(state(await open({ collapsed_groups: ['overdue'] }))).toEqual({
      'status:overdue': false,
      'status:later': true,
    });
  });

  it('starts a group closed above collapse_above', async () => {
    expect(state(await open({ collapse_above: 2 }))).toEqual({
      'status:overdue': false,
      'status:later': true,
    });
  });

  it('keeps a group the user opened when the card draws again', async () => {
    const card = await open({ collapsed: true });
    const overdue = sr(card).querySelector('details[data-group-key="status:overdue"]');
    overdue.open = true;
    overdue.dispatchEvent(new Event('toggle'));
    card.hass = { callWS: async () => ({ tasks }), language: 'en' };
    card.setConfig({ type: 'custom:home-keeper-card', group_by: 'status', collapsed: true });
    expect(state(card)).toEqual({ 'status:overdue': true, 'status:later': false });
  });

  it('keeps a group the user opened when only group_by changes', async () => {
    const card = await open({ collapsed: true });
    const overdue = sr(card).querySelector('details[data-group-key="status:overdue"]');
    overdue.open = true;
    overdue.dispatchEvent(new Event('toggle'));
    card.setConfig({ type: 'custom:home-keeper-card', group_by: 'none', collapsed: true });
    card.setConfig({ type: 'custom:home-keeper-card', group_by: 'status', collapsed: true });
    expect(state(card)).toEqual({ 'status:overdue': true, 'status:later': false });
  });

  it('counts the tasks that max_items leaves in the group for collapse_above', async () => {
    // 3 overdue tasks, max_items 2: the group shows 2, so collapse_above 2 keeps it open.
    expect(state(await open({ max_items: 2, collapse_above: 2 }))['status:overdue']).toBe(true);
  });

  it('starts over from the options when a collapse option changes', async () => {
    const card = await open({ collapsed: true });
    const overdue = sr(card).querySelector('details[data-group-key="status:overdue"]');
    overdue.open = true;
    overdue.dispatchEvent(new Event('toggle'));
    card.setConfig({ type: 'custom:home-keeper-card', group_by: 'status', collapsed_groups: ['later'] });
    expect(state(card)).toEqual({ 'status:overdue': true, 'status:later': false });
  });
});

// Note quick-view (issue #340). A task with a note gets a one-tap chip that opens a
// read-only dialog showing the full note as Markdown, independent of the card's
// "Show notes" row setting — the point is a compact row that still reaches the note.
describe('Card note quick-view (issue #340)', () => {
  beforeAll(() => {
    if (!customElements.get('ha-markdown')) {
      customElements.define('ha-markdown', class extends HTMLElement {});
    }
    if (!customElements.get('ha-dialog')) {
      customElements.define('ha-dialog', class extends HTMLElement {});
    }
  });

  const noted = [{ ...sampleTasks[0], notes: 'Use a **HEPA** filter' }];

  it('shows the note chip only on a task with a note', async () => {
    const card = makeCard();
    card.hass = { callWS: async () => ({ tasks: noted }), language: 'en' };

    const shown = await waitFor(() => sr(card)?.querySelector('.hk-note-chip'));
    expect(shown).toBe(true);
    expect(sr(card).querySelector('.hk-note-chip').getAttribute('label')).toBe('Note');
  });

  // A task deleted from the panel while its note is open is gone from `_tasks` on the
  // next push. Showing the copy captured at open time would put a note on screen for a
  // task that no longer exists, so the dialog goes away instead.
  it('drops the dialog when the task is deleted from another surface', async () => {
    const card = makeCard();
    let tasks = noted;
    card.hass = { callWS: async () => ({ tasks }), language: 'en' };

    await waitFor(() => sr(card)?.querySelector('.hk-note-chip'));
    sr(card).querySelector('.hk-note-chip').click();
    await waitFor(() => sr(card)?.querySelector('ha-dialog[open]'));

    // The task goes away, and a state change makes the card reload.
    tasks = [];
    card.hass = {
      callWS: async () => ({ tasks }),
      language: 'en',
      states: {
        'todo.home_keeper_tasks': {
          entity_id: 'todo.home_keeper_tasks',
          state: '0',
          last_updated: new Date().toISOString(),
          attributes: {},
        },
      },
    };

    const gone = await waitFor(() => !sr(card)?.querySelector('ha-dialog[open]'));
    expect(gone, 'the dialog must not outlive its task').toBe(true);
  });

  // The chip carries `hk-link-chip` so it takes the card's primary-tinted, outlined
  // style — the same one the document chips use. A neutral chip reads as inert state,
  // like the Area chip beside it, and nothing else would catch that class going away.
  it('reads as a link-chip, not a neutral state chip', async () => {
    const card = makeCard();
    card.hass = { callWS: async () => ({ tasks: noted }), language: 'en' };

    await waitFor(() => sr(card)?.querySelector('.hk-note-chip'));
    const chip = sr(card).querySelector('.hk-note-chip');
    expect(chip.classList.contains('hk-link-chip')).toBe(true);
  });

  it('shows no note chip on a task with no note', async () => {
    const card = makeCard();
    card.hass = { callWS: async () => ({ tasks: sampleTasks }), language: 'en' };

    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(sr(card).querySelector('.hk-note-chip')).toBeNull();
  });

  it('shows no note chip on a task whose note is blank', async () => {
    const card = makeCard();
    const blank = [{ ...sampleTasks[0], notes: '   ' }];
    card.hass = { callWS: async () => ({ tasks: blank }), language: 'en' };

    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(sr(card).querySelector('.hk-note-chip')).toBeNull();
  });

  it('appears even when "Show notes" is off, and opens the full note on tap', async () => {
    const card = makeCard({ type: 'custom:home-keeper-card' }); // show_notes unset
    card.hass = { callWS: async () => ({ tasks: noted }), language: 'en' };

    await waitFor(() => sr(card)?.querySelector('.hk-note-chip'));
    // The affordance is independent of the inline-notes setting.
    expect(sr(card).querySelector('.hk-notes')).toBeNull();

    sr(card).querySelector('.hk-note-chip').click();
    const shown = await waitFor(() => sr(card)?.querySelector('ha-dialog[open] ha-markdown'));
    expect(shown).toBe(true);
    expect(sr(card).querySelector('ha-dialog[open] ha-markdown').content).toBe(
      'Use a **HEPA** filter',
    );
  });

  it('opens a read-only dialog — no form, no save', async () => {
    const card = makeCard();
    card.hass = { callWS: async () => ({ tasks: noted }), language: 'en' };

    await waitFor(() => sr(card)?.querySelector('.hk-note-chip'));
    sr(card).querySelector('.hk-note-chip').click();
    await waitFor(() => sr(card)?.querySelector('ha-dialog[open]'));

    const dialog = sr(card).querySelector('ha-dialog[open]');
    expect(dialog.querySelector('ha-form')).toBeNull();
    expect(dialog.querySelector('input, textarea')).toBeNull();
  });

  it('does not interfere with the row\'s Done button', async () => {
    const card = makeCard();
    let completes = 0;
    card.hass = {
      language: 'en',
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_tasks') return { tasks: noted };
        if (msg.type === 'home_keeper/complete_task') completes++;
        return {};
      },
    };

    await waitFor(() => sr(card)?.querySelector('.hk-note-chip'));
    sr(card).querySelector('.hk-note-chip').click();
    await new Promise((r) => setTimeout(r, 20));
    expect(completes, 'tapping the note chip must not complete the task').toBe(0);

    const done = sr(card).querySelector('.hk-done');
    expect(done, 'Done stays present and reachable').not.toBeNull();
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

/** A Home Keeper state push that changes the card's state signal, so it refreshes. */
let pushSeq = 0;
function statePush() {
  pushSeq++;
  return {
    'todo.home_keeper_tasks': {
      entity_id: 'todo.home_keeper_tasks',
      state: String(pushSeq),
      last_updated: new Date(Date.now() + pushSeq * 1000).toISOString(),
      attributes: {},
    },
  };
}

describe('HomeKeeperCard event subscription (F09-1)', () => {
  function connection(result) {
    const conn = { calls: 0 };
    conn.subscribeEvents = async () => {
      conn.calls++;
      if (result === 'refuse') throw { code: 'unauthorized', message: 'Unauthorized' };
      return () => {};
    };
    return conn;
  }

  it('F09-1: does not subscribe for a non-admin user', async () => {
    const card = makeCard();
    const conn = connection('ok');
    const callWS = async () => ({ tasks: sampleTasks });
    const user = { is_admin: false };
    card.hass = { callWS, language: 'en', connection: conn, user };
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    card.hass = { callWS, language: 'en', connection: conn, user, states: statePush() };
    await new Promise((r) => setTimeout(r, 30));
    expect(conn.calls).toBe(0);
  });

  it('F09-1: does not try again on a connection that refused the subscription', async () => {
    const card = makeCard();
    const conn = connection('refuse');
    const callWS = async () => ({ tasks: sampleTasks });
    card.hass = { callWS, language: 'en', connection: conn };
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    for (let i = 0; i < 3; i++) {
      card.hass = { callWS, language: 'en', connection: conn, states: statePush() };
      await new Promise((r) => setTimeout(r, 10));
    }
    expect(conn.calls).toBe(1);

    // A new connection (a websocket reconnect) gets one new attempt.
    const fresh = connection('ok');
    card.hass = { callWS, language: 'en', connection: fresh };
    await waitFor(() => fresh.calls === 1);
    expect(fresh.calls).toBe(1);
  });

  it('F09-1: still subscribes for an admin user', async () => {
    const card = makeCard();
    const conn = connection('ok');
    card.hass = {
      callWS: async () => ({ tasks: sampleTasks }),
      language: 'en',
      connection: conn,
      user: { is_admin: true },
    };
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(conn.calls).toBe(1);
  });
});

describe('HomeKeeperCard counted wear progress for a non-admin (F09-2)', () => {
  // The part exactly as `assets.card_projection` sends it to a non-admin: only the
  // allowlisted keys, with no cost, vendor or part number.
  const PROJECTED = {
    id: 'a1',
    documents: [],
    metadata: [],
    parts: [
      {
        id: 'p1',
        name: 'Shell',
        url: null,
        stock: 0,
        reorder_at: 0,
        stock_unit: '',
        replace_interval: 25,
        use_noun: 'wears',
        carried_uses: 17,
      },
    ],
  };
  const useTask = {
    id: 'u1',
    name: 'Wear the jacket',
    recurrence_type: 'use',
    next_due: null,
    completions: [],
    source: { part: { asset_id: 'a1', part_id: 'p1', role: 'use' } },
  };

  it('F09-2: shows "17 of 25 wears" from the projected part', async () => {
    const card = makeCard();
    card.hass = {
      language: 'en',
      user: { is_admin: false },
      callWS: async (msg) =>
        msg.type === 'home_keeper/get_tasks'
          ? { tasks: [useTask] }
          : msg.type === 'home_keeper/get_assets'
            ? { assets: [PROJECTED] }
            : {},
    };
    await waitFor(() => sr(card)?.querySelector('.hk-counted'));
    expect(sr(card).querySelector('.hk-counted')?.getAttribute('label')).toBe('17 of 25 wears');
  });
});

describe('HomeKeeperCard create guard (F05-3)', () => {
  async function openFilledForm(card) {
    await waitFor(() => sr(card)?.querySelector('#hk-add'));
    sr(card).querySelector('#hk-add').click();
    const form = sr(card).querySelector('ha-form');
    form.dispatchEvent(
      new CustomEvent('value-changed', { detail: { value: { ...form.data, name: 'New filter' } } }),
    );
  }

  it('F05-3: a second tap on Create while add_task is in flight adds nothing', async () => {
    const card = makeCard();
    let addCalls = 0;
    let resolveAdd;
    card.hass = {
      language: 'en',
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_tasks') return { tasks: sampleTasks };
        if (msg.type === 'home_keeper/add_task') {
          addCalls++;
          await new Promise((r) => (resolveAdd = r));
          return { task: { id: 'new' } };
        }
        return {};
      },
    };
    await openFilledForm(card);

    const create = sr(card).querySelector('#hk-create');
    expect(create.hasAttribute('disabled')).toBe(false);
    create.click();
    await new Promise((r) => setTimeout(r, 10));
    expect(create.hasAttribute('disabled'), 'Create is disabled while in flight').toBe(true);
    create.click();
    await new Promise((r) => setTimeout(r, 30));
    expect(addCalls, 'only one add_task should be sent').toBe(1);

    resolveAdd?.();
    await waitFor(() => !sr(card).querySelector('.hk-form'));
    expect(sr(card).querySelector('.hk-form')).toBeNull();
  });

  it('F05-3: Create is live again after a failed add', async () => {
    const card = makeCard();
    let addCalls = 0;
    card.hass = {
      language: 'en',
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_tasks') return { tasks: sampleTasks };
        if (msg.type === 'home_keeper/add_task') {
          addCalls++;
          throw new Error('boom');
        }
        return {};
      },
    };
    await openFilledForm(card);
    sr(card).querySelector('#hk-create').click();
    await waitFor(() => sr(card).querySelector('.hk-form ha-alert'));
    const create = sr(card).querySelector('#hk-create');
    expect(create.hasAttribute('disabled')).toBe(false);
    create.click();
    await waitFor(() => addCalls === 2);
    expect(addCalls).toBe(2);
  });

  it('F05-3: a new form after a good add has a live Create', async () => {
    const card = makeCard();
    card.hass = {
      language: 'en',
      callWS: async (msg) =>
        msg.type === 'home_keeper/get_tasks'
          ? { tasks: sampleTasks }
          : msg.type === 'home_keeper/add_task'
            ? { task: { id: 'new' } }
            : {},
    };
    await openFilledForm(card);
    sr(card).querySelector('#hk-create').click();
    await waitFor(() => !sr(card).querySelector('.hk-form'));
    sr(card).querySelector('#hk-add').click();
    expect(sr(card).querySelector('#hk-create').hasAttribute('disabled')).toBe(false);
  });
});

describe('HomeKeeperCard refresh with an open overlay (X11-3)', () => {
  beforeAll(() => {
    if (!customElements.get('ha-dialog')) {
      customElements.define('ha-dialog', class extends HTMLElement {});
    }
  });

  function liveCard(config) {
    const card = makeCard(config);
    const state = { tasks: sampleTasks, gets: 0 };
    const callWS = async (msg) => {
      if (msg.type === 'home_keeper/get_tasks') {
        state.gets++;
        return { tasks: state.tasks };
      }
      return {};
    };
    card.hass = { callWS, language: 'en' };
    const push = () => {
      card.hass = { callWS, language: 'en', states: statePush() };
    };
    return { card, state, push };
  }

  const renamed = [{ ...sampleTasks[0], name: 'Replace filter now' }];

  it('X11-3: keeps the create form in place and updates the list', async () => {
    const { card, state, push } = liveCard();
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    sr(card).querySelector('#hk-add').click();
    const form = sr(card).querySelector('.hk-form');
    const header = sr(card).querySelector('.hk-head');
    expect(form).toBeTruthy();

    state.tasks = renamed;
    const before = state.gets;
    push();
    await waitFor(() => sr(card).textContent.includes('Replace filter now'));

    expect(state.gets).toBeGreaterThan(before);
    expect(sr(card).querySelector('.hk-form'), 'the same form node').toBe(form);
    expect(sr(card).querySelector('.hk-head'), 'the same header node').toBe(header);
    // The new rows are live: Done is wired on them.
    expect(sr(card).querySelector('.hk-done').path).toBeTruthy();
  });

  it('X11-3: keeps an open Snooze dialog in place', async () => {
    const { card, state, push } = liveCard();
    await waitFor(() => sr(card)?.querySelector('.hk-defer-snooze'));
    sr(card).querySelector('.hk-defer-snooze').click();
    const dialog = sr(card).querySelector('ha-dialog');
    expect(dialog).toBeTruthy();

    state.tasks = renamed;
    push();
    await waitFor(() => sr(card).textContent.includes('Replace filter now'));
    expect(sr(card).querySelector('ha-dialog'), 'the same dialog node').toBe(dialog);
    // The new rows are wired: their Snooze button carries its icon.
    expect(sr(card).querySelector('.hk-defer-snooze').path).toBeTruthy();
  });

  it('X11-3: hides the card behind an open form when the list goes empty', async () => {
    const { card, state, push } = liveCard({
      type: 'custom:home-keeper-card',
      hide_when_empty: true,
    });
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    sr(card).querySelector('#hk-add').click();
    expect(card.style.display).toBe('');

    state.tasks = [];
    push();
    await waitFor(() => card.style.display === 'none');
    expect(card.style.display).toBe('none');
  });

  it('X11-3: renders the whole card again when no overlay is open', async () => {
    const { card, state, push } = liveCard();
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    const header = sr(card).querySelector('.hk-head');

    state.tasks = renamed;
    push();
    await waitFor(() => sr(card).textContent.includes('Replace filter now'));
    expect(sr(card).querySelector('.hk-head')).not.toBe(header);
  });
});

describe('HomeKeeperCard profile that is gone (F05-4)', () => {
  const PROFILE = { id: 'p1', name: 'Kid chores', filter: { status: 'all', labels: ['kid'] } };
  const tasks = [
    { ...sampleTasks[0], id: 'a', name: 'Feed the cat', labels: ['kid'] },
    { ...sampleTasks[0], id: 'b', name: 'Clean the gutters' },
  ];

  function hassWith(profiles) {
    return {
      language: 'en',
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_tasks') return { tasks };
        if (msg.type === 'home_keeper/get_profiles') {
          if (profiles === 'fail') throw new Error('not_loaded');
          return { profiles };
        }
        return {};
      },
    };
  }

  it('F05-4: shows a warning and no rows when the profile does not exist', async () => {
    const card = makeCard({
      type: 'custom:home-keeper-card',
      profile: 'p-gone',
      hide_when_empty: true,
    });
    card.hass = hassWith([PROFILE]);
    await waitFor(() => sr(card)?.querySelector('ha-alert'));
    const alert = sr(card).querySelector('ha-alert');
    expect(alert.getAttribute('alert-type')).toBe('warning');
    expect(alert.textContent).toBe(
      'The profile "p-gone" does not exist. Edit the card and select a different profile.',
    );
    expect(sr(card).querySelector('.hk-row')).toBeNull();
    // hide_when_empty does not hide the warning.
    expect(card.style.display).toBe('');
  });

  it('F05-4: applies a profile found by id or by name', async () => {
    for (const ref of ['p1', 'Kid chores']) {
      const card = makeCard({ type: 'custom:home-keeper-card', profile: ref });
      card.hass = hassWith([PROFILE]);
      await waitFor(() => sr(card)?.querySelector('.hk-row'));
      expect(sr(card).textContent).toContain('Feed the cat');
      expect(sr(card).textContent).not.toContain('Clean the gutters');
      expect(sr(card).querySelector('ha-alert')).toBeNull();
    }
  });

  it('F05-4: keeps the last profile list when a later fetch fails', async () => {
    const card = makeCard({ type: 'custom:home-keeper-card', profile: 'p1' });
    card.hass = hassWith([PROFILE]);
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    let fetched = false;
    const failing = hassWith('fail');
    card.hass = {
      ...failing,
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_profiles') fetched = true;
        return failing.callWS(msg);
      },
      states: statePush(),
    };
    await waitFor(() => fetched);
    await new Promise((r) => setTimeout(r, 30));
    expect(sr(card).textContent).toContain('Feed the cat');
    expect(sr(card).textContent).not.toContain('Clean the gutters');
    expect(sr(card).querySelector('ha-alert')).toBeNull();
  });

  it('F05-4: fetches the profiles when setConfig adds a profile', async () => {
    const card = makeCard({ type: 'custom:home-keeper-card' });
    card.hass = hassWith([PROFILE]);
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(sr(card).textContent).toContain('Clean the gutters');
    card.setConfig({ type: 'custom:home-keeper-card', profile: 'p1' });
    await waitFor(() => sr(card).textContent.includes('Feed the cat') && !sr(card).querySelector('ha-alert'));
    expect(sr(card).textContent).toContain('Feed the cat');
    expect(sr(card).textContent).not.toContain('Clean the gutters');
    expect(sr(card).querySelector('ha-alert')).toBeNull();
  });
});

describe('HomeKeeperCard failed Done (F05-5)', () => {
  it('F05-5: shows a toast when the completion fails', async () => {
    const card = makeCard();
    card.hass = {
      language: 'en',
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_tasks') return { tasks: sampleTasks };
        if (msg.type === 'home_keeper/complete_task') throw new Error('save failed');
        return {};
      },
    };
    await waitFor(() => sr(card)?.querySelector('.hk-done'));
    const toasts = [];
    card.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));
    sr(card).querySelector('.hk-done').click();
    await waitFor(() => toasts.length > 0);
    expect(toasts).toEqual(['Something went wrong. Please try again.']);
  });
});

describe('HomeKeeperCard disabled task rail (F05-7)', () => {
  it('F05-7: gives no overdue rail to a disabled task with an old due date', async () => {
    const old = new Date(Date.now() - 5 * 86_400_000).toISOString();
    const card = makeCard({ type: 'custom:home-keeper-card', show_disabled: true });
    card.hass = {
      language: 'en',
      callWS: async () => ({
        tasks: [
          { ...sampleTasks[0], id: 'off', name: 'Pool', enabled: false, next_due: old },
          { ...sampleTasks[0], id: 'late', name: 'Late', next_due: old },
        ],
      }),
    };
    await waitFor(() => sr(card)?.querySelectorAll('.hk-row').length === 2);
    const rows = [...sr(card).querySelectorAll('.hk-row')];
    const byName = (n) => rows.find((r) => r.textContent.includes(n));
    expect(byName('Pool').classList.contains('overdue')).toBe(false);
    expect(byName('Late').classList.contains('overdue')).toBe(true);
  });
});

describe('HomeKeeperCard editor options (F05-9)', () => {
  it('F05-9: offers every card filter and every recurrence type', () => {
    expect(FILTER_OPTS.map((o) => o.value)).toEqual([
      'all',
      'overdue',
      'today',
      'soon',
      'no_due',
      'shopping',
      'counted',
    ]);
    expect(RECURRENCE_OPTS.map((o) => o.value)).toEqual([
      'floating',
      'fixed',
      'triggered',
      'one-off',
      'sensor',
      'use',
    ]);
    for (const o of [...FILTER_OPTS, ...RECURRENCE_OPTS]) expect(o.label).toBeTruthy();
  });
});

describe('HomeKeeperCard to-do item subscription (F09-3)', () => {
  function connection() {
    const conn = { msgs: [], callbacks: [], unsubs: 0 };
    conn.subscribeEvents = async () => () => {};
    conn.subscribeMessage = async (cb, msg) => {
      conn.msgs.push(msg);
      conn.callbacks.push(cb);
      cb({ items: [] }); // Home Assistant sends the current items at once.
      return () => conn.unsubs++;
    };
    return conn;
  }

  it('F09-3: refreshes on a to-do push, also for a non-admin user', async () => {
    let name = 'Replace filter';
    let gets = 0;
    const conn = connection();
    const card = makeCard();
    card.hass = {
      language: 'en',
      user: { is_admin: false },
      connection: conn,
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_tasks') {
          gets++;
          return { tasks: [{ ...sampleTasks[0], name }] };
        }
        return {};
      },
    };
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(conn.msgs).toEqual([
      { type: 'todo/item/subscribe', entity_id: 'todo.home_keeper_tasks' },
    ]);
    await new Promise((r) => setTimeout(r, 30));
    // The first message (the current items) does not cause a second load.
    expect(gets).toBe(1);
    name = 'Replace the HVAC filter';
    conn.callbacks[0]({ items: [] });
    await waitFor(() => sr(card).textContent.includes('Replace the HVAC filter'));
    expect(gets).toBe(2);
    // One subscription per connection.
    card.hass = { ...card.hass, states: statePush() };
    await new Promise((r) => setTimeout(r, 30));
    expect(conn.msgs).toHaveLength(1);
    card.remove();
    expect(conn.unsubs).toBe(1);
  });

  it('F09-3: uses the registry entity id of the Home Keeper to-do list', () => {
    expect(todoEntityId(undefined)).toBe('todo.home_keeper_tasks');
    expect(
      todoEntityId({
        entities: {
          'todo.shopping': { entity_id: 'todo.shopping', platform: 'shopping_list' },
          'sensor.hk': { entity_id: 'sensor.hk', platform: 'home_keeper' },
          'todo.chores': { entity_id: 'todo.chores', platform: 'home_keeper' },
        },
      }),
    ).toBe('todo.chores');
  });

  it('F09-3: does not try again on a connection that refused it', async () => {
    const conn = { calls: 0 };
    conn.subscribeEvents = async () => () => {};
    conn.subscribeMessage = async () => {
      conn.calls++;
      throw { code: 'invalid_entity_id' };
    };
    const card = makeCard();
    const callWS = async () => ({ tasks: sampleTasks });
    card.hass = { callWS, language: 'en', connection: conn };
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    for (let i = 0; i < 3; i++) {
      card.hass = { callWS, language: 'en', connection: conn, states: statePush() };
      await new Promise((r) => setTimeout(r, 10));
    }
    expect(conn.calls).toBe(1);
  });
});
