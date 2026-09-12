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
  // **Re-measured at 204s**, which is why 240s then failed. No single PR did that:
  // 6 feature PRs have edited the tour since #298 took the measurement above, and
  // each added the beats its own surface needed —
  //
  //     #303 search  +4    #302 notification icons  +3    #309 import/export  +14
  //     #318 due today  +4    #321 counted wear  +7    #333 guide split  +0
  //
  // 32 beats at 900ms is ~29s, and the interactions those PRs added alongside them
  // cover the rest of the ~33s. Every one was a correct change under the gate that
  // requires a new surface to appear in the tour; the mistake was that none of them
  // moved this number, so the margin fell from ~40% to ~15% and the tour began
  // timing out on luck. It finally went red on a change that touched no panel code.
  //
  // So this is nobody's regression and everybody's: the tour only ever gets longer.
  // **A PR that adds a beat re-measures and moves this number** — run the tour with
  // `--timeout=600000 --reporter=list` and read the duration it reports, rather than
  // the cap it died at. 300s is 204s plus ~45%, which is ~96s of headroom.
  //
  // That headroom is not slack to spend: it absorbs a loaded runner, and `retries: 2`
  // does not help when the tour is over the cap every time. **Past ~360s, stop
  // raising this and shorten the tour instead** — drop a beat the phone walk already
  // covers, or split the desktop walk in two. A 6-minute test that runs 3 times is
  // not a gate anyone waits for.
  //
  // **This cap is the last thing that bounds a hung tour**, and the aim is that it
  // never has to: a wait the tour controls cannot hang, because `waitForTimeout` is
  // a fixed duration, so anything that eats the whole budget is a *call that never
  // returns*. Each of those gets its own shorter cap below, so the failure names the
  // step that broke instead of surfacing as a timeout on the whole tour, and a real
  // hang costs 20-30s rather than 15 minutes over 3 attempts.
  timeout: 300_000,
  use: {
    // The base config leaves actionTimeout unset (0 = no per-action cap), so a
    // click on a momentarily-unstable element would hang for the whole test budget.
    // Cap it so any bad selector fails fast and visibly instead — the failure then
    // names the step that broke, rather than surfacing as a timeout on the whole
    // tour. It bounds actions only; see the note on `timeout` above.
    actionTimeout: 20_000,
    // `actionTimeout` does **not** cover navigation, and the base config leaves that
    // uncapped too — so `page.goto('/home-keeper')`, which the tour calls several
    // times, was the one call in it that could genuinely hang forever. That is the
    // hole the per-test budget was quietly covering. 30s is well past a healthy
    // panel load (~1s) and well under the budget, so a stuck navigation now fails
    // naming itself.
    navigationTimeout: 30_000,
  },
});
