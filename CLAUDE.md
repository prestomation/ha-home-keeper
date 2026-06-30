# Home Keeper — Claude Code memory

@AGENTS.md

The project's workflow, conventions, and **hard gates** live in `AGENTS.md`
(imported above) and `.amazonq/rules/`. Read them before pushing.

Two gates worth repeating because they are easy to miss:

- **Every PR that touches the panel UI (`custom_components/home_keeper/frontend/src/`)
  MUST include current screenshots** of the changed surface — captured with the
  Playwright harness, committed under `docs/images/`, and embedded in the PR body
  (SHA-pinned `raw.githubusercontent.com` URL, HTML `<img>` tag).
- **Every PR that adds a _new user-facing UI feature_ MUST also include a short
  video walkthrough** of that surface — captured with `ci/capture-video.sh`
  (`tests/e2e/walkthrough.capture.ts`), committed under `docs/videos/` as `mp4` +
  `gif`, and embedded in the PR body (SHA-pinned `<video>` plus an `<img>` GIF
  fallback). Pure bug-fix / styling PRs stay on the screenshots gate only.

See AGENTS.md "Workflow" for both.
