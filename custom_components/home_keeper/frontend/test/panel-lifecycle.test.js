import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import {
  definePanelStubs,
  focusField,
  makeHass,
  mountPanel,
  stubLazyMarkdown,
  waitFor,
} from './panel-harness.js';
import { openSkip } from '../src/panel-defer.ts';

/**
 * Panel lifecycle and navigation: Back after a deep link, renders after unmount, the
 * `narrow` flag, the saved filter, and the late Markdown upgrade over a dialog.
 *
 * Own file for the Markdown test: a custom element cannot be un-registered, so it
 * needs a registry that has never seen `ha-markdown`. It runs first for that reason.
 */

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
  localStorage.clear();
  vi.restoreAllMocks();
});

const PREFIX = '/home-keeper';
const task = {
  id: 'A',
  name: 'Change filter',
  recurrence_type: 'floating',
  interval: 3,
  unit: 'months',
  enabled: true,
};

describe('F10-4: a late Markdown upgrade waits while the skip dialog is open', () => {
  it('keeps the skip dialog and its focused field', async () => {
    const registerMarkdown = stubLazyMarkdown();
    const { panel } = await mountPanel('/tasks', makeHass({ tasks: [task] }));
    openSkip(panel, task);
    const host = panel.shadowRoot.getElementById('hk-dialog-host');
    const dialog = await waitFor(() => host?.firstElementChild);
    expect(dialog, 'the skip dialog should render').toBeTruthy();
    const input = focusField(dialog);

    registerMarkdown();
    await waitFor(() => customElements.get('ha-markdown'));
    await new Promise((r) => setTimeout(r, 50));

    expect(panel.shadowRoot.getElementById('hk-dialog-host')).toBe(host);
    expect(host.firstElementChild).toBe(dialog);
    expect(panel.shadowRoot.activeElement).toBe(input);
  });
});

/** Boot on *path* with a stand-in for HA's router, as `upload.test.js` does. */
async function bootRouted(path, hass) {
  history.replaceState(null, '', `${PREFIX}${path}`);
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: PREFIX, path };
  panel.addEventListener('location-changed', () => {
    panel.route = { prefix: PREFIX, path: location.pathname.slice(PREFIX.length) || '/' };
  });
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel._loaded);
  return panel;
}

/** Go back one entry, as the browser does, and feed the new path to the panel. */
async function browserBack(panel) {
  await new Promise((resolve) => {
    window.addEventListener('popstate', resolve, { once: true });
    history.back();
  });
  panel.route = { prefix: PREFIX, path: location.pathname.slice(PREFIX.length) || '/' };
}

describe('F01-3: in-panel Back after a deep link', () => {
  const asset = { id: 'X', name: 'Washer', parts: [], documents: [] };

  it('goes to the list, not out of the panel, after a drill-in and a pop back', async () => {
    const panel = await bootRouted('/tasks/A', makeHass({ tasks: [task], assets: [asset] }));
    panel._navigate({ view: 'appliances', detail: { kind: 'asset', id: 'X' } });
    expect(location.pathname).toBe(`${PREFIX}/appliances/X`);
    await browserBack(panel);
    expect(location.pathname).toBe(`${PREFIX}/tasks/A`);

    const back = vi.spyOn(history, 'back');
    panel._closeDetail();
    expect(back).not.toHaveBeenCalled();
    expect(location.pathname).toBe(`${PREFIX}/tasks`);
  });

  it('still pops an entry that the panel pushed', async () => {
    const panel = await bootRouted('/tasks/A', makeHass({ tasks: [task], assets: [asset] }));
    panel._navigate({ view: 'appliances', detail: { kind: 'asset', id: 'X' } });
    // A lateral move (a sub-tab) keeps the depth.
    panel._navigate({ view: 'appliances', detail: { kind: 'asset', id: 'X', tab: 'documents' } }, true);
    const back = vi.spyOn(history, 'back').mockImplementation(() => {});
    panel._closeDetail();
    expect(back).toHaveBeenCalledTimes(1);
  });

  it('pops a settings section only when the index is below it', async () => {
    const panel = await bootRouted('/settings', makeHass());
    panel._navigate({ view: 'settings', detail: null, section: 'notifications' });
    // The rail is a replace, so the index is still below.
    panel._navigate({ view: 'settings', detail: null, section: 'profiles' }, true);
    const back = vi.spyOn(history, 'back').mockImplementation(() => {});
    panel._closeSettingsSection();
    expect(back).toHaveBeenCalledTimes(1);
    back.mockClear();

    // A section on top of a task page: Back goes to the index, not to the task.
    history.replaceState(null, '', `${PREFIX}/tasks`);
    panel._navigate({ view: 'tasks', detail: { kind: 'task', id: 'A' } });
    panel._navigate({ view: 'settings', detail: null, section: 'profiles' }, true);
    panel._closeSettingsSection();
    expect(back).not.toHaveBeenCalled();
    expect(location.pathname).toBe(`${PREFIX}/settings`);
  });
});

describe('F01-6: a panel that is not connected does not render', () => {
  it('leaves the detached tree alone and arms no timer', async () => {
    const hass = makeHass({ tasks: [task] });
    const callWS = hass.callWS;
    hass.callWS = (msg) =>
      msg.type === 'home_keeper/sign_document_url'
        ? Promise.resolve({ url: '/signed' })
        : callWS(msg);
    const { panel } = await mountPanel('/tasks', hass);
    const list = panel.shadowRoot.querySelector('#hk-list');
    const upload = new AbortController();
    panel._uploadAbort = upload;
    panel._uploadShowTimer = setTimeout(() => {}, 100000);

    panel.remove();
    expect(upload.signal.aborted, 'unmount aborts the upload in flight').toBe(true);
    expect(panel._uploadShowTimer).toBeUndefined();

    panel._render();
    expect(panel.shadowRoot.querySelector('#hk-list')).toBe(list);
    expect(panel._sheetQuery).toBeNull();

    // A sign that ends after unmount does not arm the re-sign timer.
    panel._assetEdit = {
      ...panel._assetEdit,
      asset: { id: 'X', documents: [{ id: 'd1', kind: 'file', name: 'Manual' }] },
    };
    await panel._signFiles();
    expect(panel._resignTimer).toBeNull();

    // Attached again, it renders again.
    document.body.appendChild(panel);
    await waitFor(() => panel.shadowRoot.querySelector('#hk-list') !== list);
    expect(panel.shadowRoot.querySelector('#hk-list')).not.toBe(list);
  });
});

describe('F01-7: narrow reaches the mounted menu button', () => {
  it('updates the button in place when Home Assistant changes narrow', async () => {
    const { panel } = await mountPanel('/tasks', makeHass());
    const mb = panel.shadowRoot.querySelector('ha-menu-button');
    expect(mb, 'the toolbar should hold a menu button').toBeTruthy();
    expect(mb.narrow).toBe(false);
    panel.narrow = true;
    expect(panel.narrow).toBe(true);
    expect(panel.shadowRoot.querySelector('ha-menu-button')).toBe(mb);
    expect(mb.narrow).toBe(true);
    panel.narrow = false;
    expect(mb.narrow).toBe(false);
  });
});

describe('F01-8: the saved Counted filter is restored', () => {
  it('keeps Counted across a reload', async () => {
    localStorage.setItem('home-keeper.filter', 'counted');
    const { panel } = await mountPanel('/tasks', makeHass());
    expect(panel._filter).toBe('counted');
  });
});

describe('X12-7: the panel loads again after a change on another surface', () => {
  /** A hass whose get_tasks calls are counted, and a way to push new entity states. */
  async function setup() {
    const hass = makeHass({ tasks: [task] });
    let loads = 0;
    const callWS = hass.callWS;
    hass.callWS = (msg) => {
      if (msg.type === 'home_keeper/get_tasks') loads++;
      return callWS(msg);
    };
    const { panel } = await mountPanel('/tasks', hass);
    const push = (stamp) => {
      panel.hass = {
        ...hass,
        states: { 'todo.home_keeper_tasks': { last_updated: stamp } },
      };
    };
    return { panel, push, loads: () => loads };
  }

  it('loads again when the Home Keeper entities change', async () => {
    const { panel, push, loads } = await setup();
    expect(loads()).toBe(1);
    // An unrelated hass push does not load.
    panel.hass = { ...panel.hass };
    expect(loads()).toBe(1);
    panel._reloadedAt = 0;
    push('2026-10-01T10:00:00Z');
    await waitFor(() => loads() === 2);
    expect(loads()).toBe(2);
    // The same fingerprint again does not load again.
    await waitFor(() => !panel._refreshing);
    panel._reloadedAt = 0;
    push('2026-10-01T10:00:00Z');
    expect(loads()).toBe(1 + 1);
  });

  it('waits while a form is open, and loads on the first push after it closes', async () => {
    const { panel, push, loads } = await setup();
    panel._reloadedAt = 0;
    panel._openEdit(task);
    push('2026-10-01T11:00:00Z');
    expect(loads()).toBe(1);
    panel._closeForm();
    panel._reloadedAt = 0;
    push('2026-10-01T11:00:00Z');
    await waitFor(() => loads() === 2);
    expect(loads()).toBe(2);
  });

  it('takes a change right after its own load as the echo of that load', async () => {
    const { panel, push, loads } = await setup();
    // `_reloadedAt` is now: the initial load just ended.
    push('2026-10-01T12:00:00Z');
    expect(loads()).toBe(1);
    // The echo is consumed, so it does not load later either.
    panel._reloadedAt = 0;
    push('2026-10-01T12:00:00Z');
    expect(loads()).toBe(1);
  });
});
