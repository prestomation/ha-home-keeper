/**
 * The stock stepper of a part: the count that the user asks for, and the 1 save
 * that sends it.
 *
 * A tap of − or +, or a typed count, moves `target`. The host sends 1 save for the
 * difference between `target` and `stored`, and only when no save runs. Taps while a
 * save runs move `target` again, so they are kept, and the host sends 1 more save for
 * all of them when the first one ends. The backend answers with the count that it
 * stored, which can include a change from another surface. The taps that came during
 * the save stay on top of that answer. A failed save puts `target` back to `stored`,
 * and so drops the taps that waited: they were made on a count that the backend did not
 * store, and the host shows the error, so the user taps again from the stored count.
 *
 * Pure: no Home Assistant code, no DOM and no clock.
 */

import { snapStock } from './utils';

/** How long the stepper waits after the last tap before it sends, so quick taps make
 *  1 save. */
export const STOCK_SETTLE_MS = 300;

export interface StockState {
  /** The count that the backend has, as far as the panel knows. */
  readonly stored: number;
  /** The count that the user asks for. */
  readonly target: number;
  /** The count that the running save asks for, or null when no save runs. */
  readonly sending: number | null;
}

export type StockEvent =
  /** A tap of − or + moves the count by `by`. `step` is the smallest step of the part. */
  | { readonly type: 'tap'; readonly by: number; readonly step: number }
  /** The user typed a count. */
  | { readonly type: 'set'; readonly value: number; readonly step: number }
  /** The host starts the save of {@link stockDelta}. */
  | { readonly type: 'send' }
  /** The save ended. `stored` is the count in the answer, if it has one. */
  | { readonly type: 'done'; readonly ok: boolean; readonly stored?: number };

export function initialStock(stored: number): StockState {
  return { stored, target: stored, sending: null };
}

export function stockStep(s: StockState, e: StockEvent): StockState {
  switch (e.type) {
    case 'tap':
      return { ...s, target: snapStock(s.target + e.by, e.step) };
    case 'set':
      return { ...s, target: snapStock(e.value, e.step) };
    case 'send':
      return stockDelta(s) === null ? s : { ...s, sending: s.target };
    case 'done': {
      if (s.sending === null) return s;
      if (!e.ok) return { stored: s.stored, target: s.stored, sending: null };
      const stored = e.stored ?? s.sending;
      // The taps that came while the save ran stay on top of the stored count.
      const extra = s.target - s.sending;
      return { stored, target: Math.max(0, round(stored + extra)), sending: null };
    }
  }
}

/** The change that the host must send now, or null when it must not send. */
export function stockDelta(s: StockState): number | null {
  if (s.sending !== null) return null;
  const delta = round(s.target - s.stored);
  return delta === 0 ? null : delta;
}

/** Whether a save runs or waits to be sent. */
export function stockPending(s: StockState): boolean {
  return s.sending !== null || s.target !== s.stored;
}

function round(n: number): number {
  return Math.round(n * 1000) / 1000;
}
