import fc from 'fast-check';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { definePanelStubs, makeHass, stubLazyMarkdown, waitFor } from './panel-harness.js';
import { closeSnooze } from '../src/panel-defer.ts';
import { closeActionSheet, openActionSheet } from '../src/panel-lists.ts';

/**
 * The overlays of the panel: 1 busy rule for every dialog, form, sheet and menu, and
 * the keyboard goes back to the control that opened an overlay when it closes.
 */

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
  localStorage.clear();
  vi.restoreAllMocks();
});

const task = {
  id: 'A',
  name: 'Change filter',
  recurrence_type: 'floating',
  interval: 3,
  unit: 'months',
  enabled: true,
  next_due: '2030-01-01T00:00:00Z',
};

const settle = () => new Promise((r) => setTimeout(r, 30));

/** A panel that counts its task loads. */
const SPEND = {
  windows: [{ days: 30, total: 12, count: 1, since: '2026-09-01T00:00:00Z' }],
  all_time: { total: 12, count: 1, first: '2026-09-02T00:00:00Z' },
  purchases: { total: 0, count: 0 },
  records: [
    {
      ts: '2026-09-02T00:00:00Z',
      cost: 12,
      who: null,
      task_id: 'A',
      task_name: 'Change filter',
      asset_id: null,
      archived: false,
    },
  ],
};

async function mountCounting(path = '/tasks') {
  const hass = makeHass({ tasks: [task] });
  hass.config = { currency: 'USD' };
  const base = hass.callWS;
  const ctl = { loads: 0 };
  hass.callWS = (msg) => {
    if (msg.type === 'home_keeper/get_tasks') ctl.loads++;
    if (msg.type === 'home_keeper/get_spend') return Promise.resolve(SPEND);
    return base(msg);
  };
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel._loaded);
  await settle();
  ctl.loads = 0;
  // Each push comes after the echo window of the last load, so it is a real change.
  let now = Date.now() + 60_000;
  vi.spyOn(Date, 'now').mockImplementation(() => now);
  let stamp = 0;
  ctl.push = () => {
    now += 5_000;
    stamp++;
    panel.hass = {
      ...panel.hass,
      states: { 'todo.home_keeper_tasks': { last_updated: new Date(Date.UTC(2026, 9, 1, 10, 0, stamp)).toISOString() } },
    };
  };
  return { panel, ctl };
}

/** The elements that got `focus()`, in order. */
function watchFocus() {
  const spy = vi.spyOn(HTMLElement.prototype, 'focus');
  return () => spy.mock.contexts;
}

describe('1 busy rule for every overlay', () => {
  it('waits with a live load while the action sheet is open', async () => {
    const { panel, ctl } = await mountCounting();
    openActionSheet(panel, task);
    ctl.push();
    await settle();
    expect(ctl.loads).toBe(0);
  });

  it('waits with a live load while the spend sheet is open', async () => {
    const { panel, ctl } = await mountCounting();
    panel._openSpendSheet();
    expect(panel.shadowRoot.querySelector('.hk-spend-sheet'), 'the sheet should show').toBeTruthy();
    ctl.push();
    await settle();
    expect(ctl.loads).toBe(0);
  });

  it('waits with a late Markdown upgrade while a deferral menu is open', async () => {
    const registerMarkdown = stubLazyMarkdown();
    const { panel } = await mountCounting();
    const caret = panel.shadowRoot.querySelector('.hk-split[data-id="A"] .hk-split-caret');
    expect(caret, 'the row should have a deferral caret').toBeTruthy();
    caret.click();
    const menu = panel.shadowRoot.querySelector('.hk-split[data-id="A"] .hk-defer-menu');
    expect(menu.hidden).toBe(false);
    registerMarkdown();
    await waitFor(() => customElements.get('ha-markdown'));
    await settle();
    expect(menu.isConnected, 'a render replaced the open menu').toBe(true);
    expect(menu.hidden).toBe(false);
  });

  it('loads the change that waited when the last overlay closes', async () => {
    const { panel, ctl } = await mountCounting();
    openActionSheet(panel, task);
    ctl.push();
    await settle();
    expect(ctl.loads).toBe(0);
    closeActionSheet(panel);
    await settle();
    expect(ctl.loads).toBe(1);
  });
});

describe('Escape closes 1 overlay', () => {
  it('closes the confirmation and leaves the spend sheet under it open', async () => {
    const { confirmDestructive } = await import('../src/panel-dialogs.ts');
    const { panel } = await mountCounting();
    panel._openSpendSheet();
    confirmDestructive(panel, { title: 'Delete?', onConfirm: () => {} });
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(panel._isOpen('confirm')).toBe(false);
    expect(panel._isOpen('spendSheet')).toBe(true);
    expect(panel.shadowRoot.querySelector('.hk-spend-sheet')).toBeTruthy();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(panel._isOpen('spendSheet')).toBe(false);
  });
});

describe('the keyboard after an overlay closes', () => {
  it('goes back to the caret after a Snooze that the deferral menu opened', async () => {
    const { panel } = await mountCounting();
    panel.shadowRoot.querySelector('.hk-split[data-id="A"] .hk-split-caret').click();
    panel.shadowRoot.querySelector('.hk-split[data-id="A"] .hk-defer-snooze').click();
    await settle();
    expect(panel._snooze.task?.id).toBe('A');
    const focused = watchFocus();
    closeSnooze(panel);
    await settle();
    const caret = panel.shadowRoot.querySelector('.hk-split[data-id="A"] .hk-split-caret');
    expect(focused()).toContain(caret);
  });

  it('goes back to the Delete button after a render while the confirmation is open', async () => {
    const { panel } = await mountCounting('/tasks/A');
    const del = await waitFor(() => panel.shadowRoot.querySelector('.d-del'));
    // The stand-in element takes the keyboard only with a tab index.
    del.tabIndex = 0;
    del.focus();
    del.click();
    const cancel = await waitFor(() => document.querySelector('.hk-confirm-scrim ha-button'));
    // A render replaces the page and the Delete button under the confirmation.
    panel._render();
    const focused = watchFocus();
    cancel.click();
    await settle();
    const now = panel.shadowRoot.querySelector('.d-del');
    expect(now).not.toBe(del);
    expect(focused()).toContain(now);
  });

  it('goes back to the tile after a Snooze that the action sheet opened', async () => {
    const { panel } = await mountCounting();
    panel._setTaskLayout('tiles');
    const host = panel.shadowRoot;
    const tile = await waitFor(() => host.querySelector('.hk-press[data-id="A"]'));
    expect(tile, 'the tiles layout should draw a tile').toBeTruthy();
    tile.focus();
    openActionSheet(panel, task);
    const sheetSnooze = await waitFor(() =>
      host.querySelector('#hk-dialog-host .hk-sheet-row[data-action="snooze"]'),
    );
    expect(sheetSnooze, 'the sheet should offer Snooze').toBeTruthy();
    sheetSnooze.click();
    await settle();
    expect(panel._snooze.task?.id).toBe('A');
    const focused = watchFocus();
    closeSnooze(panel);
    await settle();
    expect(focused().some((el) => el.matches?.('.hk-press[data-id="A"]'))).toBe(true);
  });
});

/*
 * Model test on the real panel. The model is the set of open overlays, with the rules
 * that a menu gives its place to the next overlay and that a render closes an open
 * deferral menu. After each command the panel's busy rule and each overlay must match
 * the model, and a change that comes while the panel is busy loads only when the last
 * overlay closes.
 */
describe('overlay model on the real panel', () => {
  const MENUS = ['deferMenu', 'actionSheet'];
  const KINDS = ['snooze', 'skip', 'completion', 'actionSheet', 'label', 'spendSheet', 'taskForm', 'confirm', 'deferMenu'];

  async function openKind(panel, kind) {
    const { openSnooze, openSkip } = await import('../src/panel-defer.ts');
    const { openCompletionDialog, confirmDestructive } = await import('../src/panel-dialogs.ts');
    const { openLabelDialog } = await import('../src/panel-labels.ts');
    switch (kind) {
      case 'snooze': return openSnooze(panel, task);
      case 'skip': return openSkip(panel, task);
      case 'completion': return openCompletionDialog(panel, task);
      case 'actionSheet': return openActionSheet(panel, task);
      case 'label': return openLabelDialog(panel, 'task', 'A');
      case 'spendSheet': return panel._openSpendSheet();
      case 'taskForm': return panel._openCreate();
      case 'confirm': return confirmDestructive(panel, { title: 'Delete?', onConfirm: () => {} });
      case 'deferMenu':
        return panel.shadowRoot.querySelector('.hk-split[data-id="A"] .hk-split-caret')?.click();
    }
  }

  async function closeKind(panel, kind) {
    const { closeSkip } = await import('../src/panel-defer.ts');
    switch (kind) {
      case 'snooze': return closeSnooze(panel);
      case 'skip': return closeSkip(panel);
      case 'actionSheet': return closeActionSheet(panel);
      case 'spendSheet': return panel._closeSpendSheet();
      case 'taskForm': return panel._closeForm();
      case 'confirm':
      case 'deferMenu':
        // Both close on Escape at document level.
        return document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      default: {
        // The completion and label dialogs close when the dialog element closes. The
        // completion dialog is drawn first in the dialog host.
        const host = panel.shadowRoot.querySelector('#hk-dialog-host');
        const dialog =
          kind === 'label' ? host.querySelector('.hk-label-dialog') : host.firstElementChild;
        return dialog?.dispatchEvent(new CustomEvent('closed'));
      }
    }
  }

  /** Whether the deferral menu can open: only on the task list, with no overlay that
   *  covers the list. */
  const menuCanOpen = (m) =>
    !m.open.length || m.open.every((k) => k === 'deferMenu');

  const cmd = (name, check, run) => ({
    check,
    async run(m) {
      await run(m);
      await settle();
      expect(m.panel._busy(), `busy after ${name}`).toBe(m.open.length > 0);
      for (const kind of KINDS) {
        expect(m.panel._isOpen(kind), `${kind} after ${name}`).toBe(m.open.includes(kind));
      }
      if (!m.open.length) expect(m.ctl.loads, `loads after ${name}`).toBe(m.changes);
      else expect(m.ctl.loads, `no load while busy, after ${name}`).toBe(m.loadsAtBusy);
    },
    toString: () => name,
  });

  const open = (kind) =>
    cmd(
      `Open(${kind})`,
      (m) => !m.open.includes(kind) && (kind !== 'deferMenu' || menuCanOpen(m)),
      async (m) => {
        if (!m.open.length) m.loadsAtBusy = m.ctl.loads;
        await openKind(m.panel, kind);
        // A render closes an open deferral menu, and a menu gives its place to the
        // overlay that opens over it.
        m.open = m.open.filter((k) => !MENUS.includes(k) || k === kind);
        m.open.push(kind);
      },
    );

  const close = (kind) =>
    cmd(
      `Close(${kind})`,
      // Only the top overlay closes: the user acts on what is in front.
      (m) => m.open[m.open.length - 1] === kind,
      async (m) => {
        await closeKind(m.panel, kind);
        m.open.pop();
        // The change that waited loads when the last overlay closes.
        if (!m.open.length && m.pending) {
          m.changes++;
          m.pending = false;
        }
      },
    );

  const change = cmd('Change', () => true, (m) => {
    if (!m.open.length) m.changes++;
    else m.pending = true;
    m.ctl.push();
  });

  it('keeps the busy rule and the waiting load right for any sequence', async () => {
    const runs = Math.max(5, Math.floor(fc.readConfigureGlobal().numRuns / 8));
    await fc.assert(
      fc.asyncProperty(
        fc.commands(
          [
            ...KINDS.map((k) => fc.constant(open(k))),
            ...KINDS.map((k) => fc.constant(close(k))),
            // Weighted: a change while an overlay is open is the case that matters.
            ...Array.from({ length: 4 }, () => fc.constant(change)),
          ],
          { maxCommands: 12 },
        ),
        async (cmds) => {
          document.body.innerHTML = '';
          vi.restoreAllMocks();
          const { panel, ctl } = await mountCounting();
          const m = { panel, ctl, open: [], changes: 0, loadsAtBusy: 0, pending: false };
          await fc.asyncModelRun(() => ({ model: m, real: {} }), cmds);
          // The user closes what is open, from the top. The change that waited loads.
          while (m.open.length) await close(m.open[m.open.length - 1]).run(m);
          expect(ctl.loads).toBe(m.changes);
        },
      ),
      // HK_MODEL_RUNS sets the number of runs for a long search by hand.
      { numRuns: Number(process.env.HK_MODEL_RUNS) || runs },
    );
  }, 600_000);
});
