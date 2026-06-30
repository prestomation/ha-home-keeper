# Home Keeper — testing & workflow conventions

## Git & PR workflow
- Never push directly to `main`. Work on a feature branch and open a PR; squash
  merge.
- Update `CHANGELOG.md` for every user-facing change before a release.
- Post screenshots to the PR for any change that adds/changes/fixes UI (capture
  via `tests/e2e/screenshots.capture.ts`, commit under `docs/images/`, embed via
  a `raw.githubusercontent.com/.../<commit-sha>/docs/images/<file>.png` URL).
- **The video walkthrough is a CI build artifact, never committed** — for a PR that
  adds a _new user-facing UI feature_, CI keeps it current (bug-fix/styling PRs need
  only screenshots). `walkthrough-preview.yml` runs the capture harness
  (`tests/e2e/walkthrough.capture.ts` → `walkthrough.config.ts`, wrapped by
  `ci/capture-video.sh`) on every PR, transcodes to gif+mp4, publishes them to the
  `gh-pages` `pr-preview-media/pr-<n>/` umbrella (GitHub Pages), and posts a **sticky
  PR comment** embedding the gif with an mp4 link. `docs/videos/` is gitignored, so
  there's zero git bloat. The author's gate is *editing the tour*: extend
  `walkthrough.capture.ts` for a new surface in the same PR and confirm the
  regenerated comment shows it; capture is a soft gate (a flaky run posts a failure
  note, doesn't block). Run `ci/capture-video.sh` locally only to debug the tour.
- **Document new major features in `README.md` in the same change** — add a brief
  section covering the **use cases** (what problem it solves) and a little about
  **how it's used**, with **screenshot(s)** (capture via the Playwright harness,
  commit under `docs/images/`, embed in the README with a relative `docs/images/…`
  path). A new headline feature isn't "done" until the README shows it. (The moving
  walkthrough is **not** committed to the README — it's the per-PR CI comment above.)

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

## Translations (quality gates)
`strings.json` (backend) and `frontend/src/locales/en.json` are the sources of
truth. Both layers are guarded by tests — `tests/unit/test_translations_parity.py`
and `custom_components/home_keeper/frontend/test/i18n.test.js` — that enforce, for
every locale:
- **Key parity** — identical key structure to the English source (no missing/extra).
- **Placeholder parity** — same `{token}` set per key (no dropped/renamed/typo'd
  tokens), and balanced braces.
- **No untranslated leaks** — a value byte-identical to its English source is a
  hard failure. Two allowlists are the only escape hatches: a tiny global
  `INTENTIONALLY_IDENTICAL`/`_INTENTIONALLY_IDENTICAL` (product name, symbols, the
  bare-`{prompt}` passthrough) and a per-locale `COGNATE_IDENTICAL`/`_COGNATE_IDENTICAL`
  for reviewed cognates/loanwords (e.g. German "Name", French "Stock", universal
  "Delta"/"Model"/"Link"). Adding a string to a locale means translating it or
  justifying it in the per-locale allowlist — never leaving it in English.
- **Key usage** (frontend) — every literal `t()`/`tn()` key exists in `en.json`;
  `tn()` bases have an `.other` form; no *new* unused keys.
- **Plural completeness** (frontend) — every plural base defines every CLDR
  category the locale uses (Slavic `few`/`many`, etc.), not just `.other`.

The only remaining baseline is `unused-keys-baseline.json` (frontend dead-key
detection is heuristic, so its backlog is frozen and **may only shrink**): wire up
or delete a baselined key and the test fails it as stale until you remove the
entry. There is no untranslated/plural backlog — those gates are absolute.

`python3 ci/i18n-coverage.py` prints per-locale coverage (informational, not a
gate); CI publishes it to the job summary.

## Release
- `manifest.json` `version` is the single source of truth. A release PR bumps it,
  bumps `const.py` `PANEL_VERSION` to match, and adds a `## [X.Y.Z]`
  `CHANGELOG.md` section. PEP 440 pre-release suffixes (`bN`/`aN`/`rcN`) ship as
  GitHub pre-releases → HACS beta channel.
- **Beta versioning — always use the next release number.** After every stable
  `X.Y.0` ships, immediately bump `manifest.json` and `const.py` to `X.(Y+1).0b1`
  on `main`, and rename the `## [Unreleased]` CHANGELOG section to
  `## [X.(Y+1).0b1]`. Beta iterations go `b1 → b2 → …`. Never cut `X.Y.0bN`
  betas after `X.Y.0` has shipped — PEP 440 sorts them below stable, causing HACS
  to offer the stable as an "upgrade" to beta users.
- **Always cut a beta release for a new feature.** A PR adding a user-facing
  feature bumps to the next beta in the same change (`manifest.json` + `const.py`
  `PANEL_VERSION` → next `bN`, plus a matching `## [X.Y.0bN]` CHANGELOG section)
  so it reaches beta testers. Fold into the current top beta if it's still
  unreleased; otherwise open the next `bN`. Bug-fix/developer-only PRs don't.
- **Always add the `preview-release` label to a new-feature PR** once it's open, so
  `preview-release.yml` publishes an installable ephemeral pre-release
  (`X.Y.Z.dev<pr>`) from the PR head for pre-merge HACS testing (auto-deleted on
  close; see RELEASE.md). Bug-fix/developer-only PRs don't.
- The built `home-keeper-panel.js` is gitignored; CI builds it.

## Typing (strict-typing gate — Platinum)
- The integration is **fully typed** and ships `custom_components/home_keeper/py.typed`.
  `lint.yml` runs `mypy custom_components/home_keeper` with Home Assistant installed
  (so HA's own types resolve); config is `[tool.mypy]` in `pyproject.toml`. Keep it
  error-free — a new untyped def or a real type mismatch fails CI.
- Run it locally before pushing: `pip install mypy homeassistant && mypy
  custom_components/home_keeper`. The pure modules (`models.py`, `recurrence.py`,
  `events.py`) stay HA-free and type-check standalone.

## Quality scale
- Home Keeper targets **Platinum** (`manifest.json` `quality_scale`), with the
  per-rule ledger in `custom_components/home_keeper/quality_scale.yaml`. Keep the
  ledger current: when you add a capability that touches a rule (a new entity
  category, a repair, discovery, an external dependency, …), update its status in
  the same change. Networking/discovery/auth rules are `exempt` (local, deviceless).

## Amazon Q reviews
- After every push and when opening a PR, request a critical Amazon Q review by
  commenting `/q review {request}`. Ask explicitly for *critical/skeptical*
  feedback and name the topics to scrutinize (correctness, maintainability,
  performance, security, HA best practices), most-serious-first.
