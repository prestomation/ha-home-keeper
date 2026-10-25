import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { definePanelStubs, emitChange, waitFor } from './panel-harness.js';
import { tabModuleLoader } from '../src/panel-tabs.ts';

definePanelStubs();

let urlSeq = 0;

/** A tab whose module URL is new for each test, so the import cache never answers. */
function makeTab(over = {}) {
  urlSeq += 1;
  return {
    id: 'library',
    companion: 'home_keeper_library',
    title: 'Library',
    icon: 'mdi:bookshelf',
    module_url: `/lib_static/tab-${urlSeq}.js?v=1`,
    element: 'home-keeper-test-tab',
    host_api: 1,
    order: 100,
    ...over,
  };
}

class TestTab extends HTMLElement {}
if (!customElements.get('home-keeper-test-tab')) {
  customElements.define('home-keeper-test-tab', TestTab);
}

function makeHass({ tabs = [], options = {}, companions = [] } = {}) {
  const calls = [];
  return {
    calls,
    language: 'en',
    states: {},
    devices: {},
    callWS(msg) {
      calls.push(msg);
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks: [] });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [] });
        case 'home_keeper/get_options':
          return Promise.resolve({ options });
        case 'home_keeper/set_options':
          Object.assign(options, msg.options);
          return Promise.resolve({ options });
        case 'home_keeper/get_panel_tabs':
          return Promise.resolve({ tabs });
        case 'home_keeper/get_companions':
          return Promise.resolve({ companions });
        case 'frontend/get_user_data':
          return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
        default:
          return Promise.resolve({});
      }
    },
  };
}

async function mount(path, hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  panel.hass = hass;
  // The panel answers `location-changed` the way Home Assistant does: it reads the
  // URL that `_navigate` wrote and sets the route.
  panel.addEventListener('location-changed', () => {
    panel.route = {
      prefix: '/home-keeper',
      path: location.pathname.replace(/^\/home-keeper/, ''),
    };
  });
  await waitFor(() => panel.shadowRoot?.querySelector('.hk-toolbar'));
  return panel;
}

const tabEl = (panel) => panel.shadowRoot.querySelector('#hk-tab-host home-keeper-test-tab');

describe('companion panel tabs', () => {
  let load;
  beforeEach(() => {
    history.replaceState(null, '', '/home-keeper');
    load = vi.spyOn(tabModuleLoader, 'load').mockImplementation(() => Promise.resolve({}));
  });
  afterEach(() => {
    load.mockRestore();
    document.body.innerHTML = '';
  });

  it('puts the tab between Appliances and Settings in both tab bars', async () => {
    const hass = makeHass({ tabs: [makeTab()] });
    const panel = await mount('/tasks', hass);
    await waitFor(() => panel.shadowRoot.querySelector('#tab-x-library'));
    const top = [...panel.shadowRoot.querySelectorAll('ha-tab-group-tab')].map((x) => x.id);
    expect(top).toEqual(['tab-tasks', 'tab-appliances', 'tab-x-library', 'tab-settings']);
    const bottom = [...panel.shadowRoot.querySelectorAll('.hk-bottomtab')].map((x) => x.id);
    expect(bottom).toEqual(['mtab-tasks', 'mtab-appliances', 'mtab-x-library', 'mtab-settings']);
    expect(panel.shadowRoot.querySelector('#mtab-x-library').textContent).toContain('Library');
    expect(load).not.toHaveBeenCalled();
    expect(hass.calls.find((m) => m.type === 'home_keeper/get_panel_tabs')).toEqual({
      type: 'home_keeper/get_panel_tabs',
      language: 'en',
    });
  });

  it('loads the module on the first open and gives the element its properties', async () => {
    const tab = makeTab();
    const hass = makeHass({ tabs: [tab] });
    const panel = await mount('/library/books/12', hass);
    const el = await waitFor(() => tabEl(panel));
    expect(el).toBeInstanceOf(TestTab);
    expect(load).toHaveBeenCalledWith(tab.module_url);
    expect(el.route).toEqual({ path: '/books/12' });
    expect(el.hass).toBe(hass);
    expect(el.narrow).toBe(false);
    expect(el.host.apiVersion).toBe(1);
    expect(Object.isFrozen(el.host)).toBe(true);
    expect(el.host.taskLink('t 1')).toBe('/home-keeper/tasks/t%201');
    expect(el.host.applianceLink('a1')).toBe('/home-keeper/appliances/a1');
    expect(panel.shadowRoot.querySelector('#tab-x-library').hasAttribute('active')).toBe(true);

    panel.narrow = true;
    expect(el.narrow).toBe(true);
    const next = { ...hass };
    panel.hass = next;
    expect(el.hass).toBe(next);
  });

  it('navigates inside the tab with no redraw, and keeps 1 element', async () => {
    const hass = makeHass({ tabs: [makeTab()] });
    const panel = await mount('/library', hass);
    const el = await waitFor(() => tabEl(panel));
    const toolbar = panel.shadowRoot.querySelector('.hk-toolbar');
    const push = vi.spyOn(history, 'pushState');

    el.host.navigate('/sub');
    expect(push).toHaveBeenCalledWith(expect.anything(), '', '/home-keeper/library/sub');
    expect(el.route).toEqual({ path: '/sub' });
    expect(panel.shadowRoot.querySelector('.hk-toolbar')).toBe(toolbar);

    el.host.navigate('../../config', { replace: true });
    expect(location.pathname).toBe('/home-keeper/library/config');

    panel._render();
    expect(tabEl(panel)).toBe(el);
    expect(load).toHaveBeenCalledTimes(1);
    push.mockRestore();
  });

  it('opens a task page and an appliance page through the host', async () => {
    const hass = makeHass({ tabs: [makeTab()] });
    const panel = await mount('/library', hass);
    const el = await waitFor(() => tabEl(panel));
    const push = vi.spyOn(history, 'pushState');
    el.host.openTask('t 1');
    expect(push).toHaveBeenLastCalledWith(expect.anything(), '', '/home-keeper/tasks/t%201');
    expect(panel._view).toBe('tasks');
    el.host.openAppliance('a1');
    expect(push).toHaveBeenLastCalledWith(expect.anything(), '', '/home-keeper/appliances/a1');
    expect(panel._view).toBe('appliances');
    push.mockRestore();
  });

  it('opens a plain left click on a Home Keeper link in the tab with no page load', async () => {
    const hass = makeHass({ tabs: [makeTab()] });
    const panel = await mount('/library', hass);
    const el = await waitFor(() => tabEl(panel));
    const root = el.shadowRoot ?? el.attachShadow({ mode: 'open' });
    root.innerHTML = `
      <a id="in" href="/home-keeper/library/linked"><span id="inner">Linked</span></a>
      <a id="out" href="/config/integrations">Out</a>
      <a id="blank" href="/home-keeper/tasks" target="_blank">New</a>
      <a id="handled" href="/home-keeper/tasks">Handled</a>`;
    root.getElementById('handled').addEventListener('click', (e) => e.preventDefault());
    const click = (id, init = {}) => {
      const ev = new MouseEvent('click', { bubbles: true, composed: true, cancelable: true, ...init });
      root.getElementById(id).dispatchEvent(ev);
      return ev;
    };

    const inner = new MouseEvent('click', { bubbles: true, composed: true, cancelable: true });
    root.getElementById('inner').dispatchEvent(inner);
    expect(inner.defaultPrevented).toBe(true);
    expect(location.pathname).toBe('/home-keeper/library/linked');
    expect(el.route).toEqual({ path: '/linked' });

    expect(click('out').defaultPrevented).toBe(false);
    expect(click('blank').defaultPrevented).toBe(false);
    expect(click('in', { ctrlKey: true }).defaultPrevented).toBe(false);
    expect(click('in', { metaKey: true }).defaultPrevented).toBe(false);
    expect(click('in', { shiftKey: true }).defaultPrevented).toBe(false);
    expect(click('in', { altKey: true }).defaultPrevented).toBe(false);
    expect(click('in', { button: 1 }).defaultPrevented).toBe(false);
    click('handled');
    expect(location.pathname).toBe('/home-keeper/library/linked');
  });

  it('keeps the element after a move to another tab and back', async () => {
    const hass = makeHass({ tabs: [makeTab()] });
    const panel = await mount('/library/a', hass);
    const el = await waitFor(() => tabEl(panel));
    panel.route = { prefix: '/home-keeper', path: '/tasks' };
    expect(tabEl(panel)).toBeNull();
    panel.route = { prefix: '/home-keeper', path: '/library/b' };
    expect(tabEl(panel)).toBe(el);
    expect(el.route).toEqual({ path: '/b' });
  });

  it('opens the tab root from the tab bar', async () => {
    const hass = makeHass({ tabs: [makeTab()] });
    const panel = await mount('/tasks', hass);
    const tab = await waitFor(() => panel.shadowRoot.querySelector('#tab-x-library'));
    tab.click();
    expect(location.pathname).toBe('/home-keeper/library');
    expect(await waitFor(() => tabEl(panel))).toBeTruthy();
  });

  it('asks for an update when the tab needs a newer host API', async () => {
    const hass = makeHass({ tabs: [makeTab({ host_api: 2 })] });
    const panel = await mount('/library', hass);
    const alert = await waitFor(() => panel.shadowRoot.querySelector('#hk-tab-host ha-alert'));
    expect(alert.getAttribute('alert-type')).toBe('warning');
    expect(alert.textContent).toBe('Update Home Keeper to use the Library tab.');
    expect(load).not.toHaveBeenCalled();
  });

  it('shows an error with Retry when the import fails, and Retry imports again', async () => {
    const tab = makeTab();
    load.mockImplementationOnce(() => Promise.reject(new Error('404')));
    const err = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const hass = makeHass({ tabs: [tab] });
    const panel = await mount('/library', hass);
    const retry = await waitFor(() => panel.shadowRoot.querySelector('#hk-tab-retry'));
    expect(panel.shadowRoot.querySelector('#hk-tab-host ha-alert').textContent).toBe(
      'The Library tab did not load.',
    );
    // The rest of the panel still works: the tab bar is there.
    expect(panel.shadowRoot.querySelector('#tab-tasks')).toBeTruthy();
    retry.click();
    expect(await waitFor(() => tabEl(panel))).toBeTruthy();
    expect(load).toHaveBeenLastCalledWith(`${tab.module_url}&hk_retry=1`);
    err.mockRestore();
  });

  it('shows an error when the module does not define the element in time', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const err = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const hass = makeHass({ tabs: [makeTab({ element: 'home-keeper-never-defined' })] });
    const panel = await mount('/library', hass);
    await vi.advanceTimersByTimeAsync(10500);
    expect(await waitFor(() => panel.shadowRoot.querySelector('#hk-tab-retry'))).toBeTruthy();
    err.mockRestore();
    vi.useRealTimers();
  });

  it('goes to the task list for an unknown tab id after the load', async () => {
    const hass = makeHass({ tabs: [makeTab()] });
    const panel = await mount('/garden/x', hass);
    await waitFor(() => panel.shadowRoot.querySelector('#add-btn'));
    expect(location.pathname).toBe('/home-keeper/tasks');
    expect(panel._view).toBe('tasks');
  });

  it('leaves a hidden tab out of the tab bar and sends its URL to the task list', async () => {
    const hass = makeHass({ tabs: [makeTab()], options: { hidden_panel_tabs: ['library'] } });
    const panel = await mount('/library', hass);
    await waitFor(() => panel.shadowRoot.querySelector('#add-btn'));
    expect(panel.shadowRoot.querySelector('#tab-x-library')).toBeNull();
    expect(panel.shadowRoot.querySelector('#mtab-x-library')).toBeNull();
    expect(location.pathname).toBe('/home-keeper/tasks');
    expect(load).not.toHaveBeenCalled();
  });
});

describe('the companion row of a panel tab', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  const companion = {
    domain: 'home_keeper_library',
    name: 'Home Keeper Library',
    status: 'connected',
  };

  it('shows the Panel tab chip and a switch that hides the tab', async () => {
    const hass = makeHass({ tabs: [makeTab()], companions: [companion] });
    const panel = await mount('/settings/companions', hass);
    const slot = await waitFor(() =>
      panel.shadowRoot.querySelector('.hk-comp-tab-switch[data-panel-tab-id="library"]'),
    );
    const row = slot.closest('.hk-companion');
    expect(row.querySelector('ha-assist-chip.hk-comp-tab').getAttribute('label')).toBe('Panel tab');
    const form = slot.querySelector('ha-form');
    expect(form.data).toEqual({ library: true });
    expect(form.schema).toEqual([{ name: 'library', selector: { boolean: {} } }]);
    expect(form.computeLabel({ name: 'library' })).toBe('Show Library tab');

    emitChange(form, { library: false });
    await waitFor(() => hass.calls.some((m) => m.type === 'home_keeper/set_options'));
    const set = hass.calls.find((m) => m.type === 'home_keeper/set_options');
    expect(set.options).toEqual({ hidden_panel_tabs: ['library'] });
    await waitFor(() => !panel.shadowRoot.querySelector('#tab-x-library'));
    expect(panel.shadowRoot.querySelector('#tab-x-library')).toBeNull();
  });

  it('shows the tab again with the switch on', async () => {
    const hass = makeHass({
      tabs: [makeTab()],
      companions: [companion],
      options: { hidden_panel_tabs: ['garden', 'library'] },
    });
    const panel = await mount('/settings/companions', hass);
    const form = await waitFor(() =>
      panel.shadowRoot.querySelector('.hk-comp-tab-switch[data-panel-tab-id="library"] ha-form'),
    );
    expect(form.data).toEqual({ library: false });
    emitChange(form, { library: true });
    await waitFor(() => hass.calls.some((m) => m.type === 'home_keeper/set_options'));
    const set = hass.calls.find((m) => m.type === 'home_keeper/set_options');
    expect(set.options).toEqual({ hidden_panel_tabs: ['garden'] });
  });

  it('gives a tab owner with no companion row a row of its own', async () => {
    const hass = makeHass({ tabs: [makeTab()], companions: [] });
    const panel = await mount('/settings/companions', hass);
    const slot = await waitFor(() => panel.shadowRoot.querySelector('.hk-comp-tab-switch'));
    const row = slot.closest('.hk-companion');
    expect(row.querySelector('.hk-companion-name').textContent).toContain('home_keeper_library');
    expect(row.querySelector('ha-icon').getAttribute('icon')).toBe('mdi:bookshelf');
  });

  it('shows no chip on a companion with no tab', async () => {
    const hass = makeHass({ tabs: [], companions: [companion] });
    const panel = await mount('/settings/companions', hass);
    await waitFor(() => panel.shadowRoot.querySelector('.hk-companion'));
    expect(panel.shadowRoot.querySelector('.hk-comp-tab')).toBeNull();
    expect(panel.shadowRoot.querySelector('.hk-comp-tab-switch')).toBeNull();
  });
});
