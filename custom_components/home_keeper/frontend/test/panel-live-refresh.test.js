import fc from 'fast-check';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { definePanelStubs, makeHass, mountPanel, waitFor } from './panel-harness.js';

/**
 * A change on another surface that arrives while the panel loads, or before a load
 * that fails, must still reach the screen. The panel loads again after such a load.
 */

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
  localStorage.clear();
  vi.restoreAllMocks();
});

const task = (name) => ({
  id: 'A',
  name,
  recurrence_type: 'floating',
  interval: 3,
  unit: 'months',
  enabled: true,
});

/**
 * A panel whose `get_tasks` answers only when the test says so. `server` is the task
 * name that the store holds now. A load reads it when the request arrives, as the
 * store does.
 */
async function setup() {
  const hass = makeHass({ tasks: [task('v0')] });
  const ctl = { server: 'v0', pending: [], loads: 0 };
  const base = hass.callWS;
  hass.callWS = (msg) => {
    if (msg.type !== 'home_keeper/get_tasks') return base(msg);
    ctl.loads++;
    const tasks = [task(ctl.server)];
    return new Promise((resolve, reject) => {
      ctl.pending.push({
        ok: () => resolve({ tasks }),
        fail: () => reject(new Error('boom')),
      });
    });
  };
  // The first load answers at once, so the panel mounts.
  const mounted = mountPanel('/tasks', hass);
  await waitFor(() => ctl.pending.length === 1);
  ctl.pending.shift().ok();
  const { panel } = await mounted;
  let stamp = 0;
  ctl.change = (name) => {
    ctl.server = name;
    stamp++;
    panel.hass = {
      ...hass,
      states: { 'todo.home_keeper_tasks': { last_updated: `2026-10-01T10:00:0${stamp}Z` } },
    };
  };
  ctl.shown = () => panel._tasks.map((t) => t.name).join();
  return { panel, ctl };
}

/** Let the answered load run its `finally` and any load that it starts. */
const settle = () => new Promise((r) => setTimeout(r, 30));

describe('live refresh: a change during a load', () => {
  it('loads again after a load that started before the change', async () => {
    const { panel, ctl } = await setup();
    // StartLoad: an action's refresh reads the store as it is now (v0).
    void panel._refresh();
    await waitFor(() => ctl.pending.length === 1);
    // Push: another device changes the task while that load runs.
    ctl.change('v1');
    ctl.pending.shift().ok();
    await settle();
    // The panel must load again, because the load read v0.
    await waitFor(() => ctl.pending.length === 1);
    expect(ctl.pending.length, 'a second load should start').toBe(1);
    ctl.pending.shift().ok();
    await settle();
    expect(ctl.shown()).toBe('v1');
  });

  it('loads again on a later push after a failed load', async () => {
    const { panel, ctl } = await setup();
    void panel._refresh();
    await waitFor(() => ctl.pending.length === 1);
    ctl.change('v1');
    ctl.pending.shift().fail();
    await settle();
    // No retry starts at once, so a broken backend does not get a loop of loads.
    expect(ctl.pending.length).toBe(0);
    // The next hass push after the retry wait loads the change.
    panel._live = { ...panel._live, retryAt: 0 };
    panel.hass = { ...panel.hass };
    await waitFor(() => ctl.pending.length === 1);
    expect(ctl.pending.length, 'a load should start on the next push').toBe(1);
    ctl.pending.shift().ok();
    await settle();
    expect(ctl.shown()).toBe('v1');
  });
});

/*
 * Model test on the real panel. The model is the store's version; the screen is the
 * task name that the panel shows. The clock is fake, so the echo window and the retry
 * wait follow the commands. A change from another device comes after the echo window
 * when no load runs (see `refresh-machine.test.js`).
 */
describe('live refresh model on the real panel', () => {
  const ECHO_MS = 2000;
  const T0 = Date.UTC(2026, 9, 1, 10);
  /** Let the panel run its promises and timers. The clock does not move. */
  const ticks = async () => {
    for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
  };

  async function start() {
    const { panel, ctl } = await setup();
    let clock = Date.now();
    vi.spyOn(Date, 'now').mockImplementation(() => clock);
    let stamp = 0;
    const push = () => {
      panel.hass = {
        ...panel.hass,
        states: { 'todo.home_keeper_tasks': { last_updated: new Date(T0 + stamp).toISOString() } },
      };
    };
    return {
      panel,
      ctl,
      push,
      advance: (ms) => (clock += ms),
      bump: () => stamp++,
      version: 0,
    };
  }

  const cmd = (name, check, run) => ({
    check,
    async run(m) {
      await run(m);
      await ticks();
    },
    toString: () => name,
  });
  const idle = (m) => m.ctl.pending.length === 0;
  const commands = [
    fc.constant(cmd('Refresh', idle, (m) => void m.panel._refresh())),
    fc.constant(cmd('LoadOk', (m) => !idle(m), (m) => m.ctl.pending.shift().ok())),
    fc.constant(cmd('LoadFail', (m) => !idle(m), (m) => m.ctl.pending.shift().fail())),
    fc.constant(
      cmd('OtherDevice', () => true, (m) => {
        m.ctl.server = `v${++m.version}`;
        m.bump();
        m.advance(idle(m) ? ECHO_MS + 1 : 1);
        m.push();
      }),
    ),
    fc.constant(cmd('OpenForm', (m) => !m.panel._edit.open, (m) => m.panel._openEdit(task('x')))),
    fc.constant(cmd('CloseForm', (m) => m.panel._edit.open, (m) => m.panel._closeForm())),
    fc.integer({ min: 0, max: 15_000 }).map((ms) =>
      cmd(`Wait(${ms})`, () => true, (m) => {
        m.advance(ms);
        m.push();
      }),
    ),
  ];

  it('ends on the newest data after any sequence', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const runs = Math.max(5, Math.floor(fc.readConfigureGlobal().numRuns / 8));
    await fc.assert(
      fc.asyncProperty(fc.commands(commands, { maxCommands: 12 }), async (cmds) => {
        document.body.innerHTML = '';
        const m = await start();
        try {
          await fc.asyncModelRun(() => ({ model: m, real: {} }), cmds);
          // The user goes idle, all waits end, and each load succeeds.
          if (m.panel._edit.open) m.panel._closeForm();
          m.advance(60_000);
          m.push();
          await ticks();
          for (let i = 0; i < 5 && !idle(m); i++) {
            m.ctl.pending.shift().ok();
            await ticks();
          }
          expect(idle(m), 'the loads should end').toBe(true);
          expect(m.ctl.shown(), 'the screen should show the newest data').toBe(m.ctl.server);
        } finally {
          vi.mocked(Date.now).mockRestore();
        }
      }),
      { numRuns: runs },
    );
  }, 120_000);
});
