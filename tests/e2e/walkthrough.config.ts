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
  // One CI figure inside the local range is not proof that CI never runs slower —
  // it is one sample against three timeouts — but it is enough to say the tour sits
  // on the line at 180s rather than that CI is systematically slow. Read a future
  // timeout that way round: suspect the margin first, and only go looking for
  // CI-specific slowness if a green run ever reports a length the container cannot
  // reproduce.
  //
  // 240s was that measurement plus ~40%, and the base config gives CI `retries: 2`,
  // so the tour has three independent attempts at it. Move the number against a
  // fresh measurement, not a hunch.
  //
  // **Re-measured at 204s**, which is why 240s then failed. #321 added the counted
  // wear item beats — a new surface the tour has to show — and grew the desktop walk
  // by ~35s without touching this number, so the margin fell from ~40% to ~15% and
  // the tour started timing out on luck rather than on a defect. Nothing in the
  // change that finally went red touched the panel at all.
  //
  // That is the failure mode to expect here: the tour only ever gets longer, because
  // every feature that adds a surface adds beats to it. **A PR that adds a beat
  // re-measures and moves this number** — run the tour with `--timeout=600000
  // --reporter=list` and read the duration it reports, rather than the cap it died
  // at. 300s is 204s plus ~45%.
  //
  // The margin is not slack to spend: it absorbs a loaded runner, and `retries: 2`
  // does not help when the tour is over the cap every time.
  //
  // **This cap is the only thing that bounds a hung tour.** `actionTimeout` below
  // does not: it applies to Playwright *actions* (click, fill), and the tour is
  // mostly `page.waitForTimeout(BEAT)`, which nothing but this budget stops. What
  // `actionTimeout` buys is that one bad selector fails in 20s instead of eating the
  // whole budget and reporting the timeout in the wrong place. Both matter; they are
  // not the same guard.
  timeout: 300_000,
  use: {
    // The base config leaves actionTimeout unset (0 = no per-action cap), so a
    // click on a momentarily-unstable element would hang for the whole test budget.
    // Cap it so any bad selector fails fast and visibly instead — the failure then
    // names the step that broke, rather than surfacing as a timeout on the whole
    // tour. It bounds actions only; see the note on `timeout` above.
    actionTimeout: 20_000,
  },
});
