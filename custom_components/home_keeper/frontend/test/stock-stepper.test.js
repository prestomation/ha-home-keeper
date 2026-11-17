import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import {
  STOCK_SETTLE_MS,
  initialStock,
  stockDelta,
  stockPending,
  stockStep,
} from '../src/stock-stepper.ts';

const run = (s, ...events) => events.reduce(stockStep, s);
const tap = (by, step = 1) => ({ type: 'tap', by, step });
const SEND = { type: 'send' };
const ok = (stored) => ({ type: 'done', ok: true, stored });

describe('stockStep', () => {
  it('starts with the stored count and no save', () => {
    expect(initialStock(4)).toEqual({ stored: 4, target: 4, sending: null });
    expect(stockDelta(initialStock(4))).toBeNull();
    expect(stockPending(initialStock(4))).toBe(false);
    expect(STOCK_SETTLE_MS).toBe(300);
  });

  it('merges taps into 1 target and 1 change', () => {
    const s = run(initialStock(2), tap(1), tap(1), tap(-1), tap(1));
    expect(s).toEqual({ stored: 2, target: 4, sending: null });
    expect(stockDelta(s)).toBe(2);
    expect(stockPending(s)).toBe(true);
  });

  it('snaps a tap and a typed count to the step and never goes below 0', () => {
    expect(run(initialStock(0), tap(-1)).target).toBe(0);
    expect(run(initialStock(1), { type: 'set', value: 4.4, step: 1 }).target).toBe(4);
    expect(run(initialStock(1), { type: 'set', value: -3, step: 1 }).target).toBe(0);
    expect(run(initialStock(0.5), tap(0.25, 0.001)).target).toBe(0.75);
  });

  it('sends only when no save runs, and only a real change', () => {
    expect(run(initialStock(2), SEND)).toEqual(initialStock(2));
    const sending = run(initialStock(2), tap(1), SEND);
    expect(sending).toEqual({ stored: 2, target: 3, sending: 3 });
    expect(stockDelta(sending)).toBeNull();
    expect(stockPending(sending)).toBe(true);
    const more = run(sending, tap(1), tap(1));
    expect(stockDelta(more)).toBeNull();
    expect(run(more, SEND)).toBe(more);
  });

  it('keeps the taps that came during a save, on top of the stored answer', () => {
    const s = run(initialStock(2), tap(1), SEND, tap(1), tap(1), tap(1), ok(3));
    expect(s).toEqual({ stored: 3, target: 6, sending: null });
    expect(stockDelta(s)).toBe(3);
  });

  it('keeps the taps on top of a count that another surface changed', () => {
    // The backend had 7, not 2: the answer of +1 is 8, and the 2 later taps make 10.
    const s = run(initialStock(2), tap(1), SEND, tap(1), tap(1), ok(8));
    expect(s).toEqual({ stored: 8, target: 10, sending: null });
  });

  it('takes the sent count when the answer has none', () => {
    expect(run(initialStock(2), tap(1), SEND, { type: 'done', ok: true })).toEqual(initialStock(3));
  });

  it('puts the stored count back after a failed save, with the later taps', () => {
    const s = run(initialStock(2), tap(1), SEND, tap(1), { type: 'done', ok: false });
    expect(s).toEqual(initialStock(2));
    expect(stockPending(s)).toBe(false);
  });

  it('changes nothing when a save ends that did not start', () => {
    const s = run(initialStock(2), tap(1));
    expect(stockStep(s, ok(9))).toBe(s);
    expect(stockStep(s, { type: 'done', ok: false })).toBe(s);
  });

  it('rounds the change to thousandths', () => {
    const s = run(initialStock(0.1), tap(0.2, 0.001));
    expect(stockDelta(s)).toBe(0.2);
    const done = run(s, SEND, tap(0.1, 0.001), ok(0.3));
    expect(done.target).toBe(0.4);
  });
});

/*
 * Model test. The fake backend holds a count, and another surface can change it. The
 * model keeps the user's taps since the last failure. When the user stops and every
 * save ends well, the backend holds the count from before plus those taps, and the
 * machine sent at most 1 save at a time.
 */
describe('stock stepper model', () => {
  const commands = [
    fc.constantFrom(1, -1, 2).map((by) => ({
      check: () => true,
      run(m) {
        m.s = stockStep(m.s, tap(by));
        m.taps.push(by);
      },
      toString: () => `Tap(${by})`,
    })),
    fc.constant({
      check: () => true,
      run(m) {
        const delta = stockDelta(m.s);
        m.s = stockStep(m.s, SEND);
        if (delta !== null) {
          expect(m.inFlight).toBeNull();
          m.inFlight = delta;
        }
      },
      toString: () => 'Send',
    }),
    fc.boolean().map((good) => ({
      check: (m) => m.inFlight !== null,
      run(m) {
        if (good) {
          m.server = Math.max(0, m.server + m.inFlight);
          m.s = stockStep(m.s, ok(m.server));
          m.known = true;
        } else {
          m.s = stockStep(m.s, { type: 'done', ok: false });
          // The taps so far are lost: the user starts again from the stored count. A
          // change from another surface stays unknown until the next answer.
          m.base = m.s.stored;
          m.drift = m.server - m.s.stored;
          m.known = m.drift === 0;
          m.taps = [];
        }
        m.inFlight = null;
      },
      toString: () => (good ? 'Ok' : 'Fail'),
    })),
    fc.integer({ min: 0, max: 3 }).map((by) => ({
      // Another surface adds to the stock while a save runs, so its answer has the change.
      check: (m) => m.inFlight !== null,
      run(m) {
        m.server += by;
        m.drift += by;
      },
      toString: () => `Other(${by})`,
    })),
  ];

  it('ends on the count from before plus the taps, with 1 save at a time', () => {
    fc.assert(
      fc.property(fc.commands(commands, { maxCommands: 25 }), (cmds) => {
        const m = {
          s: initialStock(5),
          server: 5,
          base: 5,
          drift: 0,
          taps: [],
          inFlight: null,
          known: true,
        };
        fc.modelRun(() => ({ model: m, real: {} }), cmds);
        // The user stops. Each save that still comes ends well.
        for (let i = 0; i < 5; i++) {
          if (m.inFlight !== null) {
            m.server = Math.max(0, m.server + m.inFlight);
            m.s = stockStep(m.s, ok(m.server));
            m.inFlight = null;
            m.known = true;
          }
          const delta = stockDelta(m.s);
          if (delta !== null) {
            m.s = stockStep(m.s, SEND);
            m.inFlight = delta;
          }
        }
        expect(m.inFlight).toBeNull();
        expect(stockPending(m.s)).toBe(false);
        // A count never goes below 0, so the taps add up with a floor at 0 on the way.
        // With no tap that hits the floor, the total is the plain sum.
        let wanted = m.base;
        for (const by of m.taps) wanted = Math.max(0, wanted + by);
        if (!m.taps.some((by) => by < 0)) expect(m.server).toBe(wanted + m.drift);
        // The machine knows the count of the backend after an answer.
        if (m.known) expect(m.s.stored).toBe(m.server);
      }),
    );
  });
});
