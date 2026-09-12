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
  // Fresh measurements, September 2026, on a tour that has grown several surfaces
  // since: **204s on CI** (green), **234s on CI** on the very next push of the same
  // branch, and **210s in the dev container**. The 234s run then failed — it spent
  // its last seconds inside a 40s wait at the closing step — and its first retry hit
  // 240s outright. The tour is unchanged between those 2 CI runs and so is the
  // panel, so the spread is the runner, and 240s had stopped being a margin: 204s
  // leaves 15%, and one slower runner is over the line.
  //
  // 360s is the highest of those figures plus ~54%. Read the next timeout the same
  // way round — the margin first — but a *lengthening* tour is the other half of
  // this: at 3 attempts, 6 minutes each, the job's own 30-minute cap is the next
  // thing that gives.
  //
  // **This cap is the only thing that bounds a hung tour.** `actionTimeout` below
  // does not: it applies to Playwright *actions* (click, fill), and the tour is
  // mostly `page.waitForTimeout(BEAT)`, which nothing but this budget stops. What
  // `actionTimeout` buys is that one bad selector fails in 20s instead of eating the
  // whole budget and reporting the timeout in the wrong place. Both matter; they are
  // not the same guard.
  timeout: 360_000,
  use: {
    // The base config leaves actionTimeout unset (0 = no per-action cap), so a
    // click on a momentarily-unstable element would hang for the whole test budget.
    // Cap it so any bad selector fails fast and visibly instead — the failure then
    // names the step that broke, rather than surfacing as a timeout on the whole
    // tour. It bounds actions only; see the note on `timeout` above.
    actionTimeout: 20_000,
  },
});
