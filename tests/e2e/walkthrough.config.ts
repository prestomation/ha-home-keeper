/** Config for the one-off video walkthrough capture (see walkthrough.capture.ts). */
import { captureConfig } from './capture-config';

export default captureConfig('walkthrough.capture.ts', {
  // The narrated tour (with deliberate pauses) plus the video flush runs well past
  // the default 60s per-test budget — give it room.
  //
  // 180s was not room enough. The desktop tour is a fixed sequence of `BEAT` pauses
  // and real interactions, so its wall clock is close to constant, and 180s left it
  // under ten seconds of margin: #298 timed out on all three attempts, while the
  // phone tour, at 24s, passed every time.
  //
  // Measured, once the budget was loose enough for a run to report its own length
  // rather than the cap it died at: **168s on CI, 168-174s in the dev container.**
  // So CI is not the slower machine — the tour simply sits on the line, and ordinary
  // run-to-run variance is what carries it over. That is worth knowing before anyone
  // "optimises" the tour: there is no CI-specific slowness to hunt.
  //
  // 240s is that measurement plus ~40%. It is not a round number picked to be safe;
  // move it only against a fresh one. A loose per-test budget is not the guard
  // against a hung tour anyway — `actionTimeout` below is, and it fails a bad
  // selector in 20s. This cap only has to clear the tour's own length.
  timeout: 240_000,
  use: {
    // The base config leaves actionTimeout unset (0 = no per-action cap), so a
    // click on a momentarily-unstable element would hang for the whole test budget.
    // Cap it so any bad selector fails fast and visibly instead.
    actionTimeout: 20_000,
  },
});
