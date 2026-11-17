/**
 * Which form draft a server answer belongs to.
 *
 * A form save is slow: the answer comes after the user can close the form and open a
 * new one. The answer to the old draft must not change the new draft. Each draft has a
 * number, `current`. A save reads `current` when it starts and sends it back with its
 * answer. An answer for another number is stale and the form ignores it.
 *
 * Pure: no Home Assistant code and no DOM. The panel and the card keep 1 state and
 * move it with {@link draftStep}.
 */

/** `verdict` is the result of the last `answer` event, and `none` before the first. */
export interface DraftState {
  /** The number of the draft that is open now, or that was open last. */
  readonly current: number;
  readonly verdict: 'none' | 'fresh' | 'stale';
}

export type DraftEvent =
  /** The draft is replaced: a form opens, closes, or a navigation drops it. */
  | { readonly type: 'replace' }
  /** The server answered the save that started on draft `draftId`. */
  | { readonly type: 'answer'; readonly draftId: number };

export const INITIAL_DRAFT: DraftState = { current: 0, verdict: 'none' };

export function draftStep(state: DraftState, event: DraftEvent): DraftState {
  if (event.type === 'replace') {
    return { current: state.current + 1, verdict: 'none' };
  }
  return {
    current: state.current,
    verdict: event.draftId === state.current ? 'fresh' : 'stale',
  };
}
