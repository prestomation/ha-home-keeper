import fc from 'fast-check';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { definePanelStubs, makeHass, waitFor } from './panel-harness.js';
import { STOCK_SETTLE_MS } from '../src/stock-stepper.ts';

/**
 * The stock stepper on the appliance page: taps while a save runs are kept. The panel
 * merges them into 1 target value and sends 1 save for them after the save that runs.
 */

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

const asset = () => ({
  id: 'a1',
  kind: 'virtual',
  name: 'Water heater',
  parts: [{ id: 'p1', name: 'Anode rod', type: 'wear', stock: 2, reorder_at: 1 }],
});

/** A panel on the appliance page whose stock saves wait until the test answers them. */
async function setup() {
  const store = asset();
  const hass = makeHass({ assets: [store] });
  const base = hass.callWS;
  const ctl = { saves: [], pending: [], inFlight: 0, maxInFlight: 0 };
  hass.callWS = (msg) => {
    if (msg.type === 'home_keeper/get_assets') {
      return Promise.resolve({ assets: [JSON.parse(JSON.stringify(store))] });
    }
    if (msg.type !== 'home_keeper/adjust_part_stock') return base(msg);
    ctl.saves.push(msg.delta);
    ctl.inFlight++;
    ctl.maxInFlight = Math.max(ctl.maxInFlight, ctl.inFlight);
    return new Promise((resolve, reject) => {
      ctl.pending.push({
        ok: () => {
          ctl.inFlight--;
          const part = store.parts[0];
          part.stock = Math.max(0, part.stock + msg.delta);
          resolve({ asset: JSON.parse(JSON.stringify(store)) });
        },
        fail: () => {
          ctl.inFlight--;
          reject(new Error('nope'));
        },
      });
    });
  };
  ctl.store = store;
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/appliances/a1' };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('.hk-stock[data-part="p1"]'));
  return { panel, ctl };
}

const stepper = (panel) => panel.shadowRoot.querySelector('.hk-stock[data-part="p1"]');
const shown = (panel) => stepper(panel)?.querySelector('input').value;
const tap = (panel, sign) => stepper(panel).querySelector(sign > 0 ? '.hk-stock-inc' : '.hk-stock-dec').click();
const settle = (ms = 30) => new Promise((r) => setTimeout(r, ms));

describe('stock stepper: taps while a save runs', () => {
  it('keeps 3 taps that come while a save runs and sends them as 1 save', async () => {
    const { panel, ctl } = await setup();
    tap(panel, 1);
    await waitFor(() => ctl.saves.length === 1);
    expect(ctl.saves).toEqual([1]);
    tap(panel, 1);
    tap(panel, 1);
    tap(panel, 1);
    expect(shown(panel)).toBe('6');
    ctl.pending.shift().ok();
    await waitFor(() => ctl.saves.length === 2);
    expect(ctl.saves).toEqual([1, 3]);
    ctl.pending.shift().ok();
    await waitFor(() => shown(panel) === '6' && ctl.inFlight === 0 && !ctl.pending.length);
    await settle(600);
    expect(ctl.store.parts[0].stock).toBe(6);
    expect(ctl.saves).toEqual([1, 3]);
  });

  it('sends 1 save for quick taps before any save', async () => {
    const { panel, ctl } = await setup();
    tap(panel, 1);
    tap(panel, 1);
    tap(panel, -1);
    tap(panel, 1);
    await waitFor(() => ctl.saves.length === 1);
    await settle(600);
    expect(ctl.saves).toEqual([2]);
    ctl.pending.shift().ok();
    await waitFor(() => shown(panel) === '4');
    expect(ctl.store.parts[0].stock).toBe(4);
  });

  it('puts the stored count back after a failed save', async () => {
    const { panel, ctl } = await setup();
    tap(panel, 1);
    await waitFor(() => ctl.saves.length === 1);
    tap(panel, 1);
    ctl.pending.shift().fail();
    await settle(600);
    expect(ctl.saves).toEqual([1]);
    expect(shown(panel)).toBe('2');
    expect(stepper(panel).hasAttribute('data-busy')).toBe(false);
  });
});

/*
 * Model test on the real panel. The model is the count that the user asks for: the
 * stored count plus the taps that were not lost to a failed save. After the user
 * stops and the saves end, the store and the screen hold that count, and at most 1
 * save runs at a time.
 */
describe('stock stepper model on the real panel', () => {
  const cmd = (name, check, run) => ({
    check,
    async run(m) {
      await run(m);
      await settle(5);
      expect(m.ctl.maxInFlight, `saves in flight after ${name}`).toBeLessThanOrEqual(1);
    },
    toString: () => name,
  });
  const commands = [
    fc.constantFrom(1, -1).map((sign) =>
      cmd(`Tap(${sign})`, () => true, (m) => {
        tap(m.panel, sign);
        m.wanted = Math.max(0, m.wanted + sign);
      }),
    ),
    fc.constant(
      cmd('SaveOk', (m) => m.ctl.pending.length > 0, (m) => m.ctl.pending.shift().ok()),
    ),
    fc.constant(
      cmd('SaveFail', (m) => m.ctl.pending.length > 0, (m) => {
        m.ctl.pending.shift().fail();
        // A failed save puts the stored count back: the taps since then are lost.
        m.failed = true;
      }),
    ),
    fc.constant(cmd('Wait', () => true, () => settle(STOCK_SETTLE_MS + 50))),
  ];

  it('ends on the count that the user asked for, with 1 save at a time', async () => {
    const runs = Math.max(5, Math.floor(fc.readConfigureGlobal().numRuns / 20));
    await fc.assert(
      fc.asyncProperty(fc.commands(commands, { maxCommands: 10 }), async (cmds) => {
        document.body.innerHTML = '';
        const { panel, ctl } = await setup();
        const m = { panel, ctl, wanted: 2, failed: false };
        await fc.asyncModelRun(() => ({ model: m, real: {} }), cmds);
        // The user stops, and each save that still comes ends well.
        for (let i = 0; i < 4; i++) {
          await settle(STOCK_SETTLE_MS + 30);
          while (ctl.pending.length) ctl.pending.shift().ok();
        }
        await settle(50);
        expect(ctl.maxInFlight).toBeLessThanOrEqual(1);
        expect(shown(panel)).toBe(String(ctl.store.parts[0].stock));
        if (!m.failed) expect(ctl.store.parts[0].stock).toBe(m.wanted);
      }),
      { numRuns: Number(process.env.HK_MODEL_RUNS) || runs },
    );
  }, 600_000);
});
