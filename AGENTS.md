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
  that didn't exist in the last stable — into the stable section.
- **Always run tests locally before pushing.** Never use CI as the test runner.
  - Pure-logic unit tests need only `pip install pytest`: `pytest tests/unit -v`.
  - Full unit suite uses `pip install pytest-homeassistant-custom-component`.
- **Every PR that touches the panel UI MUST include screenshots — no exceptions.**
  This is a hard gate: a UI change is not reviewable (or mergeable) until the PR
  body embeds current screenshots of the changed surface. Capture them with the
  Playwright harness (`tests/e2e/screenshots.capture.ts`; bring HA up with
  `KEEP_UP=1 bash ci/e2e-up.sh`, then run the capture config), commit the PNG(s)
  under `docs/images/`, and embed them in the PR via a
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
- **Always document new major features in `README.md` in the same change.** Add a
  brief section with the **use cases** (what problem it solves) and a little about
  **how it's used**, and include **screenshot(s)** (same Playwright capture, committed
  under `docs/images/`, embedded with a relative `docs/images/…` path). A headline
  feature isn't done until the README shows it.
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
  Source in `src/*.ts`, builds to `home-keeper-panel.js` (gitignored, built by CI;
  see `ci/build-panel.sh`).
- **Admin vs usage:** management lives in the **sidebar panel** (a custom HA panel);
  usage is exposed via native `todo`/`calendar` entities and per-task device-page
  entities. Don't blur these — administration stays in the panel.

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

## Cross-integration contribution (DEFERRED)

The stable interface for other integrations (e.g. Battery Notes) to push tasks is
not implemented yet. Hook points: `const.SIGNAL_TASK_CONTRIBUTION` and the
`# DEFERRED` marker in `__init__.py`. See IDEAS.md before building it.

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
- `integration.yml` — Docker-based integration tests.
- `e2e.yml` — Docker + Playwright; uploads the Playwright report on failure.
- `pytest_coverage.yml` + `post_coverage_to_pr.yml` — coverage comment on PRs.
- `release.yml` — PR-merge-driven release (see RELEASE.md).
