import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { submitSkip, submitSnooze } from '../src/defer-dialogs.ts';
import { guardWrite } from '../src/utils.ts';
import { definePanelStubs, mountPanel, waitFor } from './panel-harness.js';

/**
 * X12-3 / X12-4: a second press of Done, Skip, Snooze, the completion dialog, or the
 * drawer's Create/Save while the first call runs must not send a second write. The
 * backend does not remove a duplicate: two completions draw down stock twice and fire
 * the event twice, and two adds make two tasks.
 */

/** A promise the test settles by hand, so a write stays "in flight". */
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('guardWrite', () => {
  it('X12-3: ignores a second call while the first runs', async () => {
    const state = {};
    const gate = deferred();
    const write = vi.fn(() => gate.promise);
    const first = guardWrite(state, write);
    expect(state.busy).toBe(true);
    const second = await guardWrite(state, write);
    expect(second).toBe(false);
    expect(write).toHaveBeenCalledTimes(1);
    gate.resolve();
    expect(await first).toBe(true);
    expect(state.busy).toBe(false);
    // Free again once the first one ended.
    expect(await guardWrite(state, async () => {})).toBe(true);
  });

  it('X12-3: disables the pressed button while the write runs, then enables it', async () => {
    const state = {};
    const button = document.createElement('button');
    const gate = deferred();
    const run = guardWrite(state, () => gate.promise, button);
    expect(button.hasAttribute('disabled')).toBe(true);
    gate.resolve();
    await run;
    expect(button.hasAttribute('disabled')).toBe(false);
  });

  it('X12-3: frees the state and the button when the write throws', async () => {
    const state = {};
    const button = document.createElement('button');
    await expect(
      guardWrite(state, () => Promise.reject(new Error('boom')), button),
    ).rejects.toThrow('boom');
    expect(state.busy).toBe(false);
    expect(button.hasAttribute('disabled')).toBe(false);
  });

  it('X12-3: leaves a button alone when the press is ignored', async () => {
    const state = { busy: true };
    const button = document.createElement('button');
    expect(await guardWrite(state, async () => {}, button)).toBe(false);
    expect(button.hasAttribute('disabled')).toBe(false);
    expect(state.busy).toBe(true);
  });
});

describe('X12-3: the skip and snooze dialogs', () => {
  function host(calls, gate) {
    const hass = {
      callWS: (msg) => {
        calls.push(msg.type);
        return gate.promise.then(() => ({ task: { id: 't1' } }));
      },
    };
    return {
      hass: () => hass,
      lang: () => 'en',
      makeForm: () => document.createElement('div'),
      rerender: () => {},
      refresh: async () => {},
    };
  }

  it('sends one skip for a double press', async () => {
    const calls = [];
    const gate = deferred();
    const s = { open: true, task: { id: 't1' }, data: {} };
    const close = vi.fn();
    const a = submitSkip(host(calls, gate), s, close);
    const b = submitSkip(host(calls, gate), s, close);
    gate.resolve();
    await Promise.all([a, b]);
    expect(calls).toEqual(['home_keeper/skip_task']);
    expect(close).toHaveBeenCalledTimes(1);
  });

  it('sends one snooze for a double press', async () => {
    const calls = [];
    const gate = deferred();
    const s = { open: true, task: { id: 't1' }, preset: '1d' };
    const close = vi.fn();
    const a = submitSnooze(host(calls, gate), s, close);
    const b = submitSnooze(host(calls, gate), s, close);
    gate.resolve();
    await Promise.all([a, b]);
    expect(calls).toEqual(['home_keeper/snooze_task']);
  });
});

describe('X12-3 / X12-4: the panel', () => {
  beforeAll(() => {
    definePanelStubs();
  });

  afterEach(() => {
    document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
  });

  const TASK = {
    id: 't1',
    name: 'Replace water filter',
    recurrence_type: 'floating',
    interval: 3,
    unit: 'months',
    next_due: '2030-01-01T00:00:00+00:00',
    completions: [],
  };

  /** A hass whose write commands wait on *gate*; `calls` counts each type. */
  function gatedHass(tasks, gate) {
    const calls = {};
    const hass = {
      language: 'en',
      states: {},
      devices: {},
      callWS(msg) {
        calls[msg.type] = (calls[msg.type] || 0) + 1;
        switch (msg.type) {
          case 'home_keeper/get_tasks':
            return Promise.resolve({ tasks });
          case 'home_keeper/get_assets':
            return Promise.resolve({ assets: [] });
          case 'home_keeper/get_options':
            return Promise.resolve({ options: {} });
          case 'frontend/get_user_data':
            return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
          case 'home_keeper/complete_task':
          case 'home_keeper/add_task':
          case 'home_keeper/add_asset':
            return gate.promise.then(() => ({ task: { id: 'new' }, asset: { id: 'a1' } }));
          default:
            return Promise.resolve({});
        }
      },
    };
    return { hass, calls };
  }

  it('X12-3: a double click on a row Done logs one completion', async () => {
    const gate = deferred();
    const { hass, calls } = gatedHass([TASK], gate);
    const { panel } = await mountPanel('/tasks', hass);
    const done = await waitFor(() => panel.shadowRoot.querySelector('#hk-list .done-btn'));
    done.click();
    expect(done.hasAttribute('disabled')).toBe(true);
    done.click();
    // A re-render mid-call draws a new, enabled button; it is still ignored.
    panel._render();
    panel.shadowRoot.querySelector('#hk-list .done-btn').click();
    gate.resolve();
    await waitFor(() => panel._completing.t1 && !panel._completing.t1.busy);
    expect(calls['home_keeper/complete_task']).toBe(1);
  });

  it('X12-3: a double click on Mark done in the completion dialog logs one completion', async () => {
    const gate = deferred();
    const task = { ...TASK, completion_detail: 'optional' };
    const { hass, calls } = gatedHass([task], gate);
    const { panel } = await mountPanel('/tasks', hass);
    const done = await waitFor(() => panel.shadowRoot.querySelector('#hk-list .done-btn'));
    done.click();
    const primary = await waitFor(() =>
      panel.shadowRoot.querySelector('ha-dialog [slot="primaryAction"]'),
    );
    primary.click();
    primary.click();
    gate.resolve();
    await waitFor(() => !panel._completion.open);
    expect(calls['home_keeper/complete_task']).toBe(1);
  });

  it('X12-4: a double press on Create in the task drawer adds one task', async () => {
    const gate = deferred();
    const { hass, calls } = gatedHass([], gate);
    const { panel, addBtn } = await mountPanel('/tasks', hass);
    addBtn.click();
    await waitFor(() => panel._edit.open);
    panel._edit.task = { ...panel._edit.task, name: 'Clean gutters' };
    const save = await waitFor(() => panel.shadowRoot.querySelector('#f-save'));
    save.click();
    save.click();
    gate.resolve();
    await waitFor(() => !panel._edit.open);
    expect(calls['home_keeper/add_task']).toBe(1);
  });

  it('X12-4: a double press on Create in the appliance drawer adds one appliance', async () => {
    const gate = deferred();
    const { hass, calls } = gatedHass([], gate);
    const { panel } = await mountPanel('/tasks', hass);
    panel._assetEdit = { open: true, asset: { kind: 'virtual', name: 'Fridge', parts: [] } };
    const a = panel._submitAssetForm();
    const b = panel._submitAssetForm();
    gate.resolve();
    await Promise.all([a, b]);
    expect(calls['home_keeper/add_asset']).toBe(1);
  });
});
