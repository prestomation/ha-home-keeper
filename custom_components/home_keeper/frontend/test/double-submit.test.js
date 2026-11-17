import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, makeHass, mountPanel, waitFor } from './panel-harness.js';
import { openMoveCompletion } from '../src/panel-dialogs.ts';

/**
 * A double press on the Save of the move dialog, or on Import, sends 1 request.
 */

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
});

const TS = '2026-09-01T10:00:00+00:00';
const task = {
  id: 'A',
  name: 'Change filter',
  recurrence_type: 'floating',
  interval: 3,
  unit: 'months',
  enabled: true,
  completions: [{ ts: TS }],
};

const REPORT = {
  ok: true,
  dry_run: true,
  counts: { appliances: { created: 0, updated: 0 }, tasks: { created: 1, updated: 0 }, completions: 0, skips: 0 },
  records: [],
  problems: [],
};

/** A hass whose writes wait for `release()`. `calls` counts each write by type. */
function gated() {
  const hass = makeHass({ tasks: [task] });
  const base = hass.callWS;
  const calls = {};
  let open = [];
  hass.callWS = (msg) => {
    calls[msg.type] = (calls[msg.type] ?? 0) + 1;
    if (msg.type === 'home_keeper/move_completion') {
      return new Promise((r) => open.push(() => r({})));
    }
    if (msg.type === 'home_keeper/import_data') {
      const report = { ...REPORT, dry_run: !!msg.dry_run };
      if (msg.dry_run) return Promise.resolve(report);
      return new Promise((r) => open.push(() => r(report)));
    }
    return base(msg);
  };
  const release = () => {
    const now = open;
    open = [];
    now.forEach((f) => f());
  };
  return { hass, calls, release };
}

const settle = () => new Promise((r) => setTimeout(r, 30));

describe('double submit', () => {
  it('moves a completion once for a double press on Save', async () => {
    const { hass, calls, release } = gated();
    const { panel } = await mountPanel('/tasks', hass);
    openMoveCompletion(panel, task, TS);
    panel._moveCompletion.newTs = '2026-09-02T10:00:00+00:00';
    const save = await waitFor(() =>
      panel.shadowRoot.querySelector('#hk-dialog-host [slot="primaryAction"]'),
    );
    save.click();
    save.click();
    await settle();
    release();
    await settle();
    expect(calls['home_keeper/move_completion']).toBe(1);
  });

  it('moves a completion once for a press on a new Save after a render', async () => {
    const { hass, calls, release } = gated();
    const { panel } = await mountPanel('/tasks', hass);
    openMoveCompletion(panel, task, TS);
    panel._moveCompletion.newTs = '2026-09-02T10:00:00+00:00';
    const save = () => panel.shadowRoot.querySelector('#hk-dialog-host [slot="primaryAction"]');
    (await waitFor(save)).click();
    // A render while the save runs draws a new Save button.
    panel._render();
    save().click();
    await settle();
    release();
    await settle();
    expect(calls['home_keeper/move_completion']).toBe(1);
  });

  it('imports once for a double press on Import', async () => {
    const { hass, calls, release } = gated();
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: '/settings/transfer' };
    document.body.appendChild(panel);
    panel.hass = hass;
    await waitFor(() => panel.shadowRoot?.querySelector('#transfer-import'));
    panel._transfer.text = 'home_keeper:\n  format: 1\n';
    await panel._previewImport();
    const run = () => panel.shadowRoot.querySelector('#transfer-import');
    run().click();
    run().click();
    await settle();
    release();
    await settle();
    // 1 preview and 1 import.
    expect(calls['home_keeper/import_data']).toBe(2);
  });
});

describe('double submit: Move of a later date in the snooze dialog', () => {
  const DUE = '2026-10-09T07:00:00-07:00';
  const LATER = '2026-10-13T07:00:00-07:00';

  it('moves the date once for a double press on Move', async () => {
    const { renderSnoozeDialog } = await import('../src/defer-dialogs.ts');
    const moves = [];
    let release;
    const hass = {
      callWS: async (msg) => {
        if (msg.type === 'home_keeper/move_occurrence') {
          moves.push(msg);
          await new Promise((r) => (release = r));
          return {};
        }
        return { occurrences: [{ start: DUE, moved_from: null }, { start: LATER, moved_from: null }] };
      },
    };
    const state = { open: true, preset: '1d', task: { id: 't1', recurrence_type: 'fixed', next_due: DUE } };
    const root = document.createElement('div');
    let open = true;
    const host = {
      hass: () => hass,
      lang: () => 'en',
      makeForm: () => document.createElement('div'),
      rerender: () => {
        root.innerHTML = '';
        renderSnoozeDialog(host, state, root, () => {
          open = false;
        });
      },
      refresh: async () => {},
      notify: () => {},
    };
    host.rerender();
    await new Promise((r) => setTimeout(r, 0));
    root.querySelectorAll('.hk-later-row')[1].click();
    // A later date moves to the day after it.
    state.moveTo = '2026-10-14 07:00:00';
    const move = root.querySelector('[slot="primaryAction"]');
    expect(move.textContent).toBe('Move');
    move.click();
    move.click();
    await new Promise((r) => setTimeout(r, 0));
    release?.();
    await new Promise((r) => setTimeout(r, 10));
    expect(moves).toHaveLength(1);
    expect(open).toBe(false);
  });
});
