---
title: CI, mutation testing and Home Assistant versions
summary: What each CI workflow gates, the mutation and typing gates, vale, and how to test the right Home Assistant.
---

# CI, mutation testing and Home Assistant versions

## Workflows

| Workflow | What it does |
|---|---|
| `lint.yml` | ruff, mypy (HA installed), vale, `docs-audit`, `changelog-release-gap` |
| `test.yml` | vitest, pytest unit, HACS validation, hassfest |
| `mutation.yml` | mutmut and Stryker on the changed code, 80% gate |
| `integration.yml` | Docker integration tests, and the upgrade suite against `stable` |
| `e2e.yml` | Docker and Playwright; uploads the report on a failure. The job limit is 25 min: shard the suite before it nears that, never raise the limit again |
| `walkthrough-preview.yml` | the walkthrough gif comment ([pr-workflow.md](pr-workflow.md#walkthrough-video)) |
| `ha-beta.yml` | nightly against HA `beta`; gates nothing, files `ha-beta-regression` |
| `pytest_coverage.yml` | the coverage comment on a PR |
| `release.yml` | tags and publishes on merge ([changelog-and-release.md](changelog-and-release.md)) |

- `lint.yml` also fails when the top CHANGELOG section names an unreleased version that
  `manifest.json` does not carry, or when `manifest.json` and `PANEL_VERSION` differ.
- **A pipe hides a failure.** `pytest … | tee log` takes the exit status of `tee`. Put
  `set -o pipefail` at the top of each `run:` block that pipes a test runner, and write an
  output guard that names what must not appear, not only what must.
- **A diagnostic step must never fail the suite after it.** Version reports in
  `ha-beta.yml` carry `continue-on-error: true`.
- **A check that no PR runs shares its inputs with one that does.** `ha-beta.yml` runs
  only on a schedule, so its inputs come from files that a PR lane also reads.
- `ci/setup-ci-deps.sh` installs every CI dependency (Python into `.venv`, npm, vale,
  ffmpeg, Docker, Chromium). It is idempotent and safe to run again; `FORCE=1` reinstalls
  and `SKIP_*` leaves a part alone. A SessionStart hook runs it; the log is
  `/tmp/setup-ci-deps.log`.

## Mutation testing

`mutation.yml` gates every PR at an 80% mutation score on the code that the PR changed.

```bash
bash ci/test-mutation-python.sh            # mutmut, changed functions only
bash ci/test-mutation-frontend.sh          # Stryker, changed line ranges only
# add --all to score the whole configured surface
```

- `ci/mutation_scope.py` maps the diff to mutmut name filters (changed line to enclosing
  function) and Stryker `--mutate` ranges. Scoring whole files would fail a PR for old debt.
- **The mutable surface is an allowlist** in 1 place per language: `only_mutate` in
  `[tool.mutmut]` (`pyproject.toml`) and `mutate` in `stryker.conf.json`. It holds the
  pure Python core (including `options.py` and `device_compat.py`, whose HA imports are
  `TYPE_CHECKING`-only) and the focused frontend modules. Widen it when you add unit tests
  that make the score mean something.
- It excludes modules that import HA at run time, data modules (`const.py`, the catalogs,
  `declarative_preset_text.py`), `backend_i18n.py`, `testing.py`, and `panel.ts`, the
  `panel-*.ts` modules, `card.ts` and `api.ts`, which are covered only through the element.
- The threshold is `[tool.mutation-gate] break`, mirrored in `thresholds.break`. Both
  runners fail on a mismatch. **Never lower it to get green.**
- **Kill a surviving mutant with a real assertion.** For a genuinely equivalent mutant,
  annotate the source (`# pragma: no mutate`, `// Stryker disable next-line <mutator>`)
  with a 1-line reason. Never disable a whole file.
- A test that reads `src/*.ts` off disk goes in a `*-parity.test.js` file.
  `vitest.stryker.config.js` excludes that suffix, because under Stryker it reads mutated
  source and kills mutants it never ran.
- **Keep the root `vitest` on version 4.** The Stryker vitest runner 10.0.0 runs no test
  per mutant under vitest 5, so every mutant survives. Dependabot holds the major back.
  Before a move, `bash ci/test-mutation-frontend.sh --all` must print
  `Ran N tests per mutant on average.` with N above 0.
- A PR that changes the npm manifests, the Stryker or vitest config, or the mutation
  scripts, and no TypeScript, is scored on `limits.ts`. `ci/mutation_report.py` fails a
  run in which no test ran against a scored mutant.
- Label a PR `skip-mutation` to bypass both jobs.

## Typing and quality scale

- The integration is fully typed, ships `py.typed`, and targets the **Platinum** quality
  scale. Keep the ledger in `custom_components/home_keeper/quality_scale.yaml` current
  when a change touches a rule.
- Run mypy before you push:
  `pip install -r requirements-typing.txt && mypy custom_components/home_keeper`.
- **`requirements-typing.txt` is the only place that names a mypy dependency.** `lint.yml`,
  `ha-beta.yml` and `ci/setup-ci-deps.sh` install from it. Add a new stub package there.
- `typings/voluptuous/*.pyi` makes mypy read `voluptuous` as probatio, the way HA 2026.9
  and later alias it. Delete the stubs when the code imports probatio directly.
- User-facing exceptions are localized ([architecture.md](architecture.md#localized-text)).

## Home Assistant versions

- **PRs test `stable`.** `HA_TAG` in `tests/integration/docker-compose.yml` defaults to
  it. Override locally with `HA_TAG=beta bash ci/e2e-up.sh`. The nightly tests `beta`, about
  4 weeks before a release.
- **A job that installs HA runs on a Python at or above HA's floor, and checks what pip
  resolved.** On an older Python, pip goes back to an old HA and the job checks an API
  that nobody runs. Run `python ci/check-ha-version.py` (`--pre` for a pre-release) (#199).
- `[tool.mypy] python_version` follows HA's floor. HA's own source uses syntax from its
  minimum Python, and an older target cannot parse it.
- Read the version from `homeassistant.const.__version__`. `homeassistant.__version__`
  does not exist.

## Vale

- The `vale` job runs the pinned `ai-tells` style and the `HomeKeeper` style over the
  files that `.vale.ini` names: `README.md`, `CHANGELOG.md`, `docs/guide/**/*.md`, the
  canonical `docs/*.md`, `docs/design/architecture.md`, `website/docs/intro.md`,
  `strings.json`, `services.yaml` and `locales/en.json`.
- The job is diff-scoped (`filter_mode: added`), but a rule applies to a whole block. An
  edit to 1 line of a paragraph puts the whole paragraph in scope. Compare the set of hits
  in each edited file with `origin/main`, not only the lines you touched.
- **A clean local run is weak evidence.** The action pins its own binary. Match the
  `tokens` regexes in `styles/ai-tells/<Rule>.yml` against the block by hand. Keep at most
  1 comma in a bullet after a modal or a pronoun, or `VerbTricolon` can fire.
- Run `vale sync && vale <paths>` locally. Disable an accepted false positive in
  `.vale.ini` (`ai-tells.RuleName = NO`) or inline with `<!-- vale ai-tells.RuleName = NO -->`.
- No bot bumps the pinned `ai-tells.zip` in `.vale.ini`. Bump it by hand now and then.

## Preset upkeep

- Each integration preset pins the upstream commit last read (`verified.ref` in
  `declarative_presets_catalog.py`). Never edit a `verified` block by hand.
- `ci/check_preset_keys.py --report` lists the keys gone and added since each pin, and
  `--pin` moves the pins. `ci/find_preset_candidates.py` lists the integrations with
  duty-like keys that no preset covers, and `--mark` records a reviewed candidate in
  `ci/preset_candidates.json`.
- The scripts only find. The weekly `preset-upkeep` skill decides, edits the catalog and
  opens 1 draft PR. Neither script is a PR gate.
- The `open-work` skill only reports open work, sorted by who must act next.
- The `preview-comment` skill drafts the note that tells a reporter a preview build is
  ready. It posts the note only after the maintainer approves the exact text.
