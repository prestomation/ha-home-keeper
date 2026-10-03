---
title: Testing rules
summary: Which test tier covers what, how to write a test that can fail, and the e2e and translation gates.
---

# Testing rules

Run the tests locally before you push. CI is not the test runner.

## Tiers and how to run them

| Tier | Where | Run |
|---|---|---|
| Unit (pure core) | `tests/unit` | `pytest tests/unit` |
| Frontend | `tests/frontend`, `frontend/test` | `bash ci/test-frontend.sh` |
| Integration | `tests/integration` (Docker HA) | `bash ci/test-python-integration.sh` |
| Browser | `tests/e2e` (Playwright) | `bash ci/e2e-up.sh` |
| Upgrade | `tests/upgrade` | stage fixtures with `bash ci/fetch-glues.sh` first |

- The pure unit lane needs only `pip install pytest PyYAML Babel hypothesis jsonschema`.
  The full unit suite adds `pytest-homeassistant-custom-component`. `ci/setup-ci-deps.sh`
  installs everything into `.venv`. Run `source .venv/bin/activate` first.
- `tests/conftest.py` runs each pure module under its real dotted name
  (`custom_components.home_keeper.<mod>`) with stub parent packages, and registers
  `hk.<mod>` and `hk_<mod>` as aliases. Keep the real name: mutmut matches a mutant key to
  `__module__`. Keep `hk` a distinct package, not an alias of the real one, or
  `from . import x` in a module loaded as `hk.<mod>` pulls in the real HA siblings.
- After a local Docker run, restore `tests/integration/ha_config/.storage/home_keeper` and
  `core.config_entries`. Never commit state that a run changed.

## Dependencies

- **A missing test dependency fails the run. It never skips.** Import every package in
  `requirements-test.txt` plainly, so a broken environment does not look like a choice.
  Use `pytest.importorskip` only for `homeassistant` and `voluptuous`.
- **A dependency that changes what other tests skip stays out of
  `requirements-test.txt`.** `voluptuous-openapi` pulls in `voluptuous`, which decides
  whether `test_config_flow.py` runs. `ci/install-schema-deps.sh` installs it and
  `jsonschema` in the one job that needs them, under Home Assistant's constraints.
- **The published-schema gate runs only where `HK_SCHEMA_GATE` is set**, which is the
  mypy job in `lint.yml`. It needs a current Home Assistant, not only an importable one.
  The job checks the HA version and greps the output to prove that the tests ran. Run it
  locally with `HK_SCHEMA_GATE=1 pytest tests/unit/test_generate_schema.py` after
  `pip install homeassistant voluptuous-openapi jsonschema` on a Python at HA's floor.
- Give an opt-in gate a sibling in the lane that every PR runs
  (`test_no_exported_value_is_null` for the schema gate).
- Never subtract the `EXCLUDED_*` keys from the published schema. They name what export
  omits, and import still accepts some of them. Keep `additionalProperties` open.

## Property-based tests

- Write a property test when the claim is about a whole domain ("the fast path always
  agrees with the slow one"). Write an ordinary test for a single case.
- They live in `tests/unit/test_*_properties.py`, share
  `tests/unit/property_strategies.py`, and carry the `property` marker.
- Build inputs with `models.build_task` or `assets.build_asset`. Never hand-roll a dict.
- A property holds for every input it can draw, or its generator is scoped until it
  does. Pin a real defect with `xfail(strict=True)` and an `@example` reproducer.
  Never widen an assertion to swallow a failure.
- `HK_HYPOTHESIS_PROFILE` picks `dev` (default), `ci` (derandomized) or `mutmut` (no
  shrink). The runner scripts export it. Never cache `.hypothesis/` in CI.
- The mutation gate scores property tests. Each one names the mutant it kills; prove it
  by mutating the line and watching the test go red.

## Writing a test that can fail

- **Test the shipped function, never a copy.** To unit-test a module that imports HA,
  stub the HA symbols, register fakes for its HA siblings, load the real file as
  `hk.<mod>`, and patch its bindings. `test_calendar.py` and `test_device_heal.py` show it.
- **Check that a new test can fail.** Mutate the line and watch it go red. A fake that can
  only produce the passing case reports coverage that the code does not have.
- A known-broken contract gets `xfail(strict=True)`, never a weaker assertion.
- **A framework contract needs an integration test.** Device registry, entity registry
  and device automation behavior is invisible to a unit test that mocks the framework.
- **Cross-version behavior needs an upgrade test.** `tests/upgrade` boots a frozen
  pre-split HA, seeds it, then boots the current HA on the same config dir. Never bump
  the frozen pin: it defines what users upgrade from. A PR that changes the split repair
  (`devices.py`, `store.py`) runs the upgrade suite before it merges.
- **A panel assertion does not cover a native entity.** The panel and the `todo` and
  `calendar` entities are separate views of the store. Assert on the surface that must
  change.
- **Assert disappearance too.** Test a transition from both ends: present before, gone
  after (`expectAbsentFromActiveSurfaces`, `expectOnTodoList` in `tests/e2e/tests/helpers.ts`).
- **A second delivery path needs a test that removes the first one.**
  `tests/e2e/tests/card-registration.spec.ts` strips the card import from the shell and
  asserts that the card still renders. It blocks service workers and asserts that the
  unstripped shell had the import, so it cannot pass for the wrong reason.
- Never commit a real `.storage` dump. Build fixtures from synthetic data, and use each
  fixture in a test.

## Browser tests

- Auth and onboarding are in `tests/e2e/global-setup.ts`. It also writes
  `PRESET_NUDGE_SEEN` to `home_keeper_preset_nudge`, so no spec meets the preset dialog.
  A step that shows the suggestions clears the key and writes it back after
  (`tests/e2e/user-data.ts`).
- **A spec owns what it creates.** The container's task store is the committed seed
  fixture. Delete created ids in `afterEach` (`createTask`, `deleteTask` in `helpers.ts`)
  and give fixtures stable names, never a `Date.now()` suffix.
- **Seeded ids are real `uuid4`s**, reached through `tests/e2e/fixture-ids.ts`. Never
  paste a bare uuid into a spec. Renaming a fixture id also moves its blobs under
  `ha_config/home_keeper/documents/` and the `.gitignore` entry that names them.
- **Assert an `ha-select` pick by its effect**, and wrap the open, the click and the check
  in 1 `expect(...).toPass()` (`pickUntil` in `walkthrough.capture.ts`).
- **Verify a spec that touches browser plumbing with the CI browser.** CI runs Playwright's
  headless shell, and `CHROMIUM_EXEC` is an older full Chromium. Run it again with
  `CHROMIUM_EXEC` unset: `cd tests/e2e && CI=true npx playwright test <spec>`.
- A spec that rewrites a document with `route.fulfill` passes
  `--disable-features=LocalNetworkAccessChecks` in its own `test.use({ launchOptions })`,
  never in `playwright.config.ts`. `launchOptions` replaces the config's copy, so the spec
  sets `CHROMIUM_EXEC` itself.
- **Bring the container down before you clean the fixture.** Reset with
  `git clean -fdX tests/integration/ha_config/` before each capture, and check
  `git status tests/integration/` after. The clean deletes the bind mountpoint, and a
  running container then serves a 404 for the panel bundle.

### Three widths

- The suite has 3 Playwright projects: `desktop` (1280x720), `tablet` (820x1180) and
  `phone` (390x844). `tests/e2e/viewports.ts` is the only place that writes a width.
- A spec opts in with a tag that starts with `@`: `@responsive` (all 3), `@narrow` (phone
  and tablet), `@phone` or `@tablet`. Untagged runs on desktop only. The `@` matters,
  because Playwright also matches `grep` against the project name.
- A test that crosses a breakpoint stays untagged and resizes itself.
- Never name a tab bar in a spec. Use `gotoTab()`, `expectTabActive()` and
  `openSettingsSection()`, because CSS picks which bar shows.
- A viewport project sets the viewport only, never a device descriptor.
- A capture config pins the desktop project with `captureConfig()` from
  `tests/e2e/capture-config.ts`. `--list` must show 1 project.
- Measure layout by relations (A is above B), never by coordinates. Assert that a list is
  not empty before you loop over it.

## Translations

`strings.json` and `frontend/src/locales/en.json` are the sources.
`tests/unit/test_translations_parity.py` and `frontend/test/i18n.test.js` enforce for
each locale:

- the same keys as English, and the same `{token}` placeholders per key;
- no value identical to English, except the global `INTENTIONALLY_IDENTICAL` list and a
  per-locale `COGNATE_IDENTICAL` list of reviewed cognates;
- for the frontend, that every `t()` and `tn()` key exists, and that every plural base
  has each CLDR category that the locale uses.

`unused-keys-baseline.json` can only shrink. `python3 ci/i18n-coverage.py` prints coverage
for information only.
