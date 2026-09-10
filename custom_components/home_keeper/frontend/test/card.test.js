import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { HomeKeeperCard, HomeKeeperCardEditor } from '../src/card.ts';

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
  if (!customElements.get('home-keeper-card-editor')) {
    customElements.define('home-keeper-card-editor', HomeKeeperCardEditor);
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
    const card = makeCard({
      type: 'custom:home-keeper-card',
      groups: [{ labels: ['no-such-label'] }],
    });
    card.hass = { callWS: async () => ({ tasks: sampleTasks }), language: 'en' };

    const shown = await waitFor(() => sr(card)?.querySelector('.hk-empty'));
    expect(shown).toBe(true);
    expect(card.style.display).toBe('');
  });

  it('hides the whole card when configured and nothing matches, and reappears once a task matches', async () => {
    let tasks = [];
    // Deliberately the *legacy* spelling: this is the end-to-end proof that a card
    // stored before filter groups existed still selects the same tasks.
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

describe('HomeKeeperCard monitored rows (issue #231)', () => {
  /** Boot a card holding *tasks* and hand back its shadow root once a row paints. */
  async function rowsFor(tasks) {
    const card = makeCard();
    card.hass = {
      language: 'en',
      callWS: async (msg) =>
        msg.type === 'home_keeper/get_tasks' ? { tasks } : {},
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

// The pre-groups card config, lifted on every load (`liftLegacyCardConfig`). Nothing
// writes the lift back — a card cannot rewrite the dashboard holding it — so the card
// and its editor both lift, and neither ever holds a legacy key. The lift function's
// own cases are in `card-filter.test.js`; these are the two surfaces that call it.
describe('HomeKeeperCard legacy config lift', () => {
  const lift = (config) => makeCard({ type: 'custom:home-keeper-card', ...config })._config;

  it('lifts labels + label_match into one group', () => {
    const config = lift({ labels: ['dog', 'vet'], label_match: 'all' });
    expect(config.groups).toHaveLength(1);
    expect(config.groups[0].labels).toEqual(['dog', 'vet']);
    expect(config.groups[0].labels_match).toBe('all');
    expect('labels' in config).toBe(false);
    expect('label_match' in config).toBe(false);
  });

  it('defaults a missing label_match to any', () => {
    expect(lift({ labels: ['dog'] }).groups[0].labels_match).toBe('any');
  });

  it('lifts areas', () => {
    const config = lift({ areas: ['kitchen'] });
    expect(config.groups[0].areas).toEqual(['kitchen']);
    expect('areas' in config).toBe(false);
  });

  it('lifts devices', () => {
    const config = lift({ devices: ['dev1'] });
    expect(config.groups[0].devices).toEqual(['dev1']);
    expect('devices' in config).toBe(false);
  });

  it('keeps a config that already has groups, dropping stray legacy keys', () => {
    const config = lift({ groups: [{ labels: ['car'] }], labels: ['dog'], areas: ['yard'] });
    expect(config.groups).toEqual([{ labels: ['car'] }]);
    expect('labels' in config).toBe(false);
    expect('areas' in config).toBe(false);
  });

  it('adds no groups key to a card that filters by neither', () => {
    const config = lift({ filter: 'overdue' });
    expect('groups' in config).toBe(false);
  });

  it('filters by the lifted group, not by the dropped keys', async () => {
    const card = makeCard({ type: 'custom:home-keeper-card', labels: ['dog'] });
    const dogTask = { ...sampleTasks[0], id: 'dog', name: 'Walk the dog', labels: ['dog'] };
    card.hass = {
      callWS: async () => ({ tasks: [...sampleTasks, dogTask] }),
      language: 'en',
    };

    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(sr(card).querySelectorAll('.hk-row')).toHaveLength(1);
    expect(sr(card).textContent).toContain('Walk the dog');
  });

  // A profile is the whole selection when one is chosen: it replaces the groups rather
  // than narrowing them, exactly as it replaced the old flat lists.
  it('ignores the card groups when a profile is set', async () => {
    const card = makeCard({
      type: 'custom:home-keeper-card',
      profile: 'p1',
      groups: [{ labels: ['no-such-label'] }],
    });
    card.hass = {
      language: 'en',
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/get_tasks') return { tasks: sampleTasks };
        if (msg.type === 'home_keeper/get_profiles') {
          return { profiles: [{ id: 'p1', name: 'Everything', filter: { status: 'all', groups: [] } }] };
        }
        return {};
      },
    };

    const shown = await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(shown, "the profile's tasks show, not the card group's").toBe(true);
    expect(sr(card).textContent).toContain('Replace filter');
  });
});

// The card's GUI editor. Its groups are the shared `renderGroupsEditor` — the same one
// the panel's profile rows use — so what is checked here is the wiring: what the editor
// holds after a lift, and what it reports back to Lovelace.
describe('HomeKeeperCardEditor filter groups', () => {
  function makeEditor(config = { type: 'custom:home-keeper-card' }) {
    const editor = document.createElement('home-keeper-card-editor');
    editor.setConfig(config);
    document.body.appendChild(editor);
    const emitted = [];
    editor.addEventListener('config-changed', (e) => emitted.push(e.detail.config));
    return { editor, emitted, root: editor.shadowRoot };
  }

  const groupCards = (root) => root.querySelectorAll('.hk-filter-group');
  const addBtn = (root) => root.querySelector('.hk-filter-group-add');

  it('renders just the add button for a card with no groups', () => {
    const { root, emitted } = makeEditor();
    expect(groupCards(root)).toHaveLength(0);
    expect(addBtn(root)).toBeTruthy();
    // An untouched editor writes nothing: no empty group is invented for the config.
    expect(emitted).toEqual([]);
  });

  it('drops the legacy fields from the schema it renders', () => {
    const { root } = makeEditor();
    // This editor has no groups, so every form on it is one of the two config forms —
    // the four legacy pickers are gone from both, and only a group offers them now.
    const names = [...root.querySelectorAll('ha-form')].flatMap((f) =>
      (f.schema ?? []).flatMap((field) => [field.name, ...(field.schema ?? []).map((x) => x.name)]),
    );
    for (const gone of ['labels', 'label_match', 'areas', 'devices']) {
      expect(names, `${gone} should be gone`).not.toContain(gone);
    }
    expect(names).toContain('profile');
    expect(names).toContain('recurrence_types');
    expect(names).toContain('hide_when_empty');
  });

  it('seeds a group from the config and labels its fields in English', () => {
    const { root } = makeEditor({ type: 'custom:home-keeper-card', groups: [{ labels: ['dog'] }] });
    expect(groupCards(root)).toHaveLength(1);
    const form = groupCards(root)[0].querySelector('ha-form');
    expect(form.data.labels).toEqual(['dog']);
    expect(form.data.labels_match).toBe('any');
    expect(form.computeLabel({ name: 'exclude_shopping' })).toBe('Exclude shopping');
    expect(form.computeLabel({ name: 'labels' })).toBe('Labels');
  });

  it('adds one empty group when the add button is pressed', () => {
    const { root, emitted } = makeEditor();
    addBtn(root).click();

    expect(emitted).toHaveLength(1);
    expect(emitted[0].groups).toHaveLength(1);
    expect(emitted[0].groups[0].labels).toEqual([]);
    expect(emitted[0].groups[0].exclude_shopping).toBe(false);
    expect(groupCards(root)).toHaveLength(1);
  });

  it('reports an edit inside a group as the whole config', () => {
    const { root, emitted } = makeEditor({ type: 'custom:home-keeper-card', groups: [{}] });
    const form = groupCards(root)[0].querySelector('ha-form');
    form.dispatchEvent(
      new CustomEvent('value-changed', {
        detail: { value: { ...form.data, areas: ['garage'] } },
      }),
    );

    expect(emitted).toHaveLength(1);
    expect(emitted[0].groups[0].areas).toEqual(['garage']);
    expect(emitted[0].type).toBe('custom:home-keeper-card');
  });

  // The whole point of lifting in the editor too: one switch flipped on an old card
  // saves it in the current spelling, with nothing left of the four legacy keys.
  it('emits a lifted config with no legacy keys after any edit', () => {
    const { root, emitted } = makeEditor({
      type: 'custom:home-keeper-card',
      labels: ['dog'],
      label_match: 'all',
      areas: ['yard'],
      devices: ['dev1'],
    });
    // The lift reaches the group editor: the old lists are showing as one group.
    expect(groupCards(root)).toHaveLength(1);

    const head = root.querySelector('ha-form');
    head.dispatchEvent(
      new CustomEvent('value-changed', { detail: { value: { ...head.data, title: 'Dog jobs' } } }),
    );

    expect(emitted).toHaveLength(1);
    const config = emitted[0];
    expect(config.title).toBe('Dog jobs');
    expect(config.groups).toHaveLength(1);
    expect(config.groups[0]).toMatchObject({
      labels: ['dog'],
      labels_match: 'all',
      areas: ['yard'],
      devices: ['dev1'],
    });
    for (const key of ['labels', 'label_match', 'areas', 'devices']) {
      expect(key in config, `${key} should be gone`).toBe(false);
    }
  });

  // A group's pickers are `ha-form`s: rebuilding them on every keystroke elsewhere in
  // the editor would flicker them, and would drop whatever the user had open.
  it('leaves the group forms standing when a config field changes', () => {
    const { root } = makeEditor({ type: 'custom:home-keeper-card', groups: [{ labels: ['dog'] }] });
    const groupForm = groupCards(root)[0].querySelector('ha-form');
    const head = root.querySelector('ha-form');
    head.dispatchEvent(
      new CustomEvent('value-changed', { detail: { value: { ...head.data, title: 'Dog' } } }),
    );

    expect(groupCards(root)[0].querySelector('ha-form')).toBe(groupForm);
    expect(groupForm.data.labels).toEqual(['dog']);
  });

  // Two forms edit one config, so each has to be re-seeded when the other changes —
  // otherwise the next edit reports the config as it was before the previous one.
  it('keeps an added group when a later edit lands in the config form', () => {
    const { root, emitted } = makeEditor();
    addBtn(root).click();
    const head = root.querySelector('ha-form');
    head.dispatchEvent(
      new CustomEvent('value-changed', { detail: { value: { ...head.data, title: 'Kept' } } }),
    );

    const config = emitted.at(-1);
    expect(config.title).toBe('Kept');
    expect(config.groups).toHaveLength(1);
  });
});
