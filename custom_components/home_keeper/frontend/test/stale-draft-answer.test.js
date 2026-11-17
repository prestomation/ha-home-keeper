// A late server answer for an old draft must not close or change a newer draft.
// Sequence: open a form, save it, close it before the server answers, open a new
// form, then let the first answer arrive. The user's new text must stay.
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { HomeKeeperCard } from '../src/card.ts';
import { definePanelStubs, emitChange, makeHass, mountPanel, waitFor } from './panel-harness.js';

beforeAll(() => {
  definePanelStubs();
  for (const tag of ['ha-assist-chip', 'ha-alert', 'ha-spinner']) {
    if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
  }
  if (!customElements.get('home-keeper-card')) {
    customElements.define('home-keeper-card', HomeKeeperCard);
  }
});
afterEach(() => {
  document.body.innerHTML = '';
});

/** A promise that the test settles by hand. */
function deferred() {
  let resolve;
  const promise = new Promise((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const escape = () =>
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

/** A hass whose `add_*` answers wait on a gate that the test opens later. */
function slowHass(gate, answerKey, answer) {
  const base = makeHass();
  const calls = [];
  return {
    ...base,
    user: { is_admin: true },
    calls,
    callWS(msg) {
      calls.push(msg);
      if (msg.type === `home_keeper/${answerKey}`) return gate.promise.then(() => answer(msg));
      return base.callWS(msg);
    },
  };
}

describe('a late answer for an old draft', () => {
  it('does not close the task form that is open now', async () => {
    const gate = deferred();
    const hass = slowHass(gate, 'add_task', (msg) => ({
      task: { id: 'new1', name: msg.task?.name },
    }));
    const { panel, addBtn } = await mountPanel('/tasks', hass);
    addBtn.click();
    await waitFor(() => panel.shadowRoot.querySelector('#hk-task-form-basics'));
    emitChange(panel.shadowRoot.querySelector('#hk-task-form-basics'), { name: 'one' });
    panel.shadowRoot.querySelector('#f-save').click();
    await waitFor(() => hass.calls.some((m) => m.type === 'home_keeper/add_task'));
    escape();
    expect(panel._isOpen('taskForm')).toBe(false);
    panel.shadowRoot.querySelector('#add-btn').click();
    await waitFor(() => panel.shadowRoot.querySelector('#hk-task-form-basics'));
    emitChange(panel.shadowRoot.querySelector('#hk-task-form-basics'), { name: 'two' });

    gate.resolve();
    await new Promise((r) => setTimeout(r, 100));

    expect(panel._isOpen('taskForm')).toBe(true);
    expect(panel._edit.task.name).toBe('two');
    expect(panel._edit.task.id).toBeUndefined();
    expect(panel.shadowRoot.querySelector('#hk-task-form-basics')).toBeTruthy();
  });

  it('keeps the id and the error of a failed link step off the new task form', async () => {
    const gate = deferred();
    const base = slowHass(gate, 'add_task', (msg) => ({
      task: { id: 'new1', name: msg.task?.name },
    }));
    const hass = {
      ...base,
      callWS(msg) {
        if (msg.type === 'home_keeper/set_task_consumable') {
          base.calls.push(msg);
          return Promise.reject(new Error('link failed'));
        }
        return base.callWS(msg);
      },
    };
    const { panel, addBtn } = await mountPanel('/tasks', hass);
    addBtn.click();
    await waitFor(() => panel.shadowRoot.querySelector('#hk-task-form-basics'));
    emitChange(panel.shadowRoot.querySelector('#hk-task-form-basics'), { name: 'one' });
    panel._edit.task.consumable_links = ['asset1:part1'];
    panel.shadowRoot.querySelector('#f-save').click();
    await waitFor(() => hass.calls.some((m) => m.type === 'home_keeper/add_task'));
    escape();
    panel.shadowRoot.querySelector('#add-btn').click();
    await waitFor(() => panel.shadowRoot.querySelector('#hk-task-form-basics'));
    emitChange(panel.shadowRoot.querySelector('#hk-task-form-basics'), { name: 'two' });

    gate.resolve();
    await waitFor(() => hass.calls.some((m) => m.type === 'home_keeper/set_task_consumable'));
    await new Promise((r) => setTimeout(r, 100));

    // A later Save of the new draft must create a task, never update `new1`.
    expect(panel._edit.task.id).toBeUndefined();
    expect(panel._edit.error).toBeUndefined();
    panel.shadowRoot.querySelector('#f-save').click();
    await waitFor(() => hass.calls.filter((m) => m.type === 'home_keeper/add_task').length === 2);
    expect(hass.calls.some((m) => m.type === 'home_keeper/update_task')).toBe(false);
  });

  it('does not close the appliance form that is open now', async () => {
    const gate = deferred();
    const hass = slowHass(gate, 'add_asset', (msg) => ({
      asset: { id: 'a1', name: msg.asset?.name },
    }));
    const { panel } = await mountPanel('/appliances', hass);
    const open = () => panel.shadowRoot.querySelector('#add-btn').click();
    const name = (value) => {
      const form = panel.shadowRoot.querySelector('#hk-asset-form ha-form');
      emitChange(form, { name: value });
    };
    open();
    await waitFor(() => panel.shadowRoot.querySelector('#hk-asset-form ha-form'));
    name('one');
    panel.shadowRoot.querySelector('#a-save').click();
    await waitFor(() => hass.calls.some((m) => m.type === 'home_keeper/add_asset'));
    escape();
    expect(panel._isOpen('assetForm')).toBe(false);
    open();
    await waitFor(() => panel.shadowRoot.querySelector('#hk-asset-form ha-form'));
    name('two');

    gate.resolve();
    await new Promise((r) => setTimeout(r, 100));

    expect(panel._isOpen('assetForm')).toBe(true);
    expect(panel._assetEdit.asset.name).toBe('two');
  });

  it('does not close the card form that is open now', async () => {
    const gate = deferred();
    const hass = slowHass(gate, 'add_task', (msg) => ({
      task: { id: 'new1', name: msg.task?.name },
    }));
    hass.user = { is_admin: false };
    const card = document.createElement('home-keeper-card');
    card.setConfig({ type: 'custom:home-keeper-card' });
    document.body.appendChild(card);
    card.hass = hass;
    const sr = card.shadowRoot;
    const name = (value) => {
      const form = sr.querySelector('.hk-form ha-form');
      form.dispatchEvent(
        new CustomEvent('value-changed', { detail: { value: { ...form.data, name: value } } }),
      );
    };
    await waitFor(() => sr.querySelector('#hk-add'));
    sr.querySelector('#hk-add').click();
    await waitFor(() => sr.querySelector('.hk-form ha-form'));
    name('one');
    sr.querySelector('#hk-create').click();
    await waitFor(() => hass.calls.some((m) => m.type === 'home_keeper/add_task'));
    // Cancel is the second button of the form's action row.
    sr.querySelector('.hk-form-actions ha-button:last-child').click();
    expect(sr.querySelector('.hk-form')).toBeNull();
    sr.querySelector('#hk-add').click();
    await waitFor(() => sr.querySelector('.hk-form ha-form'));
    name('two');

    gate.resolve();
    await new Promise((r) => setTimeout(r, 100));

    expect(sr.querySelector('.hk-form')).toBeTruthy();
    expect(card._edit.task.name).toBe('two');
  });
});
