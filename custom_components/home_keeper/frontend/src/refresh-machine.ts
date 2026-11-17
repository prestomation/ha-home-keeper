/**
 * When the panel or the card must load the Home Keeper data again.
 *
 * A change on another surface reaches the frontend in 2 ways: a new entity
 * fingerprint in `hass` (`utils.hkStateSignal`, the `signal` event) or a pushed event
 * that has no fingerprint (the `change` event). Each one counts as 1 change in `seen`.
 * A load starts with the count it covers. When it ends with success, the data on
 * screen covers that count (`shown`), not the count when it ends. So a change that
 * arrives while a load runs causes 1 more load. A failed load covers nothing.
 *
 * The caller asks {@link shouldLoad} after each event and starts the load.
 *
 * Pure: no Home Assistant code, no DOM and no clock. The caller gives the time.
 */

/** After a failed load, a push with no new change waits this long before it tries
 *  again, so a broken backend does not get a loop of loads. A new change tries at once. */
export const LOAD_RETRY_MS = 10_000;

export interface RefreshState {
  /** The last entity fingerprint seen. */
  readonly sig: string;
  /** The number of changes seen. */
  readonly seen: number;
  /** The number of changes that the data on screen covers. */
  readonly shown: number;
  /** The value of `seen` when the running load started, or null when no load runs. */
  readonly loading: number | null;
  /** Until this time, a new fingerprint is the echo of the last load's own action. */
  readonly echoUntil: number;
  /** Until this time, only a new change starts a load. */
  readonly retryAt: number;
}

export type RefreshEvent =
  /** `hass` changed. `busy` is true while the user has a form or dialog open. */
  | { readonly type: 'signal'; readonly sig: string; readonly busy: boolean; readonly now: number }
  /** A pushed event says that the data changed. */
  | { readonly type: 'change' }
  /** A load starts. `sig` is the fingerprint now: the load reads data at least as new. */
  | { readonly type: 'start'; readonly sig: string }
  /** The load ended. `echoMs` is how long a new fingerprint after it counts as its echo. */
  | { readonly type: 'done'; readonly ok: boolean; readonly now: number; readonly echoMs: number };

export const INITIAL_REFRESH: RefreshState = {
  sig: '',
  seen: 0,
  shown: 0,
  loading: null,
  echoUntil: 0,
  retryAt: 0,
};

export function refreshStep(s: RefreshState, e: RefreshEvent): RefreshState {
  switch (e.type) {
    case 'signal': {
      if (e.sig !== s.sig) s = { ...s, ...newChange(s), sig: e.sig };
      // The echo of the panel's own action shows as a new fingerprint just after its
      // load. That load already read the change, so it does not load again.
      const echo = s.loading === null && !e.busy && e.now < s.echoUntil;
      return echo ? { ...s, shown: s.seen } : s;
    }
    case 'change':
      return { ...s, ...newChange(s) };
    case 'start':
      return { ...s, sig: e.sig, loading: s.loading ?? s.seen };
    case 'done': {
      const from = s.loading ?? s.shown;
      // Only a load that saw no change while it ran opens the echo window. A change
      // that came during the load is real, and it must load.
      const clean = e.ok && from === s.seen;
      return {
        ...s,
        shown: e.ok ? from : s.shown,
        loading: null,
        echoUntil: clean ? e.now + e.echoMs : 0,
        retryAt: e.ok ? 0 : e.now + LOAD_RETRY_MS,
      };
    }
  }
}

function newChange(s: RefreshState): Pick<RefreshState, 'seen' | 'retryAt'> {
  return { seen: s.seen + 1, retryAt: 0 };
}

/** True when the caller must start a load now. */
export function shouldLoad(s: RefreshState, busy: boolean, now: number): boolean {
  return s.loading === null && !busy && s.shown < s.seen && now >= s.retryAt;
}
