# AGENTS.md — Home Keeper

## Workflow

- **Never push directly to main.** Always use a feature branch and open a PR.
- Wait for CI (tests, HACS validation, code review) and approval before merging.
- **Always squash merge PRs.**
- **CHANGELOG.md** — update for every user-facing change before tagging a release.
  Developer-only changes (CI config, AGENTS.md, IDEAS.md) don't need entries.
- **Always run tests locally before pushing.** Never use CI as the test runner.
  - Pure-logic unit tests need only `pip install pytest`: `pytest tests/unit -v`.
  - Full unit suite uses `pip install pytest-homeassistant-custom-component`.
- **Always post screenshots to the PR when a change adds, changes, or fixes UI.**
  Capture with the Playwright harness (`tests/e2e/screenshots.capture.ts`), commit
  the PNG(s) under `docs/images/`, and embed them in the PR via a
  `raw.githubusercontent.com/<owner>/<repo>/<commit-sha>/docs/images/<file>.png`
  URL pinned to the commit that added them.

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

- Tasks are plain dicts: `id, name, notes, recurrence_type, interval, unit|freq,
  anchor, device_id, area_id, enabled, last_completed, next_due, completions[]`.
- All datetimes are timezone-aware (`homeassistant.util.dt`); `recurrence.py` takes
  an explicit `now` so tests are deterministic.
- Entity unique IDs are anchored to the task `id` (survives renames).
- Per-task device-page entities are created only for tasks with a `device_id`.
- Escape all user content before innerHTML injection in the panel (`escapeHTML`).

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

## CI

- `test.yml` — vitest, pytest unit, HACS validation, hassfest.
- `integration.yml` — Docker-based integration tests.
- `e2e.yml` — Docker + Playwright; uploads the Playwright report on failure.
- `pytest_coverage.yml` + `post_coverage_to_pr.yml` — coverage comment on PRs.
- `release.yml` — PR-merge-driven release (see RELEASE.md).
