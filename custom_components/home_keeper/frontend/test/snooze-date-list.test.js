import { beforeAll, describe, expect, it } from 'vitest';
import { renderSnoozeDialog } from '../src/defer-dialogs.ts';
import { definePanelStubs } from './panel-harness.js';

/**
 * The snooze dialog of a fixed task lists its dates. The first row is the due date,
 * and a snooze moves it. A later row moves only that date (#390).
 */

beforeAll(() => definePanelStubs());

const DUE = '2026-10-09T07:00:00-07:00';
const LATER = '2026-10-13T07:00:00-07:00';

function setup(state) {
  const calls = [];
  const hass = {
    callWS: async (msg) => {
      calls.push(msg);
      return { occurrences: [{ start: DUE, moved_from: null }, { start: LATER, moved_from: null }] };
    },
  };
  const root = document.createElement('div');
  const host = {
    hass: () => hass,
    lang: () => 'en',
    makeForm: () => document.createElement('div'),
    rerender: () => {
      root.innerHTML = '';
      renderSnoozeDialog(host, state, root, () => {});
    },
    refresh: async () => {},
    notify: () => {},
  };
  host.rerender();
  return { root, calls };
}

const fixedState = () => ({
  open: true,
  preset: '1d',
  task: { id: 't1', recurrence_type: 'fixed', next_due: DUE },
});

const rows = (root) => [...root.querySelectorAll('.hk-later-row')];
const primary = (root) => root.querySelector('[slot="primaryAction"]');

describe('the snooze dialog of a fixed task', () => {
  it('picks the due date first, so the dialog is a plain snooze', async () => {
    const state = fixedState();
    const { root, calls } = setup(state);
    await new Promise((r) => setTimeout(r, 0));
    expect(calls[0].type).toBe('home_keeper/upcoming_occurrences');
    // The due date, then only the later date: the due date is not listed twice.
    expect(rows(root).map((b) => b.dataset.start)).toEqual([DUE, LATER]);
    expect(rows(root)[0].getAttribute('aria-pressed')).toBe('true');
    expect(primary(root).textContent).toBe('Snooze');
  });

  it('moves a later date when one is picked, and goes back to snooze', async () => {
    const state = fixedState();
    const { root } = setup(state);
    await new Promise((r) => setTimeout(r, 0));
    rows(root)[1].click();
    expect(rows(root)[1].getAttribute('aria-pressed')).toBe('true');
    expect(primary(root).textContent).toBe('Move');
    expect(root.querySelector('.hk-move-hint').textContent).toContain('moves to');
    rows(root)[0].click();
    expect(primary(root).textContent).toBe('Snooze');
  });

  it('shows no date list for a floating task', () => {
    const state = { open: true, preset: '1d', task: { id: 't2', recurrence_type: 'floating' } };
    const { root, calls } = setup(state);
    expect(rows(root)).toHaveLength(0);
    expect(calls).toHaveLength(0);
  });
});
