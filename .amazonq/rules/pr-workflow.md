---
title: PR workflow
summary: The branch, review, screenshot, walkthrough and documentation gates that every Home Keeper PR passes.
---

# PR workflow

## Branches, checks and merges

- Never push to `main`. Work on a feature branch, open a PR, and squash merge it.
- **Every check is green, and the PR has approval, before a merge.** A failure that the
  change did not cause is still the change's to clear: fix it, or land the fix first and
  merge it in. Never merge on a red run or on a run that is still going.
- **A green check is not proof.** A step with `continue-on-error` is green whatever
  happens. Read what it produced: the walkthrough comment, the coverage comment, the
  preview links. When a soft gate can hide a real failure, make it a hard gate.
- Run the tests locally before you push. CI is not the test runner ([testing.md](testing.md)).
- **A plan lives in the PR body**, never in a plan file. It starts with the CHANGELOG
  bullet that it will ship ([changelog-and-release.md](changelog-and-release.md)). A
  bullet that does not come out cleanly in 3 sentences tells you the scope is wrong.
- **One-way doors.** A one-way door is a choice that is hard to reverse after users
  depend on it: the name, shape or format of a service field, an event payload, storage,
  an entity attribute, a user-data key, or another external contract. The plan names
  each one before work starts. The PR body has a **One-way doors** section that lists
  each committed surface: the field, its format, where it appears, and what automations
  will rely on. Frontend form data and private helpers are not one-way doors.
- **Ask Amazon Q for a review after each push and when you open the PR.** Post a PR
  comment `/q review {request}`. Ask for critical, skeptical feedback, most serious
  first, and name the topics: correctness (edge cases, time zones, error paths),
  maintainability, performance, security, and Home Assistant practice. Fix the valid
  findings. Reply with a reason to a false positive.
- **Never comment on a GitHub issue.** Issues are where users talk to the maintainer.
  Findings and status go in the PR or in the reply to the person who asked. The PR links
  the issue with `Fixes #N` and the release closes it. PR comments, `/q review` and
  replies to review threads are still required. Repo automation that posts from a fixed
  template (`notify-issues` in `release.yml`, the `ha-beta.yml` reporter) is allowed.
  There is 1 exception: the preview-build note of the `preview-comment` skill
  (`.claude/skills/preview-comment/SKILL.md`). The maintainer must ask for it in the current
  session. The agent shows the exact final text first, and posts it unchanged only after the
  maintainer approves that text.
- Commit messages, PR bodies and code comments follow STE, but the CHANGELOG budget and
  vale do not apply to them.

## Screenshots: desktop and phone

Every PR that touches `custom_components/home_keeper/frontend/src/` must embed current
screenshots of each changed surface in the PR body: **a desktop shot and a phone shot**.
Below 700px the panel is a different layout. The tabs move to the bottom, Add floats,
the filter becomes wrapping chips, and rows stack. A desktop-only shot leaves that half
unreviewed.

1. Start Home Assistant and leave it running: `KEEP_UP=1 bash ci/e2e-up.sh`.
2. Capture from `tests/e2e/`. Pass `screenshots.config.ts` to `--config`, not the test:

   ```bash
   cd tests/e2e
   CHROMIUM_EXEC=$(ls /opt/pw-browsers/chromium-*/chrome-linux/chrome 2>/dev/null | head -1) \
     SHOT_DIR=../../docs/images npx playwright test --config=screenshots.config.ts
   ```

   In the Claude Code remote environment `npx playwright install chromium` fails, so
   `CHROMIUM_EXEC` points at the Chromium in `/opt/pw-browsers/`.
3. When a change adds a surface, add a step for it to `tests/e2e/screenshots.capture.ts`.
   Add the phone step to the `page.setViewportSize(PHONE)` block at the end of the file,
   and name it with a `-mobile-` segment so the pair sorts together:
   `57-panel-task-search.png` and `57c-panel-mobile-task-search.png`.
4. **Open every PNG with the Read tool before you commit it.** Make sure that the changed
   surface shows: dialogs have their heading and buttons, lists are full, and no content
   is blank or clipped. Fix the cause of a bad shot.
5. Commit the PNGs under `docs/images/`. A screenshot documents a surface. It does not
   test it, so make sure that a spec in `tests/e2e/tests/` asserts on each new surface.

Embed each image with an HTML tag, `<img src="…" alt="…" width="820">`, not Markdown
`![](…)`. The `src` is a `raw.githubusercontent.com/<owner>/<repo>/<sha>/docs/images/<file>.png`
URL pinned to the commit that added the file. The PR update path can wrap an image in a
code span:

- Write attribute text with no character-entity reference. Reword around an apostrophe.
- If an unchanged body still comes back mangled after 2 submissions, the file name is
  the trigger. Rename the PNG in the capture script and shoot again.
- After each body edit, read the body again and check that each URL returns HTTP 200.

## Walkthrough video

A PR that adds a **new user-facing UI feature** keeps the walkthrough current. CI makes
the video. You never commit one: `docs/videos/` is gitignored.

- `walkthrough-preview.yml` runs `tests/e2e/walkthrough.capture.ts` on every PR,
  publishes a gif and an mp4 to the `gh-pages` `pr-preview-media/pr-<n>/` folder, and
  posts a sticky PR comment with the gif.
- **The gate is editing the tour.** When a feature adds a surface, extend
  `walkthrough.capture.ts` with `BEAT` pauses in the same PR. Then confirm that the new
  comment shows the surface. A bug-fix, styling or copy PR does not touch the tour.
- **Capture is a hard gate.** A failed capture fails the check. Debug locally, never
  push again and hope:

  ```bash
  KEEP_UP=1 bash ci/e2e-up.sh
  CHROMIUM_EXEC=$(ls /opt/pw-browsers/chromium-*/chrome-linux/chrome 2>/dev/null | head -1) \
    bash ci/capture-video.sh   # writes docs/videos/walkthrough.gif
  ```

  Open the gif with the Read tool and check that the tour shows the new flow.
- **A new beat means a new budget measurement.** The desktop walk is a fixed list of
  pauses, so its time only grows. Measure with
  `npx playwright test --config=walkthrough.config.ts --timeout=600000 --reporter=list`,
  read the reported duration, and set `timeout` in `walkthrough.config.ts` to that plus
  about 40%. The cap is 360s, and that is the last free raise: the job's own 30-minute
  cap is next. A tour that outgrows it gets a shorter walk.
- Set `actionTimeout` and `navigationTimeout` in a capture config, so that a stuck step
  fails in seconds and names itself.
- The walkthrough records 1 browser context per width (`TOURS` in the capture file),
  because `recordVideo.size` is fixed per context. A phone tour has its own beats.

## User documentation

- **Document a new major feature in `docs/guide/` in the same change.** Write the use
  cases and how to use it, with screenshots embedded by a relative `../../images/…` path.
- A new guide page needs a `USER_SECTIONS` entry in `website/scripts/doc-map.mjs`, or the
  site build fails.
- `README.md` is the repository front page and stays short. Feature detail does not go there.
- Edit the canonical sources (`docs/guide/**/*.md`, `docs/*.md`). Never edit the
  generated `website/docs/guide/` or `website/developer/`.
- **A UI change with a subjective visual choice starts with an artifact.** Mock up the
  options in the panel's own tokens, with real markup, at desktop and phone width. Agree
  on one before you write the plan. A change with one obvious rendering does not need it.
