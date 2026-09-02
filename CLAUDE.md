# Home Keeper — Claude Code memory

@AGENTS.md

The project's workflow, conventions, and **hard gates** live in `AGENTS.md`
(imported above) and `.amazonq/rules/`. Read them before pushing.

**All user-facing prose is Simplified Technical English (ASD-STE100)** — `README.md`,
`docs/*.md`, `CHANGELOG.md`, `strings.json`, `services.yaml`, the frontend locale. One
idea per sentence, active voice, imperative for instructions, one word for one meaning,
no idiom, no `-ing` word as a subject. See AGENTS.md "Workflow" for the full rule and
for the three `ai-tells` vale patterns that STE's short sentences tend to trip.

Three gates worth repeating because they are easy to miss:

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

- **`mutation.yml` gates every PR at an 80% mutation score on the code it changed**
  (mutmut for Python, Stryker for TypeScript). A surviving mutant means a test
  executes that code without asserting anything that would catch it being wrong —
  kill it with a real assertion, or annotate a genuinely equivalent mutant with a
  reason. Never lower the threshold to get green. The mutable surface is an
  allowlist: `only_mutate` in `[tool.mutmut]` and `mutate` in `stryker.conf.json`
  (the pure Python core — including `options.py`, whose HA imports are
  `TYPE_CHECKING`-only — plus the focused frontend modules).

See AGENTS.md "Workflow" for the first two and "Mutation testing" for the third.
