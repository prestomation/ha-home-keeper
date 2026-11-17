import fc from 'fast-check';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { definePanelStubs, makeHass, waitFor } from './panel-harness.js';
import { switchView } from '../src/panel-settings.ts';
import { buildPath, parseRoute } from '../src/utils.ts';

/**
 * Browser history on the real panel: a model of the history stack against the panel.
 *
 * The model holds the entries and the number of panel pushes below each one. Each
 * command does what a user does: open a page, change a tab or a sub-tab, use the
 * panel's back arrow, or use the browser's Back and Forward. After each command, the
 * URL and the page on screen must be the model's current entry. The ids include
 * `..`, `parts` and a letter outside ASCII, so the URL encoding is in the test too.
 */

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
  localStorage.clear();
  vi.restoreAllMocks();
});

const PREFIX = '/home-keeper';
const TASK_IDS = ['A', '..', 'café'];
const ASSET_IDS = ['X', 'parts', '.'];
const task = (id) => ({
  id,
  name: `Task ${id}`,
  recurrence_type: 'floating',
  interval: 3,
  unit: 'months',
  enabled: true,
});
const asset = (id) => ({ id, name: `Asset ${id}`, parts: [], documents: [] });

const ticks = async () => {
  for (let i = 0; i < 3; i++) await new Promise((r) => setTimeout(r, 0));
};
const routeOf = () => location.pathname.slice(PREFIX.length) || '/';

/** The route path that the browser gives back for a location. */
function pathOf(loc) {
  return new URL(PREFIX + buildPath(loc), 'http://hass.local').pathname.slice(PREFIX.length);
}

async function boot() {
  history.replaceState(null, '', `${PREFIX}/tasks`);
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: PREFIX, path: '/tasks' };
  // Stand in for Home Assistant's router: it answers each URL change with a new route.
  panel.addEventListener('location-changed', () => {
    panel.route = { prefix: PREFIX, path: routeOf() };
  });
  document.body.appendChild(panel);
  panel.hass = makeHass({ tasks: TASK_IDS.map(task), assets: ASSET_IDS.map(asset) });
  await waitFor(() => panel._loaded);
  return panel;
}

/** The browser's Back or Forward: wait for `popstate`, then the router sets the route. */
async function travel(panel, step) {
  await new Promise((resolve) => {
    window.addEventListener('popstate', resolve, { once: true });
    history.go(step);
  });
  panel.route = { prefix: PREFIX, path: routeOf() };
}

const current = (m) => m.stack[m.index];
const push = (m, path) => {
  m.stack = [...m.stack.slice(0, m.index + 1), { path, depth: current(m).depth + 1 }];
  m.index += 1;
};
const replace = (m, path) => {
  m.stack = [...m.stack];
  m.stack[m.index] = { path, depth: current(m).depth };
};
const locOf = (m) => parseRoute(current(m).path);

const cmd = (name, check, run) => ({
  check,
  async run(m, panel) {
    await run(m, panel);
    await ticks();
    expect(location.pathname, `URL after ${name}`).toBe(PREFIX + current(m).path);
    const loc = locOf(m);
    expect(panel._view, `view after ${name}`).toBe(loc.view);
    expect(panel._detail ?? null, `detail after ${name}`).toEqual(loc.detail);
  },
  toString: () => name,
});

const openTask = fc.constantFrom(...TASK_IDS).map((id) =>
  cmd(`OpenTask(${id})`, () => true, (m, panel) => {
    panel._openDetail('task', id);
    push(m, pathOf({ view: 'tasks', detail: { kind: 'task', id } }));
  }),
);
const openAsset = fc.constantFrom(...ASSET_IDS).map((id) =>
  cmd(`OpenAsset(${id})`, () => true, (m, panel) => {
    panel._openDetail('asset', id);
    push(m, pathOf({ view: 'appliances', detail: { kind: 'asset', id } }));
  }),
);
const openPart = fc.constantFrom('..', 'p 1').map((part) =>
  cmd(`OpenPart(${part})`, () => true, (m, panel) => {
    panel._openPart('X', part);
    push(m, pathOf({ view: 'appliances', detail: { kind: 'asset', id: 'X', tab: 'parts', part } }));
  }),
);
const tab = fc.constantFrom('tasks', 'appliances', 'settings').map((view) =>
  cmd(
    `Tab(${view})`,
    // Tapping the open list's own tab does nothing.
    (m) => !(locOf(m).view === view && !locOf(m).detail && !locOf(m).section),
    (m, panel) => {
      switchView(panel, view);
      replace(m, `/${view}`);
    },
  ),
);
const subTab = cmd(
  'SubTab',
  (m) => Boolean(locOf(m).detail),
  (m, panel) => {
    const d = locOf(m).detail;
    if (d.kind === 'task') {
      const next = d.tab === 'history' ? 'notes' : 'history';
      panel._setTaskTab(next);
      replace(m, pathOf({ view: 'tasks', detail: { ...d, tab: next } }));
    } else {
      const next = d.tab === 'documents' ? 'history' : 'documents';
      panel._setAssetTab(next);
      const { part: _part, ...rest } = d;
      replace(m, pathOf({ view: 'appliances', detail: { ...rest, tab: next } }));
    }
  },
);
const closeDetail = cmd(
  'CloseDetail',
  (m) => Boolean(locOf(m).detail),
  async (m, panel) => {
    if (current(m).depth > 0) {
      await new Promise((resolve) => {
        window.addEventListener('popstate', resolve, { once: true });
        panel._closeDetail();
      });
      panel.route = { prefix: PREFIX, path: routeOf() };
      m.index -= 1;
    } else {
      panel._closeDetail();
      replace(m, `/${locOf(m).view}`);
    }
  },
);
const SECTIONS = ['general', 'profiles'];
const openSection = fc.constantFrom(...SECTIONS).map((section) =>
  cmd(
    `IndexRow(${section})`,
    (m) => locOf(m).view === 'settings',
    (m, panel) => {
      // A row of the phone index is a drill-in, so it pushes.
      panel._navigate({ view: 'settings', detail: null, section });
      push(m, `/settings/${section}`);
    },
  ),
);
const railSection = fc.constantFrom(...SECTIONS).map((section) =>
  cmd(
    `Rail(${section})`,
    (m) => locOf(m).view === 'settings',
    (m, panel) => {
      // The rail is a lateral move, so it replaces.
      panel._navigate({ view: 'settings', detail: null, section }, true);
      replace(m, `/settings/${section}`);
    },
  ),
);
const closeSection = cmd(
  'CloseSection',
  (m) => Boolean(locOf(m).section),
  async (m, panel) => {
    // The back arrow of a section always goes to the index. It pops the entry only
    // when the entry below is the index.
    const below = m.index > 0 && current(m).depth > 0 ? m.stack[m.index - 1].path : null;
    if (below === '/settings') {
      await new Promise((resolve) => {
        window.addEventListener('popstate', resolve, { once: true });
        panel._closeSettingsSection();
      });
      panel.route = { prefix: PREFIX, path: routeOf() };
      m.index -= 1;
    } else {
      panel._closeSettingsSection();
      replace(m, '/settings');
    }
  },
);
const back = cmd(
  'Back',
  (m) => m.index > 0,
  async (m, panel) => {
    await travel(panel, -1);
    m.index -= 1;
  },
);
const forward = cmd(
  'Forward',
  (m) => m.index < m.stack.length - 1,
  async (m, panel) => {
    await travel(panel, 1);
    m.index += 1;
  },
);

describe('browser history model on the real panel', () => {
  it('shows the entry that the browser history holds after any sequence', async () => {
    const panel = await boot();
    const runs = Math.max(5, Math.floor(fc.readConfigureGlobal().numRuns / 4));
    await fc.assert(
      fc.asyncProperty(
        fc.commands(
          [
            openTask,
            openAsset,
            openPart,
            tab,
            openSection,
            railSection,
            fc.constant(subTab),
            fc.constant(closeDetail),
            fc.constant(closeSection),
            fc.constant(back),
            fc.constant(forward),
          ],
          { maxCommands: 16 },
        ),
        async (cmds) => {
          // Each run starts on a new entry, so no entry of an earlier run is reachable.
          history.pushState(null, '', `${PREFIX}/tasks`);
          panel.route = { prefix: PREFIX, path: '/tasks' };
          await ticks();
          const model = { stack: [{ path: '/tasks', depth: 0 }], index: 0 };
          await fc.asyncModelRun(() => ({ model, real: panel }), cmds);
        },
      ),
      { numRuns: Number(process.env.HK_HISTORY_RUNS) || runs },
    );
  }, 120_000);

  it('goes back to the list after a tab change, a detail and Back', async () => {
    const panel = await boot();
    switchView(panel, 'appliances');
    await ticks();
    panel._openDetail('asset', 'X');
    await ticks();
    expect(routeOf()).toBe('/appliances/X');
    await travel(panel, -1);
    await ticks();
    expect(routeOf()).toBe('/appliances');
    expect(panel._view).toBe('appliances');
    expect(panel._detail).toBeNull();
  });
});

describe('the back arrow of a settings section', () => {
  it('goes to the index when the entry below was replaced by another page', async () => {
    const panel = await boot();
    switchView(panel, 'settings');
    await ticks();
    panel._navigate({ view: 'settings', detail: null, section: 'general' });
    await ticks();
    await travel(panel, -1);
    await ticks();
    // The entry below the section is now the task list.
    switchView(panel, 'tasks');
    await ticks();
    await travel(panel, 1);
    await ticks();
    expect(routeOf()).toBe('/settings/general');
    const popped = new Promise((resolve) => {
      window.addEventListener('popstate', () => resolve(true), { once: true });
      setTimeout(() => resolve(false), 100);
    });
    panel._closeSettingsSection();
    if (await popped) panel.route = { prefix: PREFIX, path: routeOf() };
    await ticks();
    expect(routeOf()).toBe('/settings');
    expect(panel._view).toBe('settings');
  });
});
