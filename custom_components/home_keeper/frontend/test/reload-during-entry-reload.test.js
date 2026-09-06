import { beforeAll, afterEach, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

/**
 * The panel waits out an unloaded integration instead of keeping what is on screen.
 *
 * Home Keeper reloads its own config entry: adding a declarative companion that
 * matches an entity materializes tasks, and the reconciler reloads the entry to
 * baseline the sensor watcher. The entry is unloaded for a moment in the middle of
 * that, and every Home Keeper websocket command answers `not_loaded` while it is —
 * which is exactly the window the refresh after such a save lands in.
 *
 * `_reload` assigns nothing when the batch fails, so a load that gave up there left
 * the **whole** panel on pre-save data: the task list, the appliances, the options,
 * the companions and the recipes, with no message and nothing to retry it. The only
 * way out was reloading the page by hand.
 *
 * Each test here fails the first few commands the way a reload does, and asserts the
 * panel ends up holding what the store actually has.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const SPEC = {
  id: 'spec-1',
  name: 'Firmware update available',
  description: '',
  enabled: true,
  preset_id: 'firmware_update_available',
  selection: { domain: 'update' },
  trigger: { mode: 'state', state: 'on', clear_on_recover: true },
  task_template: { name_template: '{{ friendly_name }}', notes_template: '' },
  per_entity_overrides: {},
};

/** The error Home Keeper's websocket commands send while the entry is unloaded. */
function notLoaded() {
  const err = new Error("Home Keeper isn't loaded right now.");
  err.code = 'not_loaded';
  return Promise.reject(err);
}

/**
 * A `hass` that answers `not_loaded` to the first *failures* Home Keeper commands and
 * serves the store after that. `calls` counts what actually reached the backend, so a
 * test can tell a retry from a lucky first read.
 */
function makeReloadingHass({ failures = 0, tasks = [], companions = [] } = {}) {
  const state = { remaining: failures, calls: 0 };
  return {
    state,
    hass: {
      language: 'en',
      states: {},
      devices: {},
      callWS(msg) {
        // Only Home Keeper's own commands go through the entry; the core registry
        // commands the panel also reads keep answering during a reload.
        if (String(msg.type).startsWith('home_keeper/')) {
          state.calls += 1;
          if (state.remaining > 0) {
            state.remaining -= 1;
            return notLoaded();
          }
        }
        switch (msg.type) {
          case 'home_keeper/get_tasks':
            return Promise.resolve({ tasks });
          case 'home_keeper/get_assets':
            return Promise.resolve({ assets: [] });
          case 'home_keeper/get_options':
            return Promise.resolve({ options: {} });
          case 'home_keeper/list_declarative_companions':
            return Promise.resolve({ companions });
          case 'frontend/get_user_data':
            return Promise.resolve({
              value: msg.key === 'home_keeper_intro_dismissed',
            });
          default:
            return Promise.resolve({});
        }
      },
    },
  };
}

async function mount(hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = hass;
  return panel;
}

describe('a refresh that lands while the config entry is reloading', () => {
  it('reads the recipe the save added rather than keeping the empty list', async () => {
    // The panel is up and holds nothing yet — the state a user is in when they open
    // the preset picker for the first time.
    const first = makeReloadingHass({});
    const panel = await mount(first.hass);
    expect(await waitFor(() => panel._loaded)).toBe(true);
    expect(panel._declarativeCompanions).toHaveLength(0);

    // The save landed and the reconciler is reloading the entry: the next two reads
    // fail before the store answers.
    const after = makeReloadingHass({ failures: 2, companions: [SPEC] });
    panel.hass = after.hass;
    await panel._refresh();

    expect(panel._declarativeCompanions).toEqual([SPEC]);
    expect(panel._loadError).toBe(false);
    expect(after.state.calls, 'the failed batch should have been read again').toBeGreaterThan(1);
  });

  it('renders the new recipe, so the Companions card is not left empty', async () => {
    const first = makeReloadingHass({});
    const panel = await mount(first.hass);
    expect(await waitFor(() => panel._loaded)).toBe(true);

    const after = makeReloadingHass({ failures: 1, companions: [SPEC] });
    panel.hass = after.hass;
    await panel._refresh();

    const rows = panel.shadowRoot.querySelectorAll('.hk-decl-row');
    expect(rows).toHaveLength(1);
    expect(rows[0].getAttribute('data-spec-id')).toBe('spec-1');
  });

  it('carries every other list across the same window, not just the recipes', async () => {
    const first = makeReloadingHass({});
    const panel = await mount(first.hass);
    expect(await waitFor(() => panel._loaded)).toBe(true);
    expect(panel._tasks).toHaveLength(0);

    // A recipe materializes tasks, so the task list is stale in the same window —
    // the report was that *every* list on the panel stayed behind.
    const task = { id: 't1', name: 'Firmware update available: Router', enabled: true };
    const after = makeReloadingHass({ failures: 2, tasks: [task], companions: [SPEC] });
    panel.hass = after.hass;
    await panel._refresh();

    expect(panel._tasks).toEqual([task]);
  });

  it('gives up on an error that is not a reload, rather than retrying it', async () => {
    const first = makeReloadingHass({});
    const panel = await mount(first.hass);
    expect(await waitFor(() => panel._loaded)).toBe(true);

    let calls = 0;
    panel.hass = {
      language: 'en',
      states: {},
      devices: {},
      callWS(msg) {
        if (msg.type === 'home_keeper/get_tasks') {
          calls += 1;
          return Promise.reject(new Error('boom'));
        }
        return Promise.resolve({});
      },
    };
    await panel._refresh();

    expect(calls, 'a plain failure is not waited out').toBe(1);
    expect(panel._loadError).toBe(true);
  });
});
