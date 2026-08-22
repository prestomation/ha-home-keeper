# AGENTS.md — Home Keeper

## Workflow

- **Never push directly to main.** Always use a feature branch and open a PR.
- Wait for CI (tests, HACS validation, code review) and approval before merging.
- **Always squash merge PRs.**
- **CHANGELOG.md** — update for every user-facing change before tagging a release.
  Developer-only changes (CI config, AGENTS.md, IDEAS.md) don't need entries.
- **A stable release's `## [X.Y.Z]` notes describe what changed since the last
  _stable_ release — not since its betas.** When cutting `X.Y.Z` from an `X.Y.ZbN`
  line, write the section for someone upgrading from the previous stable version and
  roll the beta work into Added/Changed/Fixed as they'd perceive it. A feature
  introduced over the betas is **Added** (even if a later beta changed how it worked
  mid-stream); don't carry beta-to-beta framing — e.g. a `### Changed` for something
  that didn't exist in the last stable — into the stable section. **Include a `###
  Fixed` section listing every GitHub issue fixed by commits since the last stable**
  — check the git log for `(Fixes #N)` references and write each one into the section
  as `(Fixes #N)`.
- **A `(Fixes #N)` in a version's CHANGELOG section is what notifies and closes the
  issue.** `release.yml`'s `notify-issues` job reads the shipped version's section,
  comments on every issue it references, and closes it once the version is stable. An
  issue left out of the section is never told and never closes, so the section is the
  release's issue list, not decoration. Only closing keywords count — write
  `(Fixes #N)`; `(Related to #161)` and a bare `(#N)` are deliberately ignored,
  because `(#N)` is also the squash-merge PR number and the two can't be told apart.
  The job posts a CI warning naming any issue a shipped commit referenced that the
  section forgot.
- **Keep linking issues from a PR with `Fixes #N`.** Closing-on-merge is turned off
  for this repository, so the keyword links the PR to the issue — that's what fills in
  the issue's **Development** panel and its linked-pull-request relationship — without
  closing anything. The issue stays open until the fix actually reaches users, and
  `notify-issues` closes it on the release that carries it, so the reporter's "closed"
  notification names a version they can install.
- **Beta versioning — always use the next release number.** After every stable
  `X.Y.0` ships, immediately bump `manifest.json` and `const.py` (`PANEL_VERSION`)
  to `X.(Y+1).0b1` on `main`, and rename the `## [Unreleased]` CHANGELOG section to
  `## [X.(Y+1).0b1]`. Beta iterations go `b1 → b2 → …` until the stable
  `X.(Y+1).0` is cut. **Never use `X.Y.0bN` after `X.Y.0` has shipped** — PEP 440
  sorts those below the stable version, so HACS would offer the stable as an
  "upgrade" to anyone on the beta, which feels like a downgrade.
- **Always cut a beta release for a new feature.** A PR that adds a user-facing
  feature must bump to the next beta in the same change — `manifest.json` +
  `const.py` (`PANEL_VERSION`) to the next `bN`, with a matching `## [X.Y.0bN]`
  CHANGELOG section — so the work ships to beta testers via HACS rather than waiting
  on the floor. (If the current top CHANGELOG section is an already-released beta,
  open the next `bN`; if it's an unreleased beta still being iterated, fold the
  feature into it.) Bug-fix-only / developer-only PRs don't need a fresh beta.
- **Always add the `preview-release` label to a new-feature PR.** As soon as the PR
  is open, apply the `preview-release` label so `preview-release.yml` publishes an
  installable ephemeral pre-release (`X.Y.Z.dev<pr>`) from the PR head — testers can
  try the feature via HACS *before* merge. The build is ephemeral and auto-deletes
  when the PR closes (see RELEASE.md → "Preview releases"). Bug-fix-only /
  developer-only PRs don't need it.
- **Always run tests locally before pushing.** Never use CI as the test runner.
  - Pure-logic unit tests need only `pip install pytest`: `pytest tests/unit -v`.
  - Full unit suite uses `pip install pytest-homeassistant-custom-component`.
- **Mutation testing gates every PR** at an 80% mutation score on the code the PR
  changed — see "Mutation testing" below. It is too slow for the
  run-before-you-push loop; run it when you touch the mutable surface.
- **User-facing prose is linted for AI-tell phrasing.** `lint.yml`'s `vale` job runs
  the [vale-ai-tells](https://github.com/tbhb/vale-ai-tells) Vale style (pinned in
  `.vale.ini`) over `README.md`, `CHANGELOG.md`, the canonical `docs/*.md` (not the
  scratch `*_PLAN.md`/research docs), `website/docs/intro.md`, `strings.json`,
  `services.yaml`, and the English frontend locale (`locales/en.json`), catching
  things like "delve", "it's important to note", em-dash overuse, and other
  AI-writing tells. **It's diff-scoped** (`filter_mode: added`): only lines your PR
  touches are checked, so it's a real gate on new prose without failing on the
  existing backlog. Run it locally with `vale sync && vale <paths>` (Vale CLI from
  [github.com/errata-ai/vale releases](https://github.com/errata-ai/vale/releases)).
  For an accepted false positive, either disable the rule for that file in
  `.vale.ini` (`ai-tells.RuleName = NO`) or wrap the exception inline with
  `<!-- vale ai-tells.RuleName = NO -->` / `<!-- vale ai-tells.RuleName = YES -->`.
  Diff-scoping only checks added/changed lines, so a wholesale rewrite of a file's
  prose (not just a small edit) can surface pre-existing hits on lines that just
  moved. Run `vale <file>` on the whole file yourself before a rewrite-style PR to
  catch those ahead of CI. There's no automated version-bump for the pinned
  `ai-tells.zip` release in `.vale.ini` (Dependabot/Renovate don't track raw
  GitHub release URLs), so bump it by hand occasionally, e.g. alongside the next
  full-corpus cleanup pass.
- **Every PR that touches the panel UI MUST include screenshots — no exceptions.**
  This is a hard gate: a UI change is not reviewable (or mergeable) until the PR
  body embeds current screenshots of the changed surface. The capture harness is
  `tests/e2e/screenshots.capture.ts` (the test) driven by `screenshots.config.ts`
  (the config — **pass this one to `--config`**, not the test file itself).
  Step-by-step:
  ```bash
  # 1. Start HA and leave it running (from repo root)
  KEEP_UP=1 bash ci/e2e-up.sh

  # 2. Run the capture — from tests/e2e/
  cd tests/e2e
  SHOT_DIR=../../docs/images \
    npx playwright test --config=screenshots.config.ts
  ```
  **In the Claude Code remote environment `npx playwright install chromium` fails**
  (the CDN is blocked by the proxy). Chromium is pre-installed at
  `/opt/pw-browsers/`. Set `CHROMIUM_EXEC` to use it — `playwright.config.ts`
  already wires it up:
  ```bash
  CHROMIUM_EXEC=$(ls /opt/pw-browsers/chromium-*/chrome-linux/chrome 2>/dev/null | head -1) \
    SHOT_DIR=../../docs/images \
    npx playwright test --config=screenshots.config.ts
  ```
  Commit PNG(s) under `docs/images/`, and embed them in the PR via a
  `raw.githubusercontent.com/<owner>/<repo>/<commit-sha>/docs/images/<file>.png`
  URL pinned to the commit that added them. When a change adds a new UI surface,
  add a capture step for it to the capture script in the same PR.
  - **Embed PR-body screenshots with an HTML `<img src="…" alt="…" width="820">`
    tag, not markdown `![](…)`.** The `update_pull_request` path can silently wrap a
    markdown image URL in double backticks (a code span), breaking the image — and it
    may hit only some of several identical-looking lines. HTML `<img>` avoids markdown
    link parsing. Keep the SHA-pinned `src` (branch names have slashes and are
    ambiguous for `raw.githubusercontent.com`). After editing the body, re-read it to
    confirm the URLs weren't mangled and verify each returns HTTP 200. (In-repo
    README/docs markdown with relative `docs/images/…` paths is fine — this only bites
    PR/issue bodies set through the API.)
  - **Always visually inspect every captured screenshot before committing it.** Read
    the PNG file with the Read tool and look at the rendered image. Confirm the
    changed surface is visible and correct — dialogs show their heading and buttons,
    lists are populated, no blank or clipped content. If a screenshot looks wrong
    (empty dialog, missing elements, `position:fixed` overlay not visible in a
    fullPage capture), diagnose the root cause and fix it before committing. Do not
    commit screenshots that don't clearly show the intended UI state.
- **Every PR that adds a _new user-facing UI feature_ MUST keep the video walkthrough
  current — but you don't capture or commit it; CI does.** Screenshots prove a surface
  renders; a video proves the *interaction* works (the flow, the transitions, the
  motion). The walkthrough is a **CI build artifact, never committed**: on every PR,
  `walkthrough-preview.yml` stands up the seeded HA container, runs the capture
  harness, transcodes to gif+mp4, publishes them to the `gh-pages`
  `pr-preview-media/pr-<n>/` umbrella (served by GitHub Pages), and posts/updates a
  **sticky PR comment** embedding the gif (with an mp4 link). Nothing lands in
  `docs/videos/` in git — that directory is gitignored — so there's zero repo bloat,
  and the comment always reflects the PR's HEAD.
  - **The gate for a feature PR is: the walkthrough comment renders the new surface.**
    Since the tour is generated, "keeping it current" means **editing the tour**, not
    capturing a file: when a feature adds a brand-new UI surface, extend
    `tests/e2e/walkthrough.capture.ts` to step through it (deliberate `BEAT` pauses so
    the motion reads well) **in the same PR**, then confirm the regenerated comment
    shows it. (Pure bug-fix / styling / copy PRs don't need to touch the tour.)
  - **Capture is a _soft_ gate.** A flaky Playwright run posts a "capture failed" note
    (with a logs link) instead of blocking the PR; pushing again re-runs it. If the
    comment is missing or stale, check the `walkthrough-preview.yml` run — don't
    hand-commit a video to work around it.
  - **Run it locally to debug the tour** (the harness still works standalone). From the
    repo root, with ffmpeg on PATH:
    ```bash
    KEEP_UP=1 bash ci/e2e-up.sh        # build panel + start HA
    # In the Claude Code remote env, point Playwright at the pre-installed Chromium:
    CHROMIUM_EXEC=$(ls /opt/pw-browsers/chromium-*/chrome-linux/chrome 2>/dev/null | head -1) \
      bash ci/capture-video.sh         # writes gif/mp4 to docs/videos/ (gitignored)
    ```
    Open the resulting `docs/videos/walkthrough.gif` with the Read tool and confirm the
    tour shows the intended surfaces — populated lists, the feature's flow, no
    blank/stuck frames — before relying on CI to publish it.
  - **Why a comment and not the PR/README body:** GitHub's issue/PR-body sanitizer
    *strips* a committed-file HTML `video` tag entirely, and committing the gif bloats
    git history with multi-MB binaries that never delta-compress. Hosting the gif on
    Pages and embedding it via the comment keeps motion visible while leaving `main`
    clean. (The only path that inline-*plays* an mp4 is a drag-and-drop
    `user-attachments` upload, which CI can't produce — so the gif still carries the
    motion and the mp4 is a link.)
- **Always document new major features in `README.md` in the same change.** Add a
  brief section with the **use cases** (what problem it solves) and a little about
  **how it's used**, and include **screenshot(s)** (same Playwright capture, committed
  under `docs/images/`, embedded with a relative `docs/images/…` path). A headline
  feature isn't done until the README shows it. (The moving walkthrough is **not** in
  the README — it's the per-PR CI comment described above; the README stays on
  committed screenshots.)
- **Always request an Amazon Q (Cue) review after every push and when opening a
  PR.** Immediately after pushing a commit (or opening a PR), post a PR comment
  of the form `/q review {request}`. Cue gives better results when explicitly
  asked for *critical, skeptical* feedback, so tailor the `{request}` to the
  change and name the topics you want scrutinized — e.g. **correctness** (edge
  cases, timezone/DST, off-by-one, error paths), **maintainability** (module
  boundaries, naming, duplication, readability), **performance** (hot paths,
  redundant work, N+1 / full reloads), **security**, and **HA best practices**.
  Ask it to surface the most serious issues first and not to withhold minor ones.
  Then triage its findings as usual (fix the valid ones; push back, with
  reasoning, on false positives).
- **Never comment on a GitHub issue.** Issues are where users talk to the
  maintainer, and an agent posting there answers on the maintainer's behalf to
  someone who didn't ask for it. Findings, analysis and status belong in the PR
  that carries the work, or in the reply to whoever asked. A PR that fixes an
  issue links it (`Fixes #N`) and the release that ships it closes it, which is the
  only signal an issue needs. This does **not** restrict PR comments: the `/q review`
  request above and replies to review threads are still required.
  - The ban is on **you** posting. It does not cover repo automation, which posts
    from a fixed template as the mechanical consequence of an event nobody has to
    interpret: `release.yml`'s `notify-issues` job (a release shipped the fix) and
    `ha-beta.yml`'s regression reporter (the nightly went red). Adding a comment to
    an issue by hand, or by asking an agent to, is still off-limits — if something
    needs saying there, the maintainer says it.

## Conventions live in `.amazonq/rules/` — keep them current

Project conventions and opinionated development decisions are recorded as Amazon Q
project rules under [`.amazonq/rules/`](.amazonq/rules/) (Markdown files Amazon Q
auto-loads as context). They currently cover architecture/code conventions and
testing/workflow.

**Whenever we establish or change a convention or opinionated development aspect**
— in a conversation, a review thread, or a decision captured in a PR — **update
`.amazonq/rules/` in the same change** (and this `AGENTS.md` if it's a
workflow/process rule) so both Amazon Q and Claude pick it up automatically. Treat
this as part of "done": a new convention isn't real until it's written into the
rules. Keep the rules and `AGENTS.md` consistent with each other.

## Project structure

- **Domain:** `home_keeper`. **Display name:** Home Keeper.
- **Backend:** `custom_components/home_keeper/`. The recurrence engine
  (`recurrence.py`) and task model (`models.py`) are pure Python (no HA imports) so
  they are unit-testable in isolation — keep them that way.
- **Storage:** local, single JSON document `.storage/home_keeper`.
- **Frontend:** TypeScript + Rollup at `custom_components/home_keeper/frontend/`.
  Source in `src/*.ts`, builds to `dist/home-keeper-panel.js` (gitignored, built by
  CI; only `dist/` is served as a static path, since HA serves those pre-auth;
  see `ci/build-panel.sh`).
- **Admin vs usage:** management lives in the **sidebar panel** (a custom HA panel);
  usage is exposed via native `todo`/`calendar` entities and per-task device-page
  entities. Don't blur these — administration stays in the panel. That split is also
  the **privilege boundary**: the panel is `require_admin=True`, and an admin-only
  operation must be gated in *both* its websocket command and its service twin, or
  `call_service` walks around the gate. See `docs/SECURITY.md` and
  `.amazonq/rules/architecture-and-code.md` → "Privilege model".
- **Docs site:** `website/` is a Docusaurus site deployed to GitHub Pages
  (https://prestomation.github.io/ha-home-keeper/). It has a **User Guide** and a
  **Developer Guide** (the `docs/INTEGRATING.md` equivalent). **The content pages are
  generated, not authored** — `website/scripts/sync-docs.mjs` splits `README.md` into
  the User Guide (`website/docs/guide/`, gitignored) and copies `docs/INTEGRATING.md` /
  `docs/GLUE_INTEGRATIONS.md` / `docs/EVENTS.md` / `docs/DESIGN.md` into the Developer
  Guide (`website/developer/`, gitignored), rewriting links/images. **Edit the canonical sources (`README.md`,
  `docs/*.md`), never the generated trees.** `README.md` therefore stays the
  comprehensive user doc (it's the source) — don't "slim" it. Screenshots are likewise
  not duplicated: `website/scripts/sync-assets.mjs` mirrors `docs/images/` into the
  static tree, so `docs/images/` stays the single home for screenshots and the
  UI-screenshots gate is unchanged. Both run via `npm run sync` (wired into
  prestart/prebuild/pretypecheck). **Production deploys on stable GitHub Release
  publication** (not on push to `main`) — the live site is always pinned to the
  latest stable release so users never see docs for unreleased features; **every PR
  gets a live preview** at `pr-preview/pr-<n>/` (see `website/README.md`).

## Conventions

- **Expose every data action as a `home_keeper.*` service.** Any operation that
  mutates or exports Home Keeper data — task/asset CRUD, exports (inventory),
  stock adjustments, and anything new — must ship as a Home Assistant **service**
  for general interoperability (automations, scripts, voice, other integrations).
  A panel **websocket command** is only a UI optimization and is never a substitute
  for the service: add the service first (with a `services.yaml` entry and
  `strings.json` localization parity), and have any websocket command delegate to
  the same store method. See `.amazonq/rules/architecture-and-code.md`.
- **Fire a `home_keeper_<noun>_<verb>` event for every state change.** Built by a pure
  builder in `events.py`, fired at the `store.py` chokepoint (including the non-CRUD
  mutation paths), edge-triggered for transitions (`transitions.py` + the coordinator,
  baselined silently on startup). A new event isn't done until it's in `docs/EVENTS.md`
  and, if device-facing, in `device_trigger.py` with translation-parity labels. Events
  need no new service. See `.amazonq/rules/architecture-and-code.md` and `docs/EVENTS.md`.
- Tasks are plain dicts: `id, name, notes, recurrence_type, interval, unit|freq,
  anchor, device_id, area_id, enabled, last_completed, next_due, completions[]`.
- All datetimes are timezone-aware (`homeassistant.util.dt`); `recurrence.py` takes
  an explicit `now` so tests are deterministic.
- Entity unique IDs are anchored to the task `id` (survives renames).
- Per-task device-page entities are created only for tasks with a `device_id`.
- Escape all user content before innerHTML injection in the panel (`escapeHTML`).
- Panel navigation is high-fidelity deep-linked: every destination (tab, detail
  page) maps to a URL under `/home-keeper`, the `route` prop is the single source
  of truth, and Back/Forward move within the panel — never mutate view/detail
  state directly to navigate. See `.amazonq/rules/architecture-and-code.md`.

## Companion discovery (implemented)

Integrations that work with Home Keeper surface in the panel's **Settings →
Companions** section. Two paths feed one in-memory registry: integrations
*self-register* via the `home_keeper.register_companion` service (push), and Home
Keeper *detects* a small curated catalog of popular upstreams and suggests their glue
(pull). See `companions.py` / `companions_catalog.py` and
`.amazonq/rules/architecture-and-code.md` → "Companion discovery".

## Cross-integration contribution (task push) — partially deferred

The `add_task` + `home_keeper_task_completed` contract for *pushing tasks* ships and is
documented in `docs/INTEGRATING.md`. The fuller dedicated **upsert/reconcile**
contribution service is still deferred — hook point `const.SIGNAL_TASK_CONTRIBUTION`.
See IDEAS.md before building it.

## Mutation testing (a PR gate)

Coverage measures that a line *ran*. Mutation testing measures whether a test
would have **failed** if that line were wrong — the difference between a suite
that executes the code and one that actually asserts on it.

`mutation.yml` runs on every PR, in two jobs:

```bash
bash ci/test-mutation-python.sh            # mutmut, changed functions only
bash ci/test-mutation-python.sh --all      # the whole configured surface
bash ci/test-mutation-frontend.sh          # Stryker, changed line ranges only
bash ci/test-mutation-frontend.sh --all
```

- **It only scores what your branch touched.** `ci/mutation_scope.py` maps the
  diff to mutmut mutant-name filters (changed line → enclosing function,
  decorators included, via `ast`) and to Stryker `--mutate` line ranges. Scoping
  to whole files would fail a PR for debt it didn't create.
- **The mutable surface is an allowlist**, in exactly one place per language:
  `only_mutate` in `[tool.mutmut]` (pyproject.toml) and `mutate` in
  `stryker.conf.json`. It holds the pure Python core (`recurrence`, `models`,
  `assets`, `reconcile`, `notifications`, `sensor_tasks`, `problem_tasks`,
  `inventory`, `profiles`, `documents`, `events`, `transitions`) and the focused
  frontend modules (`utils`, `forms`, `card-filter`, `documents`, `markdown`,
  `i18n`, `limits`). Excluded on purpose: everything importing Home Assistant
  (only the Docker tiers cover it — far too slow to run once per mutant),
  `const.py` / `companions_catalog.py` (data, not logic), `backend_i18n.py` (pure
  but with no unit-test entry point), `testing.py` (already coverage-omitted), and
  `panel.ts` / `card.ts` / `api.ts` (only indirectly covered; ~7k lines that would
  score near zero). Widen the allowlist when you add unit tests that would make
  the score mean something.
- **The gate is a mutation score of 80%**, set in `[tool.mutation-gate] break` and
  mirrored in `thresholds.break` (stryker.conf.json). The two runners compare them
  and fail on a mismatch, so they cannot drift.
- **Kill surviving mutants with real assertions.** If a mutant is genuinely
  *equivalent* — it cannot change observable behaviour — annotate it at the source
  (`# pragma: no mutate`, `// Stryker disable next-line <mutator>`) with a one-line
  reason. Never blanket-disable a file, and never lower the threshold to get green.
- **Tests that read `src/*.ts` off disk belong in a `*-parity.test.js` file.**
  Inside Stryker's sandbox they read *mutated* source, so any mutant touching a
  string literal turns them red and is scored as "killed" by a test that never ran
  the behaviour — `forms.ts` alone has dozens of `t('…')` call sites, so this
  inflates the score badly. `vitest.stryker.config.js` excludes that suffix; the
  normal `ci/test-frontend.sh` run still includes it.
- Label a PR `skip-mutation` to bypass both jobs.

`tests/conftest.py` executes the pure modules under their **real** dotted name
(`custom_components.home_keeper.<mod>`, with stub parent packages so the
HA-importing `__init__.py` never runs) and registers `hk.<mod>` / `hk_<mod>` as
aliases. Keep it that way: mutmut matches a mutant's path-derived key against the
function's `__module__`, and a mismatch makes every mutant look untested. `hk`
itself must stay a **distinct** package object, not another alias of
`custom_components.home_keeper` — `from . import x` resolves through the parent's
`__name__`, so aliasing the two makes the modules that `test_coordinator_purge.py`
and `test_calendar.py` load as `hk.coordinator` pull in the real HA-importing
siblings instead of their fakes.

## Browser e2e tests (Playwright)

- Location: `tests/e2e/` drives a real browser against the same HA Docker container
  as `tests/integration`, on the seeded `home-keeper-e2e` YAML dashboard and the
  `/home-keeper` panel.
- Run locally / in a session: `bash ci/e2e-up.sh` (builds the panel, starts HA, runs
  Playwright, tears down). `KEEP_UP=1` leaves HA running.
- Env prep: `ci/setup-browser-env.sh` (wired to a Claude Code SessionStart hook).
- Auth: `tests/e2e/global-setup.ts` completes onboarding and performs a real login.

## Typing & quality scale

- The integration is **fully typed** and targets the **Platinum** quality scale
  (`manifest.json` `quality_scale`; per-rule ledger in
  `custom_components/home_keeper/quality_scale.yaml`). `lint.yml` runs `mypy` against
  the integration with Home Assistant installed — keep it error-free, and run it
  locally (`pip install mypy homeassistant && mypy custom_components/home_keeper`)
  before pushing. User-facing exceptions must be localized (translation keys under
  `strings.json` → `exceptions`); see `.amazonq/rules/`.

## CI

- `lint.yml` — ruff lint + format check, and **mypy** strict typing (HA installed).
- `test.yml` — vitest, pytest unit, HACS validation, hassfest.
- `mutation.yml` — mutation testing (mutmut + Stryker) on the code a PR changed;
  fails below an 80% mutation score. `skip-mutation` label bypasses it.
- `integration.yml` — Docker-based integration tests.
- `e2e.yml` — Docker + Playwright; uploads the Playwright report on failure.
- `ha-beta.yml` — **nightly early warning**, gates nothing. Runs integration, e2e and
  the upgrade suite against `HA_TAG=beta`, plus mypy against a pre-release HA, and
  files/updates a single `ha-beta-regression` issue on failure.
- `pytest_coverage.yml` + `post_coverage_to_pr.yml` — coverage comment on PRs.
- `release.yml` — PR-merge-driven release (see RELEASE.md). Its `notify-issues` job
  tells every issue the version fixes which release carries the fix, and closes them
  on a stable. Rehearse it against a past release with a `workflow_dispatch` run and
  `notify_dry_run: true`.

### Home Assistant versions

- **PRs test `stable`** — what users actually run. The container version is
  `HA_TAG` in `tests/integration/docker-compose.yml`, defaulting to `stable`;
  override it locally with `HA_TAG=beta bash ci/e2e-up.sh`.
- **A nightly tests `beta`.** HA beta week is public ~4 weeks ahead of a release, so
  this is the warning window. HA 2026.8 split devices per config entry and broke
  device attachment (#183) with no advance signal, which is why this exists.
- **Anything resting on an HA framework contract** — device registry, entity registry,
  device automation — **needs an integration-level assertion.** A unit test mocks the
  framework and cannot see the contract change. #183 shipped because the only
  device-attachment coverage was for the *self-owned* case.
- **Cross-version behaviour needs an upgrade test**, not just a fresh-boot test:
  `tests/upgrade/` boots a frozen pre-split HA, seeds, then boots the current one
  against the same config dir so HA runs its own migration in between. Stage its
  fixtures with `bash ci/fetch-glues.sh` first. The pre-split pin is frozen on
  purpose — bumping it changes what the test means.
- **Any job that `pip install`s Home Assistant must run on a Python at or above HA's
  own floor, and must verify what pip actually resolved.** When the runner's Python
  is too old, pip does not fail — it quietly backtracks to the last HA release that
  supported it, and the job goes green having checked an API nobody runs. HA 2026.3
  moved to Python >=3.14.2, which silently pinned both mypy jobs to HA 2026.2.3 for
  months (#199). Every such job runs `python ci/check-ha-version.py` (add `--pre`
  when installing with `pip install --pre`), which fails on a stale resolve.
- **`[tool.mypy] python_version` tracks HA's floor, not ours.** HA's source uses
  syntax from its own minimum Python (2026.8 uses PEP 758 parenthesis-free
  `except A, B:`); target anything older and mypy cannot parse HA at all — it exits
  on a syntax error having checked nothing.
- **A diagnostic step must never be able to fail the suite it precedes.** The
  version-report steps in `ha-beta.yml` are informational, so they carry
  `continue-on-error: true`. #199 was a one-line version `print` that aborted a whole
  nightly and filed a regression issue against a Home Keeper that was working fine.
