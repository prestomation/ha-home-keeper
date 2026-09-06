/** Config for the one-off video walkthrough capture (see walkthrough.capture.ts). */
import { captureConfig } from './capture-config';

export default captureConfig('walkthrough.capture.ts', {
  // The narrated tour (with deliberate pauses) plus the video flush runs well past
  // the default 60s per-test budget — give it room.
  //
  // 180s was not room enough. The desktop tour is a fixed sequence of `BEAT` pauses
  // and real interactions, so its wall clock is close to constant: it measures
  // 168-174s in the dev container, which left under ten seconds of margin. A slower
  // CI runner spends that, and #298 timed out on all three attempts (the phone tour,
  // at 24s, passed every time).
  //
  // **How much slower CI is, is not known.** A timed-out test reports the cap, not
  // its own length, so those three attempts establish only that the tour needs more
  // than 180s there — not how much more. That is why this is 300s rather than a
  // tighter number fitted to a guess: the next green run prints the tour's real CI
  // duration, and the budget can be tightened against that measurement instead.
  //
  // A loose per-test budget is not the guard against a hung tour anyway —
  // `actionTimeout` below is, and it fails a bad selector in 20s. This cap only has
  // to be clear of the tour's own length.
  timeout: 300_000,
  use: {
    // The base config leaves actionTimeout unset (0 = no per-action cap), so a
    // click on a momentarily-unstable element would hang for the whole test budget.
    // Cap it so any bad selector fails fast and visibly instead.
    actionTimeout: 20_000,
  },
});
