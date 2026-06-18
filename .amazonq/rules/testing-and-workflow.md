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

## Translations (quality gates)
`strings.json` (backend) and `frontend/src/locales/en.json` are the sources of
truth. Both layers are guarded by tests — `tests/unit/test_translations_parity.py`
and `custom_components/home_keeper/frontend/test/i18n.test.js` — that enforce, for
every locale:
- **Key parity** — identical key structure to the English source (no missing/extra).
- **Placeholder parity** — same `{token}` set per key (no dropped/renamed/typo'd
  tokens), and balanced braces.
- **No untranslated leaks** — a value byte-identical to its English source fails.
  Two escape hatches only: a tiny curated `INTENTIONALLY_IDENTICAL`/`_INTENTIONALLY_IDENTICAL`
  allowlist (brand names, symbols) and a frozen *backlog* baseline of the strings
  already untranslated when the gate landed.
- **Key usage** (frontend) — every literal `t()`/`tn()` key exists in `en.json`;
  `tn()` bases have an `.other` form; no *new* unused keys.
- **Plural completeness** (frontend) — every plural base defines every CLDR
  category the locale uses (Slavic `few`/`many`, etc.), not just `.other`.

**Baselines may only shrink.** The backlogs live in
`tests/unit/translations_untranslated_baseline.json` and
`custom_components/home_keeper/frontend/test/{untranslated,unused-keys,plural-categories}-baseline.json`.
When you translate a baselined string (or wire up / delete an unused key), the
test fails as a *stale* entry until you remove it from the baseline — that is how
the debt is burned down. Never add a new entry to a baseline to silence a gate;
translate the string or justify it in the allowlist instead.

`python3 ci/i18n-coverage.py` prints per-locale coverage (informational, not a
gate); CI publishes it to the job summary.

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
