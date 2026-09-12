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
  // thing that gives. **So this is the last raise that is free.** The next tour that
  // outgrows its budget is paid for by shortening the walk — drop a beat the phone
  // tour already covers, or split the desktop one — rather than by another number.
  //
  // Where the length came from, since it is nobody's regression and everybody's:
  // 6 feature PRs edited the tour after #298 measured it at 168-174s, and each added
  // the beats its own surface needed —
  //
  //     #303 search  +4    #302 notification icons  +3    #309 import/export  +14
  //     #318 due today  +4    #321 counted wear  +7    #333 guide split  +0
  //
  // 32 beats at 900ms is ~29s, and the interactions alongside them cover the rest.
  // Every one was correct under the gate that requires a new surface to appear in the
  // tour; none moved this number. **A PR that adds a beat re-measures and moves it** —
  // run with `--timeout=600000 --reporter=list` and read the duration it reports,
  // never the cap it died at.
  //
  // **This cap is the last thing that bounds a hung tour**, and the aim is that it
  // never has to: a wait the tour controls cannot hang, because `waitForTimeout` is
  // a fixed duration, so anything that eats the whole budget is a *call that never
  // returns*. Each of those gets its own shorter cap below, so the failure names the
  // step that broke instead of surfacing as a timeout on the whole tour, and a real
  // hang costs 20-30s rather than 18 minutes over 3 attempts.
  timeout: 360_000,
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
