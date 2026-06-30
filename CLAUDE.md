# Home Keeper — Claude Code memory

@AGENTS.md

The project's workflow, conventions, and **hard gates** live in `AGENTS.md`
(imported above) and `.amazonq/rules/`. Read them before pushing.

Two gates worth repeating because they are easy to miss:

- **Every PR that touches the panel UI (`custom_components/home_keeper/frontend/src/`)
  MUST include current screenshots** of the changed surface — captured with the
  Playwright harness, committed under `docs/images/`, and embedded in the PR body
  (SHA-pinned `raw.githubusercontent.com` URL, HTML `<img>` tag).
- **Every PR that adds a _new user-facing UI feature_ MUST keep the video walkthrough
  current — but CI captures and posts it; you never commit a video.**
  `walkthrough-preview.yml` runs the `tests/e2e/walkthrough.capture.ts` harness on
  every PR, publishes the gif/mp4 to the `gh-pages` `pr-preview-media/` umbrella, and
  posts a **sticky PR comment** embedding the gif. The gate is *editing the tour*: when
  a feature adds a new surface, extend `walkthrough.capture.ts` to step through it in
  the same PR, then confirm the regenerated comment shows it. `docs/videos/` is
  gitignored (zero repo bloat); capture is a soft gate. Pure bug-fix / styling PRs
  stay on the screenshots gate only.

See AGENTS.md "Workflow" for both.
