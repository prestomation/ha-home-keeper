# Home Keeper — testing & workflow conventions

## Git & PR workflow
- Never push directly to `main`. Work on a feature branch and open a PR; squash
  merge.
- Update `CHANGELOG.md` for every user-facing change before a release.
- Post screenshots to the PR for any change that adds/changes/fixes UI (capture
  via `tests/e2e/screenshots.capture.ts`, commit under `docs/images/`, embed via
  a `raw.githubusercontent.com/.../<commit-sha>/docs/images/<file>.png` URL).
- **Document new major features in `README.md` in the same change** — add a brief
  section covering the **use cases** (what problem it solves) and a little about
  **how it's used**, with **screenshot(s)** (capture via the Playwright harness,
  commit under `docs/images/`, embed in the README with a relative `docs/images/…`
  path). A new headline feature isn't "done" until the README shows it.

## Tests (run locally before pushing — never use CI as the test runner)
- The recurrence engine and model are the correctness core: keep them HA-free and
  thoroughly unit-tested. `pytest tests/unit` must run without the HA harness.
- Layers: `tests/unit` (pytest, pure logic), `tests/frontend` +
  `frontend/test` (vitest), `tests/integration` (Docker HA), `tests/e2e`
  (Playwright). Run e2e/integration with `bash ci/e2e-up.sh` /
  `ci/test-python-integration.sh`.
- After running the Docker HA container locally, restore the seeded fixtures
  (`tests/integration/ha_config/.storage/{home_keeper,core.config_entries}`);
  don't commit runtime-mutated state.

## Release
- `manifest.json` `version` is the single source of truth. A release PR bumps it,
  bumps `const.py` `PANEL_VERSION` to match, and adds a `## [X.Y.Z]`
  `CHANGELOG.md` section. PEP 440 pre-release suffixes (`bN`/`aN`/`rcN`) ship as
  GitHub pre-releases → HACS beta channel.
- The built `home-keeper-panel.js` is gitignored; CI builds it.

## Amazon Q reviews
- After every push and when opening a PR, request a critical Amazon Q review by
  commenting `/q review {request}`. Ask explicitly for *critical/skeptical*
  feedback and name the topics to scrutinize (correctness, maintainability,
  performance, security, HA best practices), most-serious-first.
