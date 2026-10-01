/**
 * The preset suggestions on the Tasks tab: the one-time dialog, then the card.
 *
 * The rules for which presets to show are unit-tested in `preset-nudge.test.js`.
 * This file checks the panel around them: when the dialog opens and when it must not,
 * what each button saves, and that a dismissal follows the user to a new browser.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

beforeAll(definePanelStubs);
afterEach(() => {
  document.body.innerHTML = '';
});

const NUDGE = 'home_keeper_preset_nudge';
const INTRO = 'home_keeper_intro_dismissed';

/** A default spec with the shape the Add dialog reads. */
const spec = (name, presetId, selection) => ({
  name,
  description: '',
  enabled: true,
  preset_id: presetId,
  selection: { area_ids: [], label_ids: [], exclude_entity_ids: [], ...selection },
  trigger: { mode: 'state', state: 'on', clear_on_recover: true },
  task_template: { name_template: 'Update {{ friendly_name }}', notes_template: '', labels: [] },
  per_entity_overrides: {},
});

const FIRMWARE = {
  id: 'firmware_update_available',
  name: 'Firmware update available',
  description: 'Watches every update entity.',
  icon: 'mdi:update',
  requires_integration: null,
  default_spec: spec('Firmware update available', 'firmware_update_available', {
    domain: 'update',
  }),
  matches: 1,
};
const STOPPED = {
  id: 'device_stopped_reporting',
  name: 'Device stopped reporting',
  description: 'Watches every last-seen sensor.',
  icon: 'mdi:access-point-off',
  requires_integration: null,
  default_spec: spec('Device stopped reporting', 'device_stopped_reporting', {
    domain: 'sensor',
    entity_regex: '.*_last_seen$',
  }),
  matches: 9,
};

/**
 * A `hass` for the suggestions. *store* backs the per-user data, shared between two
 * mocks to act as one user on two browsers. *addFailures* is a list of errors the
 * next adds throw, in order (`null` for a success).
 */
function makeHass({
  presets = [FIRMWARE],
  companions = [],
  store = { [INTRO]: true },
  addFailures = [],
  userDataFails = false,
} = {}) {
  const calls = { adds: [], sets: [], getTasks: 0 };
  const hass = {
    language: 'en',
    states: {},
    devices: {},
    callWS(msg) {
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          calls.getTasks += 1;
          return Promise.resolve({ tasks: [] });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [] });
        case 'home_keeper/get_options':
          return Promise.resolve({ options: {} });
        case 'home_keeper/list_declarative_presets':
          return Promise.resolve({ presets });
        case 'home_keeper/list_declarative_companions':
          return Promise.resolve({ companions });
        case 'home_keeper/add_declarative_companion': {
          calls.adds.push(msg.companion);
          const failure = addFailures.shift();
          if (failure) return Promise.reject(failure);
          companions.push({ id: `c${calls.adds.length}`, ...msg.companion });
          return Promise.resolve({ companion: msg.companion });
        }
        case 'frontend/get_user_data':
          if (userDataFails && msg.key === NUDGE) return Promise.reject(new Error('down'));
          return Promise.resolve({ value: store[msg.key] ?? null });
        case 'frontend/set_user_data':
          store[msg.key] = msg.value;
          calls.sets.push({ key: msg.key, value: msg.value });
          return Promise.resolve({});
        default:
          return Promise.resolve({});
      }
    },
  };
  return { hass, calls, store };
}

async function mount(hass, path = '') {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  const toasts = [];
  panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('#hk-dialog-host'));
  // One more turn, so the first load's render has landed.
  await waitFor(() => panel._declarativePresets !== null);
  await new Promise((r) => setTimeout(r, 30));
  return { panel, toasts };
}

const $ = (panel, sel) => panel.shadowRoot.querySelector(sel);
const $$ = (panel, sel) => [...panel.shadowRoot.querySelectorAll(sel)];
const dialog = (panel) => $(panel, 'ha-dialog.hk-preset-dialog');
const card = (panel) => $(panel, '.hk-preset-nudge');

describe('the one-time dialog', () => {
  it('opens with a checked row per usable preset and marks them shown', async () => {
    const { hass, store } = makeHass({ presets: [FIRMWARE, STOPPED] });
    const { panel } = await mount(hass);

    const dlg = await waitFor(() => dialog(panel));
    expect(dlg).toBeTruthy();
    const boxes = [...dlg.querySelectorAll('input[type=checkbox]')];
    expect(boxes.map((b) => [b.dataset.presetId, b.checked])).toEqual([
      ['firmware_update_available', true],
      ['device_stopped_reporting', true],
    ]);
    const counts = [...dlg.querySelectorAll('.hk-preset-pick-count')].map((e) => e.textContent);
    expect(counts).toEqual(['1 entity matches', '9 entities match']);
    expect(dlg.querySelector('.hk-preset-dialog-add').textContent).toBe('Add 2 presets');
    // ha-dialog-footer shows only its named slots.
    expect(dlg.querySelector('.hk-preset-dialog-add').getAttribute('slot')).toBe('primaryAction');
    expect(dlg.querySelector('.hk-preset-dialog-later').getAttribute('slot')).toBe(
      'secondaryAction',
    );
    // The card waits behind the dialog.
    expect(card(panel)).toBeNull();
    await waitFor(() => store[NUDGE]);
    expect(store[NUDGE]).toEqual({
      shown: ['firmware_update_available', 'device_stopped_reporting'],
      dismissed: [],
    });
  });

  it('Not now closes it and the card shows the same presets', async () => {
    const { hass } = makeHass({ presets: [FIRMWARE, STOPPED] });
    const { panel } = await mount(hass);
    (await waitFor(() => dialog(panel))).querySelector('.hk-preset-dialog-later').click();

    expect(dialog(panel)).toBeNull();
    const rows = $$(panel, '.hk-preset-nudge-row').map((r) => r.dataset.presetId);
    expect(rows).toEqual(['firmware_update_available', 'device_stopped_reporting']);
    expect($(panel, '.hk-preset-nudge-count').textContent).toBe('1 entity matches');
  });

  it('closing it with the X is the same as Not now', async () => {
    const { hass } = makeHass();
    const { panel } = await mount(hass);
    const dlg = await waitFor(() => dialog(panel));
    dlg.dispatchEvent(new Event('closed'));
    expect(dialog(panel)).toBeNull();
    expect(card(panel)).toBeTruthy();
  });

  it('does not open again once every preset was offered', async () => {
    const { hass } = makeHass({
      store: { [INTRO]: true, [NUDGE]: { shown: ['firmware_update_available'], dismissed: [] } },
    });
    const { panel } = await mount(hass);
    expect(dialog(panel)).toBeNull();
    expect(card(panel)).toBeTruthy();
  });

  it('opens again for a preset that is new to the user', async () => {
    const { hass } = makeHass({
      presets: [FIRMWARE, STOPPED],
      store: { [INTRO]: true, [NUDGE]: { shown: ['firmware_update_available'], dismissed: [] } },
    });
    const { panel } = await mount(hass);
    const dlg = await waitFor(() => dialog(panel));
    expect([...dlg.querySelectorAll('input')].map((b) => b.dataset.presetId)).toEqual([
      'firmware_update_available',
      'device_stopped_reporting',
    ]);
  });

  it('waits while the first-run intro shows, and so does the card', async () => {
    const { hass, calls } = makeHass({ store: {} });
    const { panel } = await mount(hass);
    expect($(panel, '.hk-intro')).toBeTruthy();
    expect(dialog(panel)).toBeNull();
    expect(card(panel)).toBeNull();
    expect(calls.sets.filter((x) => x.key === NUDGE)).toEqual([]);
  });

  it('leaves a preset too big for one click to the card', async () => {
    const big = { ...STOPPED, matches: 51 };
    const { hass, store } = makeHass({ presets: [FIRMWARE, big] });
    const { panel } = await mount(hass);
    const dlg = await waitFor(() => dialog(panel));
    expect([...dlg.querySelectorAll('input')].map((b) => b.dataset.presetId)).toEqual([
      'firmware_update_available',
    ]);
    dlg.querySelector('.hk-preset-dialog-later').click();
    expect($$(panel, '.hk-preset-nudge-row').map((r) => r.dataset.presetId)).toEqual([
      'firmware_update_available',
      'device_stopped_reporting',
    ]);
    await waitFor(() => store[NUDGE]);
    expect(store[NUDGE].shown).toEqual(['firmware_update_available', 'device_stopped_reporting']);
  });

  it('a big preset alone goes straight to the card', async () => {
    const { hass } = makeHass({ presets: [{ ...FIRMWARE, matches: 80 }] });
    const { panel } = await mount(hass);
    expect(dialog(panel)).toBeNull();
    expect($(panel, '.hk-preset-nudge-count').textContent).toBe('80 entities match');
  });

  it('a preset whose companion was deleted comes back on the card, not in the dialog', async () => {
    const store = { [INTRO]: true };
    const companions = [{ id: 'c1', preset_id: 'firmware_update_available' }];
    const { hass } = makeHass({ companions, store });
    const { panel } = await mount(hass);
    expect(dialog(panel)).toBeNull();
    expect(card(panel)).toBeNull();
    await waitFor(() => store[NUDGE]);
    expect(store[NUDGE].shown).toEqual(['firmware_update_available']);

    document.body.innerHTML = '';
    const { hass: after } = makeHass({ companions: [], store });
    const { panel: again } = await mount(after);
    expect(dialog(again)).toBeNull();
    expect(card(again)).toBeTruthy();
  });

  it('does not open on Settings, and opens on arrival at the task list', async () => {
    const { hass } = makeHass();
    const { panel } = await mount(hass, '/settings');
    expect(dialog(panel)).toBeNull();
    panel.route = { prefix: '/home-keeper', path: '' };
    expect(await waitFor(() => dialog(panel))).toBeTruthy();
  });

  it('does not open on a task page', async () => {
    const { hass } = makeHass();
    const { panel } = await mount(hass, '/task/t1');
    expect(dialog(panel)).toBeNull();
  });

  it('reads the preset list once per panel load, not on every refresh', async () => {
    const { hass } = makeHass();
    let listed = 0;
    const orig = hass.callWS.bind(hass);
    hass.callWS = (msg) => {
      if (msg.type === 'home_keeper/list_declarative_presets') listed += 1;
      return orig(msg);
    };
    const { panel } = await mount(hass);
    expect(listed).toBe(1);
    await panel._refresh();
    await panel._refresh();
    expect(listed).toBe(1);
  });

  it('does not open after an action refresh', async () => {
    const { hass } = makeHass({ presets: [] });
    const { panel } = await mount(hass);
    expect(dialog(panel)).toBeNull();
    // A preset starts to match; the next refresh must not pop a dialog up.
    panel._declarativePresets = null;
    hass.callWS = ((orig) => (msg) =>
      msg.type === 'home_keeper/list_declarative_presets'
        ? Promise.resolve({ presets: [FIRMWARE] })
        : orig(msg))(hass.callWS);
    await panel._refresh();
    expect(dialog(panel)).toBeNull();
    expect(card(panel)).toBeNull();
    // It waits for the next arrival at the task list.
    panel.route = { prefix: '/home-keeper', path: '/settings' };
    panel.route = { prefix: '/home-keeper', path: '' };
    expect(await waitFor(() => dialog(panel))).toBeTruthy();
  });
});

describe('adding from the dialog', () => {
  it('adds only the checked presets, refreshes once and says so', async () => {
    const { hass, calls } = makeHass({ presets: [FIRMWARE, STOPPED] });
    const { panel, toasts } = await mount(hass);
    const dlg = await waitFor(() => dialog(panel));
    const [, second] = dlg.querySelectorAll('input');
    second.checked = false;
    second.dispatchEvent(new Event('change'));
    const add = dlg.querySelector('.hk-preset-dialog-add');
    expect(add.textContent).toBe('Add 1 preset');
    const before = calls.getTasks;
    add.click();

    await waitFor(() => toasts.length);
    expect(calls.adds).toEqual([FIRMWARE.default_spec]);
    expect(calls.getTasks - before).toBe(1);
    expect(toasts).toEqual(['1 preset added']);
    expect(dialog(panel)).toBeNull();
    // The unchecked preset stays on the card; the added one has a companion now.
    expect($$(panel, '.hk-preset-nudge-row').map((r) => r.dataset.presetId)).toEqual([
      'device_stopped_reporting',
    ]);
  });

  it('turns Add off when nothing is checked', async () => {
    const { hass } = makeHass();
    const { panel } = await mount(hass);
    const dlg = await waitFor(() => dialog(panel));
    const box = dlg.querySelector('input');
    box.checked = false;
    box.dispatchEvent(new Event('change'));
    expect(dlg.querySelector('.hk-preset-dialog-add').hasAttribute('disabled')).toBe(true);
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    expect(dlg.querySelector('.hk-preset-dialog-add').hasAttribute('disabled')).toBe(false);
  });

  it('waits out a config-entry reload and adds the preset once', async () => {
    const notLoaded = Object.assign(new Error('not loaded'), { code: 'not_loaded' });
    const { hass, calls } = makeHass({ addFailures: [notLoaded] });
    const { panel, toasts } = await mount(hass);
    (await waitFor(() => dialog(panel))).querySelector('.hk-preset-dialog-add').click();
    await waitFor(() => toasts.length, 4000);
    expect(calls.adds).toHaveLength(2);
    expect(toasts).toEqual(['1 preset added']);
  });

  it('says how many it added when one fails, and keeps the failed one on the card', async () => {
    const { hass } = makeHass({
      presets: [FIRMWARE, STOPPED],
      addFailures: [null, new Error('Too many companions')],
    });
    const { panel, toasts } = await mount(hass);
    (await waitFor(() => dialog(panel))).querySelector('.hk-preset-dialog-add').click();
    await waitFor(() => toasts.length);
    expect(toasts).toEqual([
      '1 of 2 presets added. Set up the others from the card above the task list.',
    ]);
    expect($$(panel, '.hk-preset-nudge-row').map((r) => r.dataset.presetId)).toEqual([
      'device_stopped_reporting',
    ]);
  });

  it('an early close lets the add finish, with the card kept out of the way', async () => {
    const { hass, calls } = makeHass();
    let release;
    const gate = new Promise((r) => (release = r));
    const orig = hass.callWS.bind(hass);
    hass.callWS = (msg) =>
      msg.type === 'home_keeper/add_declarative_companion'
        ? gate.then(() => orig(msg))
        : orig(msg);
    const { panel, toasts } = await mount(hass);
    const dlg = await waitFor(() => dialog(panel));
    dlg.querySelector('.hk-preset-dialog-add').click();
    await waitFor(() => panel._presetDialog.busy);
    $(panel, 'ha-dialog.hk-preset-dialog').dispatchEvent(new Event('closed'));
    expect(dialog(panel)).toBeNull();
    expect(card(panel)).toBeNull();
    release();
    await waitFor(() => toasts.length);
    expect(toasts).toEqual(['1 preset added']);
    expect(calls.adds).toHaveLength(1);
    expect(dialog(panel)).toBeNull();
  });

  it('skips a preset that got a companion in another tab', async () => {
    const companions = [];
    const { hass, calls } = makeHass({ companions });
    const { panel, toasts } = await mount(hass);
    const dlg = await waitFor(() => dialog(panel));
    companions.push({ id: 'elsewhere', preset_id: 'firmware_update_available' });
    dlg.querySelector('.hk-preset-dialog-add').click();
    await waitFor(() => !panel._presetDialog.busy && !panel._presetDialog.open);
    await new Promise((r) => setTimeout(r, 50));
    expect(calls.adds).toEqual([]);
    expect(toasts).toEqual([]);
  });

  it('gives the error when nothing was added', async () => {
    const { hass } = makeHass({ addFailures: [new Error('Invalid spec')] });
    const { panel, toasts } = await mount(hass);
    (await waitFor(() => dialog(panel))).querySelector('.hk-preset-dialog-add').click();
    await waitFor(() => toasts.length);
    expect(toasts).toEqual(['Home Keeper did not add the presets: Invalid spec']);
  });
});

describe('the card', () => {
  const seen = () => ({
    [INTRO]: true,
    [NUDGE]: { shown: ['firmware_update_available', 'device_stopped_reporting'], dismissed: [] },
  });

  it('Set up opens the Add dialog on the preset', async () => {
    const { hass } = makeHass({ store: seen() });
    const { panel } = await mount(hass);
    $(panel, '.hk-preset-nudge-setup').click();
    await waitFor(() => $(panel, 'ha-dialog.hk-decl-dialog'));
    expect(panel._declDialog.draft.preset_id).toBe('firmware_update_available');
  });

  it('See all presets goes to Settings, Companions', async () => {
    const { hass } = makeHass({ store: seen() });
    const { panel } = await mount(hass);
    const link = $(panel, 'a.hk-preset-nudge-all');
    expect(link.getAttribute('href')).toBe('/home-keeper/settings/companions');
    link.click();
    expect(window.location.pathname).toBe('/home-keeper/settings/companions');
  });

  it('Not now hides it for this user on every browser', async () => {
    const store = seen();
    const { hass } = makeHass({ presets: [FIRMWARE, STOPPED], store });
    const { panel } = await mount(hass);
    expect($$(panel, '.hk-preset-nudge-row')).toHaveLength(2);
    $$(panel, 'ha-button.hk-preset-nudge-hide')[0].click();
    expect(card(panel)).toBeNull();
    await waitFor(() => store[NUDGE].dismissed.length);
    expect(store[NUDGE].dismissed).toEqual([
      'firmware_update_available',
      'device_stopped_reporting',
    ]);

    document.body.innerHTML = '';
    const { hass: other } = makeHass({ presets: [FIRMWARE, STOPPED], store });
    const { panel: again } = await mount(other);
    expect(card(again)).toBeNull();
    expect(dialog(again)).toBeNull();
  });

  it('keeps an answer another tab saved since this one loaded', async () => {
    const store = seen();
    const { hass } = makeHass({ presets: [FIRMWARE, STOPPED], store });
    const { panel } = await mount(hass);
    // Another tab hides a preset this tab has not seen hidden.
    store[NUDGE] = { ...store[NUDGE], dismissed: ['elsewhere'] };
    $$(panel, 'ha-button.hk-preset-nudge-hide')[0].click();
    await waitFor(() => store[NUDGE].dismissed.length === 3);
    expect(store[NUDGE].dismissed).toEqual([
      'firmware_update_available',
      'device_stopped_reporting',
      'elsewhere',
    ]);
  });

  it('the X hides it as well', async () => {
    const { hass } = makeHass({ store: seen() });
    const { panel } = await mount(hass);
    $(panel, 'ha-icon-button.hk-preset-nudge-hide').click();
    expect(card(panel)).toBeNull();
  });
});

describe('nothing to suggest', () => {
  it.each([
    ['no match', { presets: [{ ...FIRMWARE, matches: 0 }] }],
    ['no count (null)', { presets: [{ ...FIRMWARE, matches: null }] }],
    ['an older backend without counts', { presets: [{ ...FIRMWARE, matches: undefined }] }],
    // This one writes: the preset is marked offered, so a deleted companion later
    // brings it back on the card, not in the dialog (tested above).
    [
      'a companion exists',
      { companions: [{ id: 'c', preset_id: 'firmware_update_available' }] },
      true,
    ],
    [
      'dismissed',
      { store: { [INTRO]: true, [NUDGE]: { shown: [], dismissed: ['firmware_update_available'] } } },
    ],
    ['the user data does not load', { userDataFails: true }],
  ])('%s: no dialog and no card', async (_label, opts, writes = false) => {
    const { hass, calls } = makeHass(opts);
    const { panel } = await mount(hass);
    expect(dialog(panel)).toBeNull();
    expect(card(panel)).toBeNull();
    expect(calls.sets.filter((s) => s.key === NUDGE).length > 0).toBe(writes);
  });
});
