/**
 * Shared jsdom harness for the panel tests: HA's lazily-registered components as bare
 * stand-ins, a minimal `hass`, and the two things a form test needs — an `ha-form`
 * `value-changed` emitted the way the real element emits it, and a stand-in for the
 * text box the user is typing in.
 *
 * Not a `*.test.js` file on purpose: `vitest.config.js` only collects those, so this
 * stays a plain module the spec files import.
 */
import { expect } from 'vitest';
import { HomeKeeperPanel } from '../src/panel.ts';

/**
 * Register the HA components the panel waits for before its first paint, plus the
 * panel element itself. `ha-markdown` is deliberately **not** among them: it is one of
 * HA's lazily-registered elements, and the tests that care about that register it
 * themselves at the moment they want the upgrade to land.
 */
export function definePanelStubs() {
  for (const tag of [
    'ha-card',
    'ha-form',
    'ha-button',
    'ha-icon-button',
    'ha-tab-group',
    'ha-tab-group-tab',
    'ha-alert',
    'ha-assist-chip',
    'ha-menu-button',
    'ha-svg-icon',
    'ha-spinner',
    'ha-icon',
  ]) {
    if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
  }
  if (!customElements.get('home-keeper-panel')) {
    customElements.define('home-keeper-panel', HomeKeeperPanel);
  }
}

export async function waitFor(fn, timeout = 2000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const v = fn();
    if (v) return v;
    await new Promise((r) => setTimeout(r, 20));
  }
  return null;
}

/** A minimal `hass` whose websocket commands answer with the supplied fixtures. */
export function makeHass({ tasks = [], assets = [] } = {}) {
  return {
    language: 'en',
    states: {},
    devices: {},
    callWS(msg) {
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets });
        case 'home_keeper/get_options':
          return Promise.resolve({ options: {} });
        case 'frontend/get_user_data':
          // Pre-dismissed, so the first-run intro banner never enters the picture.
          return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
        default:
          return Promise.resolve({});
      }
    },
  };
}

/** Boot a panel on *path* and wait for its first painted list. */
export async function mountPanel(path, hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  panel.hass = hass;
  const addBtn = await waitFor(() => panel.shadowRoot?.querySelector('#add-btn'));
  expect(addBtn, 'panel should finish its initial load').toBeTruthy();
  return { panel, addBtn };
}

/**
 * Emit a `value-changed` the way the real `ha-form` does: its `.data` is already
 * updated, and the event carries the *whole* form snapshot, not just the field that
 * changed. That full snapshot is what carries the form's seeded defaults into the
 * panel's handler.
 */
export function emitChange(form, patch) {
  const value = { ...form.data, ...patch };
  form.data = value;
  form.dispatchEvent(new CustomEvent('value-changed', { detail: { value } }));
}

/**
 * Stand in for the focused text box inside a form. The `ha-form` here is a bare stub,
 * so there is no real field to type in — this is the element whose survival decides
 * whether the next keystroke reaches the form or Home Assistant's global shortcuts.
 */
export function focusField(form) {
  const input = document.createElement('input');
  input.type = 'text';
  form.appendChild(input);
  input.focus();
  return input;
}

/**
 * Stub HA's lazily-loaded Markdown path. `window.loadCardHelpers` is installed by HA's
 * Lovelace chunk, and building a markdown card is what registers `ha-markdown` as a
 * side effect; the returned function performs that registration, so a test decides
 * exactly when the upgrade lands.
 */
export function stubLazyMarkdown() {
  window.loadCardHelpers = () => Promise.resolve({ createCardElement: () => undefined });
  return () => {
    if (!customElements.get('ha-markdown')) {
      customElements.define('ha-markdown', class extends HTMLElement {});
    }
  };
}
