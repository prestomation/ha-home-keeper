import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { HomeKeeperCard } from '../src/card.ts';

/**
 * "Confirm before completing" asks in the dialog that the panel uses, not in the
 * browser's `window.confirm`, and the card is not marked done until the button says so.
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

const TASK = {
  id: 't1',
  name: 'Replace filter',
  recurrence_type: 'floating',
  interval: 1,
  unit: 'months',
  next_due: new Date(Date.now() + 86_400_000).toISOString(),
  completions: [],
};

async function waitFor(fn, timeout = 2000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const v = fn();
    if (v) return v;
    await new Promise((r) => setTimeout(r, 10));
  }
  return null;
}

async function mount(config) {
  const calls = [];
  const card = document.createElement('home-keeper-card');
  card.setConfig({ type: 'custom:home-keeper-card', ...config });
  document.body.appendChild(card);
  card.hass = {
    language: 'en',
    callWS: async (msg) => {
      calls.push(msg.type);
      if (msg.type === 'home_keeper/get_tasks') return { tasks: [TASK] };
      if (msg.type === 'home_keeper/complete_task') return { task: TASK };
      return {};
    },
  };
  await waitFor(() => card.shadowRoot?.querySelector('.hk-done'));
  return { card, calls };
}

const done = (card) => card.shadowRoot.querySelector('.hk-done');
const scrim = () => document.querySelector('.hk-confirm-scrim');
const button = (label) =>
  [...document.querySelectorAll('.hk-confirm-scrim ha-button')].find((b) => b.textContent === label);
const completed = (calls) => calls.filter((c) => c === 'home_keeper/complete_task').length;

describe('the card asks before it marks a task done', () => {
  it('opens the shared dialog, and never calls the browser confirm', async () => {
    const native = vi.spyOn(window, 'confirm');
    const { card, calls } = await mount({ confirm_complete: true });
    done(card).click();
    expect(scrim()).toBeTruthy();
    expect(document.querySelector('.hk-confirm-modal').getAttribute('role')).toBe('alertdialog');
    expect(document.querySelector('#hk-confirm-title').textContent).toBe('Mark "Replace filter" done?');
    expect(button('Done')).toBeTruthy();
    expect(completed(calls)).toBe(0);
    expect(native).not.toHaveBeenCalled();
  });

  it('does not complete on Cancel, on Escape or on a tap outside', async () => {
    const { card, calls } = await mount({ confirm_complete: true });
    for (const close of [
      () => button('Cancel').click(),
      () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })),
      () => scrim().click(),
    ]) {
      done(card).click();
      expect(scrim()).toBeTruthy();
      close();
      expect(scrim()).toBeNull();
    }
    await new Promise((r) => setTimeout(r, 30));
    expect(completed(calls)).toBe(0);
  });

  it('completes once, from the Done button of the dialog', async () => {
    const { card, calls } = await mount({ confirm_complete: true });
    done(card).click();
    button('Done').click();
    expect(scrim()).toBeNull();
    await waitFor(() => completed(calls) === 1);
    expect(completed(calls)).toBe(1);
  });

  it('asks nothing when the option is off', async () => {
    const { card, calls } = await mount({});
    done(card).click();
    expect(scrim()).toBeNull();
    await waitFor(() => completed(calls) === 1);
    expect(completed(calls)).toBe(1);
  });

  it('takes the dialog down when the card leaves the page', async () => {
    const { card } = await mount({ confirm_complete: true });
    done(card).click();
    expect(scrim()).toBeTruthy();
    card.remove();
    expect(scrim()).toBeNull();
  });
});
