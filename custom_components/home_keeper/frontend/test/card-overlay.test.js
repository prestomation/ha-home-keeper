import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { HomeKeeperCard } from '../src/card.ts';
import { stubLazyMarkdown } from './panel-harness.js';

/**
 * The card's overlays follow the panel's rules (`overlay-state.ts`): 1 busy rule, and
 * the keyboard goes back to the control that opened an overlay when it closes.
 *
 * Own file: the Markdown test needs a registry that has never seen `ha-markdown`.
 */

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
    'ha-dialog',
  ]) {
    if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
  }
  if (!customElements.get('home-keeper-card')) {
    customElements.define('home-keeper-card', HomeKeeperCard);
  }
});

afterEach(() => {
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

const TASKS = [
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

async function waitFor(fn, timeout = 2000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const v = fn();
    if (v) return v;
    await new Promise((r) => setTimeout(r, 20));
  }
  return null;
}

function mount() {
  const card = document.createElement('home-keeper-card');
  card.setConfig({ type: 'custom:home-keeper-card' });
  document.body.appendChild(card);
  card.hass = {
    language: 'en',
    callWS: async (msg) => (msg.type === 'home_keeper/get_tasks' ? { tasks: TASKS } : {}),
  };
  return card;
}

describe('card overlays', () => {
  it('waits with a late Markdown upgrade while the create form is open', async () => {
    const register = stubLazyMarkdown();
    const card = mount();
    await waitFor(() => card.shadowRoot?.querySelector('.hk-row'));
    card.shadowRoot.querySelector('#hk-add').click();
    const form = card.shadowRoot.querySelector('.hk-form');
    expect(form).toBeTruthy();
    register();
    await waitFor(() => customElements.get('ha-markdown'));
    await new Promise((r) => setTimeout(r, 50));
    expect(card.shadowRoot.querySelector('.hk-form'), 'a render replaced the form').toBe(form);
  });

  it('gives the keyboard back to the Snooze button of the row after the dialog', async () => {
    const card = mount();
    const button = await waitFor(() => card.shadowRoot?.querySelector('.hk-defer-snooze[data-id="t1"]'));
    expect(button).toBeTruthy();
    button.tabIndex = 0;
    button.focus();
    button.click();
    const cancel = await waitFor(() => card.shadowRoot.querySelector('ha-dialog [slot="secondaryAction"]'));
    expect(cancel, 'the snooze dialog should open').toBeTruthy();
    const focused = vi.spyOn(HTMLElement.prototype, 'focus');
    cancel.click();
    await new Promise((r) => setTimeout(r, 20));
    const now = card.shadowRoot.querySelector('.hk-defer-snooze[data-id="t1"]');
    expect(now).not.toBe(button);
    expect(focused.mock.contexts).toContain(now);
  });
});
