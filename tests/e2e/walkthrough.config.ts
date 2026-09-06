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
  // at 24s, passed every time). The budget is not a knob to tune per run — raise it
  // once, well clear of the tour's own length, so the capture fails only when the
  // tour is actually broken.
  timeout: 300_000,
  use: {
    // The base config leaves actionTimeout unset (0 = no per-action cap), so a
    // click on a momentarily-unstable element would hang for the whole test budget.
    // Cap it so any bad selector fails fast and visibly instead.
    actionTimeout: 20_000,
  },
});
