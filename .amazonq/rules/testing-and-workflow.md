# Home Keeper — testing & workflow conventions

## Git & PR workflow
- **All English text follows ASD-STE100.** See `writing-style.md` in this directory
  for the rules and the glossary. It covers docs, strings, comments, and PR text.
- Never push directly to `main`. Work on a feature branch and open a PR; squash
  merge.
- Update `CHANGELOG.md` for every user-facing change before a release.
- **User-facing text is drafted by a Sonnet 4.5 subagent** (`model: sonnet`), not written
  inline: `CHANGELOG.md` bullets, `README.md`, the canonical `docs/*.md`, `strings.json`,
  `services.yaml` descriptions, the frontend locale. Hand it the diff, the surrounding
  section for voice, and the house rules it must satisfy; review and edit the draft before
  committing. Commit messages, PR bodies and code comments stay inline — they are not
  user-facing.
- **Keep every CHANGELOG bullet to three sentences at most.** A bold lead naming the
  change, then what a user notices, then a caveat or `(Fixes #N)` if one is needed.
  Cut the worked example, the before-and-after story, the list of every surface the
  value now appears on, and the API/attribute inventory. Detail belongs in `README.md`,
  `docs/`, or the PR; the changelog says what changed and stops. One bullet per change,
  never a second paragraph. Three sentences is the budget for the **whole bullet**,
  counting the bold lead as the first, not three per paragraph.
- **Credit an outside contributor in the bullet for their change.** End the bullet
  with `(Thanks @user!)`, after `(Fixes #N)` if the bullet has one. The credit does
  not count against the three-sentence budget. An outside contributor is anyone
  without write access to the repository when the PR opens. Their change gets a
  credit in the same PR that writes the bullet. If a maintainer and a contributor
  share the work, the contributor gets the credit. `summarize()` in
  `ci/release-issues.py` quotes only the bold lead. The credit stays in the
  CHANGELOG. It does not reach the issue comment, and it does not notify the
  contributor on each release.
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
- **Plans and PRs must list one-way doors.** A one-way door is a design choice
  that is hard to reverse once users depend on it: the name, shape, or format of
  a field in a service call, an event payload, storage, an entity attribute, or
  any other external contract. Plans call them out before implementation; PR
  bodies include a **One-way doors** section listing every committed surface —
  field name, format, where it appears, and what users or automations will rely
  on. Internal-only shapes (frontend form data, private helpers) are two-way
  doors and don't need listing.
- **User-facing prose is linted for AI-tell phrasing.** `lint.yml`'s `vale` job runs
  the [vale-ai-tells](https://github.com/tbhb/vale-ai-tells) style (pinned version in
  `.vale.ini`) over `README.md`, `CHANGELOG.md`, the canonical `docs/*.md` (excludes
  `*_PLAN.md`/research scratch docs), `website/docs/intro.md`, `strings.json`,
  `services.yaml`, and `locales/en.json` (not the other locales or `translations/`,
  since the rules are English-phrase regexes). It's diff-scoped (`filter_mode: added`),
  so only new/changed lines can fail CI. The existing corpus is cleaned up
  separately. Run locally with `vale sync && vale <paths>`, but treat a clean local run
  as weak evidence: `lint.yml`'s action pins its own binary and has reported hits a local
  Vale found nowhere in the file. To be sure, match the rule's `tokens` regexes from
  `styles/ai-tells/<Rule>.yml` against the text yourself, scoped per **block** (a list
  item plus its continuation lines is one string, and `[^,]+` spans sentence boundaries).
  Keep at most one comma after a modal or pronoun in a bullet. Disable an accepted false
  positive per-file in `.vale.ini` (`ai-tells.RuleName = NO`) or inline with
  `<!-- vale ai-tells.RuleName = NO -->` / `... = YES -->`. For example,
  `services.yaml` disables `ColonUsage`, which otherwise fires on every unquoted
  YAML `key: Value` line. Diff-scoping misses pre-existing hits on lines a
  full-file prose rewrite happens to move, so run `vale <file>` yourself first for
  that case. The pinned `ai-tells.zip` version has no bump automation
  (Dependabot/Renovate don't track raw release URLs), so bump it by hand
  periodically.

## Tests (run locally before pushing — never use CI as the test runner)
- The recurrence engine and model are the correctness core: keep them HA-free and
  thoroughly unit-tested. `pytest tests/unit` must run without the HA harness.
  `tests/conftest.py` *executes* the pure modules under their real dotted name
  (`custom_components.home_keeper.<mod>`, with stub parent packages so the
  HA-importing `__init__.py` never runs) and registers `hk.<mod>` / `hk_<mod>` as
  aliases. **Two invariants there:** mutmut matches a mutant's path-derived key
  against the function's `__module__`, so executing them as `hk.<mod>` would make
  every mutant look untested; and `hk` must stay a *distinct* package object, not
  an alias of `custom_components.home_keeper`, because `from . import x` resolves
  through the parent's `__name__` — aliasing them makes the modules
  `test_coordinator_purge.py` / `test_calendar.py` load as `hk.coordinator` pull
  in the real HA-importing siblings instead of their fakes.
- Layers: `tests/unit` (pytest, pure logic), `tests/frontend` +
  `frontend/test` (vitest), `tests/integration` (Docker HA), `tests/e2e`
  (Playwright), `tests/upgrade` (two-phase HA version upgrade). Run e2e/integration
  with `bash ci/e2e-up.sh` / `ci/test-python-integration.sh`; stage the upgrade
  suite's fixtures with `bash ci/fetch-glues.sh` first.
- **`tests/unit/test_api_surface.py` is the drift gate for the integrator-facing
  surface.** It parses the component's source and compares it to `api_surface.py`, so
  a service, event, websocket command, device trigger, entity platform or HTTP view
  added in one place and forgotten in the others fails there rather than shipping.
  Adding a surface means adding its spec. Its `services.yaml` check and the
  generator's tests need `PyYAML`, so the bare-`pytest` loop is now
  `pip install pytest PyYAML`; without it those few tests skip and the rest still run.
- **A panel assertion is not coverage for a native entity.** The panel and the
  `todo`/`calendar` entities are separate projections of the same store, so the panel
  being right proves nothing about them. #221 shipped with a passing e2e test that
  created a one-off, completed it, and asserted the panel filed it under Completed —
  while the to-do entity went on offering it as `needs_action` forever. A state change
  that should be visible on a native surface needs an assertion **on that surface**.
- **Assert disappearance, not just appearance.** Presence gets asserted by accident;
  absence has to be asked for, and the interesting bugs are absences that didn't
  happen. Test a state transition from both ends — present before, gone after — via
  `expectAbsentFromActiveSurfaces` / `expectOnTodoList` in `tests/e2e/tests/helpers.ts`.
  Asserting only the post-state also passes for a task that was never listed at all.
- **A screenshot is documentation, not verification.** The capture harness wrote
  `docs/images/4-usage-todo-and-calendar.png` showing #221 in plain sight — stale
  to-do items beside panel columns marking those same tasks Completed — for months.
  Capturing a surface is not covering it; if a screenshot shows a surface, something
  should be asserting on it too.
- **An e2e spec owns what it creates.** The container's task store *is* the committed
  seed fixture (`tests/integration/ha_config/.storage/home_keeper`), so anything a
  spec leaves behind is a permanent addition to it. Register created ids and delete
  them in `afterEach` (`createTask`/`deleteTask` in `helpers.ts`), and give fixtures
  **stable** names — a `Date.now()` suffix makes each leak look like a new record
  instead of the same spec failing to clean up, which is how eight of them reached git.
- **Seeded fixture ids are real `uuid4`s, and specs reach them through
  `tests/e2e/fixture-ids.ts`.** Readable ids (`task_fridge_filter`) were easier to
  grep for, but they were a quarter the length of anything a real install holds —
  `models.build_task` and `assets.build_asset` mint `str(uuid.uuid4())` and take no
  caller-supplied id. That gap flattered every screenshot and every layout
  assertion: the panel's id row wraps at a width no short fixture ever exercised.
  Add a fixture ⇒ give it a uuid and a name in `fixture-ids.ts`; never paste a bare
  uuid into a spec. The blobs under `ha_config/home_keeper/documents/` are named for
  the asset and document ids, so renaming one means moving those too, and the
  `.gitignore` allowlist that names that directory.
  `tests/unit/test_integration_fixture_clean.py` resolves `${TASK.x}` references
  through the module, so a mistyped constant fails there rather than in the soft
  walkthrough gate.
- **Anything that rests on an HA framework contract** — device registry, entity
  registry, device automation — **needs an integration-level assertion.** Unit tests
  mock the framework away and cannot see the contract change. #183 (devices split per
  config entry in HA 2026.8) shipped because the only device-attachment coverage was
  for the *self-owned* case, never the foreign-device one.
- **Cross-version behaviour needs an upgrade test, not just a fresh-boot test.**
  `tests/upgrade` boots a frozen pre-split HA, seeds every scenario into one config
  dir, then boots the current HA against that same dir so HA runs its own migration
  in between — two cold starts for the whole suite. The pre-split tag is a frozen
  pin: it defines "the world users upgrade from", so bumping it changes the meaning
  of the test.
- **A test must exercise the shipped function, never a copy of it.** Re-implementing
  the logic under test inside the test file (to dodge an import) proves nothing: the
  production code keeps zero coverage and every later edit to it stays green. An
  HA-importing module is still unit-testable — `test_calendar.py`,
  `test_coordinator_purge.py` and `test_device_heal.py` stub the HA symbols the module
  imports, register fakes for its HA-aware siblings, load the **real** file under
  `hk.<mod>`, then inject fakes by patching the loaded module's bindings. Follow that
  pattern instead of duplicating the source.
- **Check that a new test can fail.** Mutate the line it covers and confirm it goes
  red before relying on it. A test whose fake can only produce the passing case (e.g.
  a mock registry that returns one candidate, "verifying" a preference between
  several) is worse than no test: it reports coverage the code does not have.
- **Never commit a real `.storage` dump as a fixture.** Production snapshots carry
  serial numbers, MAC addresses, document links and other household data, and they
  live forever in git history. Build fixtures from synthetic data, and wire every
  fixture into a test — an unreferenced fixture is only a leak with no upside.
- **Known-broken contracts get `xfail(strict=True)`, never a weakened assertion.**
  The test then documents the breakage without going red, and becomes a hard failure
  the moment a fix lands, forcing the marker off.
- HA versions: PRs run `stable` (`HA_TAG` in `tests/integration/docker-compose.yml`);
  `ha-beta.yml` runs `beta` nightly as an early warning and gates nothing.
- After running the Docker HA container locally, restore the seeded fixtures
  (`tests/integration/ha_config/.storage/{home_keeper,core.config_entries}`);
  don't commit runtime-mutated state.
- **A second delivery path needs a test that deletes the first one.** #228 was
  invisible to a suite where every dashboard test loaded a freshly-rendered app shell
  that happened to carry the card's import. Don't wait for a stale cache — reproduce
  what one *is*: `tests/e2e/tests/card-registration.spec.ts` intercepts the dashboard
  navigation with `page.route`, strips the card's `import(...)` out of the HTML, and
  asserts the card still renders. Two things make it honest. It sets
  `test.use({ serviceWorkers: 'block' })`, because a service worker answers
  navigations *before* `page.route` sees them, and HA registers one on first load — so
  without it the reload that follows is served the original shell and the test passes
  for the wrong reason. And it asserts the *unstripped* HTML did contain the import, so
  the test cannot quietly go vacuous if HA changes how it delivers extra modules. It
  deliberately does not use `openCardDashboard`: that helper reloads up to 3x to absorb
  cold-frontend flake, which here would only re-serve the stripped shell while turning
  a precise failure into an opaque timeout.
- **Verify a browser-sensitive e2e spec with the browser CI actually uses.** `e2e.yml` runs
  `npx playwright install chromium` and no `CHROMIUM_EXEC`, so CI drives Playwright's
  **headless shell**; the `CHROMIUM_EXEC` override documented in AGENTS.md for the Claude Code
  remote environment points at a *different, older* full Chromium. `card-registration.spec.ts`
  passed locally and failed on CI three times for exactly that reason. Re-run a spec with
  `CHROMIUM_EXEC` unset (`CI=true npx playwright test <spec>`) before trusting it.
- **A spec that rewrites a document needs the Local Network Access flag.** Chrome classifies a
  response synthesized by `route.fulfill` as coming from a public address space, then blocks the
  page's own `ws://localhost:8123/api/websocket` as a local-network request
  (`net::ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS`). The frontend never connects, so nothing
  websocket-delivered — Lovelace resources included — ever loads, and the failure looks like the
  feature under test is broken. Pass `--disable-features=LocalNetworkAccessChecks` in that spec's
  own `test.use({ launchOptions })`, not in `playwright.config.ts`: only a spec that rewrites a
  document needs it, and every other spec should keep the check so a future test of network or
  CORS behaviour still gets it. Note `launchOptions` *replaces* the config's copy rather than
  merging, so the spec has to re-plumb `CHROMIUM_EXEC` itself — see
  `tests/e2e/tests/card-registration.spec.ts`.
- **Give an e2e assertion that depends on browser plumbing a failure message that names what it
  saw.** The above took a CI round-trip per guess until the spec captured console errors and
  whether the bundle was requested at all; "the bundle was never requested" is the line that
  ended it. A bare `waitFor` timeout says only that something, somewhere, did not happen.

### The e2e suite runs at three widths

- **The panel's layout is responsive, so the suite has three Playwright projects** —
  `desktop` (1280x720), `tablet` (820x1180) and `phone` (390x844) — sharing one set of
  test bodies. `tests/e2e/viewports.ts` is the only place a width is written down.
  Tablet is not decoration: at 820px the drawer is already a sheet and the master pane
  has already stepped aside while the top tabs are still up, which is where the 1150 /
  1000 / 700 thresholds have to agree with each other.
- **A spec opts into the extra widths with a tag**, and every tag starts with `@`:
  `@responsive` (all three), `@narrow` (phone + tablet), `@phone` / `@tablet` (one
  band). Untagged is desktop-only, which is the default and covers the Lovelace specs —
  a dashboard card learns nothing from a second viewport. The `@` is load-bearing:
  Playwright matches `grep` against the project name as well as the tags, so a project
  named `tablet` with a bare `/tablet/` would match every test in it.
- **A test that crosses a breakpoint within one page stays untagged and resizes
  itself.** A project viewport is fixed for the life of the test, so it cannot express
  a transition — and `_syncDrawerModality()`'s `matchMedia` listener, the only viewport
  read in the panel, is reachable no other way. The two mechanisms coexist on purpose;
  neither replaces the other.
- **Never let a spec name a tab bar directly.** Both bars are in the DOM at every width
  (`#tab-*` and `#mtab-*` differ only because two elements cannot share an id) and CSS
  picks. Go through `gotoTab()`, which clicks whichever is *visible* — that is how a
  spec asks for "the tab bar" while keeping the invariant that nothing but CSS reads
  the viewport. Use `expectTabActive()` for "we got back to the list": the phone bar is
  visible on every view, so asserting its presence there is vacuous. Reach a Settings
  section with `openSettingsSection()`, because a narrow screen renders an index and
  opens one section at a time, so "every section is on screen" is a desktop-only claim.
- **A viewport project must not use a device descriptor.** `devices['Pixel 5']` also
  sets `isMobile`, `hasTouch` and a `deviceScaleFactor`, none of which
  `page.setViewportSize()` changes — so the project-driven runs and the self-resizing
  tests would disagree about what a phone is. Override the viewport only.
- **A capture config must pin the desktop project.** Each `*.config.ts` spreads
  `playwright.config.ts`, which now carries three projects, so an unpinned capture
  would shoot every committed PNG three times over at three widths and keep whichever
  finished last. `captureConfig()` in `tests/e2e/capture-config.ts` applies the pin;
  use it rather than spreading the base config by hand. Check with
  `npx playwright test --config=screenshots.config.ts --list` — it must list one
  project.
- **Measure layout by relationships, not coordinates.** `responsive-layout.spec.ts`
  uses `getComputedStyle` for keywords (`position`, `flex-wrap`, `overflow-x`) and
  bounding boxes for relations (A is above B; this box is inside that one). No absolute
  coordinate and no exact size, so a spacing tweak does not turn the suite red. Assert
  a list is non-empty before looping over it, or a renamed class makes the loop pass by
  iterating nothing. Prove an anchored element is anchored by *scrolling and re-reading
  its box*, not by reading `position: fixed` once — the static read still passes under
  a `container-type` regression that turns every fixed descendant into a
  page-positioned one.
- **The screenshot capture mutates the seeded fixture, and only a local re-run
  notices.** It dismisses the first-run banner into HA's per-user frontend store and
  leaves uploaded documents behind; those runtime files are gitignored, so CI starts
  clean every time and never sees it, while a second local run fails on the banner it
  already dismissed. Reset with `git clean -fdX tests/integration/ha_config/` (plus
  `git clean -fd` and `git checkout --`) before each capture, and check
  `git status tests/integration/` afterwards.
- **Bring the container *down* before that clean, not after.** `ha_config/custom_components/`
  is a gitignored directory Docker creates to hold the integration bind mount, so the
  `-fdX` above deletes it — and deleting a mountpoint under a running container
  detaches the mount from inside. HA keeps answering on 8123 while
  `/home_keeper_panel/home-keeper-panel.js` starts 404ing, so the panel never upgrades
  and *every* browser test fails identically at `openPanel`'s 45s attach timeout. It
  reads exactly like a bundle that failed to build. `docker compose down` first (or
  restart afterwards) and the mountpoint is recreated.
- **The walkthrough records one context per width.** `recordVideo.size` is fixed when a
  context is created, so resizing mid-recording leaves the phone viewport in a corner
  of a desktop-sized frame — which is why an earlier attempt concluded the phone layout
  could not be recorded. The `TOURS` table in `walkthrough.capture.ts` gives each width
  its own context, its own `test()` and its own output basename. A phone tour is
  different *beats*, not the desktop script at 390px.

## Mutation testing (a PR gate)
Coverage proves a line *ran*; mutation testing proves a test would have *failed*
had that line been wrong. `mutation.yml` runs on every PR and scores only the code
the branch touched.

- **Runners:** `ci/test-mutation-python.sh` (mutmut, against `tests/unit`) and
  `ci/test-mutation-frontend.sh` (Stryker, against vitest). Both take `--changed`
  (default) or `--all`.
- **The surface is an allowlist, in one place per language:** `only_mutate` in
  `[tool.mutmut]` (pyproject.toml) and `mutate` in `stryker.conf.json`. It holds
  only what the fast tiers cover — the pure core, and the focused frontend modules
  (`utils`, `forms`, `card-filter`, `documents`, `markdown`, `i18n`, `limits`).
  Out: everything importing Home Assistant (Docker-tier only), `const.py` /
  `companions_catalog.py` (data), `backend_i18n.py` (no unit entry point),
  `testing.py`, and `panel.ts` + its `panel-*.ts` region modules / `card.ts` / `api.ts` (indirectly covered only).
- **Diff scoping:** `ci/mutation_scope.py` turns the diff into mutmut mutant-name
  filters (changed line → enclosing function, decorators included, via `ast`) and
  Stryker `--mutate` line ranges. Scoping to whole files would fail a PR for
  pre-existing debt.
- **The gate is 80%**, in `[tool.mutation-gate] break` and mirrored in
  `thresholds.break`; both runners fail on a mismatch so they cannot drift.
  `--all` may sit below it while the surface is being brought up — the PR gate is
  what must stay green.
- **Surviving mutants are a test gap, not a formality.** Kill them with a real
  assertion. For a genuinely *equivalent* mutant, annotate at the source
  (`# pragma: no mutate`, `// Stryker disable next-line <mutator>`) **with a
  one-line reason**. Never blanket-disable a file; never lower the threshold.
- **Tests that read source off disk must be `*-parity.test.js`.** Under Stryker
  they would read *mutated* text and go red for mutants they never exercised —
  `forms.ts` is full of `t('…')` call sites, so this inflates the score badly.
  `vitest.stryker.config.js` excludes that suffix.
- Label a PR `skip-mutation` to bypass both jobs (revert/infra PRs).

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
- **`lint.yml`'s `changelog-release-gap` job guards the "fold into the current top
  beta" rule above.** `release.yml` keys off `manifest.json`'s version and skips
  tagging silently when that version is already tagged — so a PR that edits the top
  `## [X.Y.ZbN]` CHANGELOG section without bumping the version, after that version
  has already shipped, merges clean and then never actually ships (#236 did exactly
  this: it landed ~50 minutes after `v0.16.0b7` was tagged, reusing the b7 heading,
  and sat unreleased on `main` until #237 caught it). `ci/check-changelog-release-gap.py`
  compares the top section between the PR's merge-base and `HEAD`: unchanged content,
  or a version bump, or a still-unreleased top section, all pass; changed content
  under an already-tagged version fails. Pure logic lives in `check()`, tested in
  `tests/unit/test_check_changelog_release_gap.py`.
- **Always add the `preview-release` label to a new-feature PR** once it's open, so
  `preview-release.yml` publishes an installable ephemeral pre-release
  (`X.Y.Z.dev<pr>`) from the PR head for pre-merge HACS testing (auto-deleted on
  close; see RELEASE.md). Bug-fix/developer-only PRs don't.
- **Shipping closes an issue, not merging.** Closing-on-merge is off for this repo, so
  a PR's `Fixes #N` links the issue (filling its **Development** panel) without closing
  it, and it stays open until users can install the fix. `release.yml`'s
  `notify-issues` job reads the shipped version's CHANGELOG section, comments on every
  issue it references, and — on a stable only — closes it as completed. A beta comments
  and leaves the issue open.
- **The `(Fixes #N)` refs in a CHANGELOG section are that release's issue list.**
  Leave an issue out and it is never notified and never closes. Only closing keywords
  are read; `(Related to #N)` and bare `(#N)` are ignored on purpose, since `(#N)` is
  also the squash-merge PR number. `ci/release-issues.py` owns the parsing (and the
  release-notes extraction) and is unit-tested in
  `tests/unit/test_release_issues.py` — change the format there, not in the workflow.
- The built `dist/home-keeper-panel.js` is gitignored; CI builds it.

## Typing (strict-typing gate — Platinum)
- The integration is **fully typed** and ships `custom_components/home_keeper/py.typed`.
  `lint.yml` runs `mypy custom_components/home_keeper` with Home Assistant installed
  (so HA's own types resolve); config is `[tool.mypy]` in `pyproject.toml`. Keep it
  error-free — a new untyped def or a real type mismatch fails CI.
- Run it locally before pushing: `pip install mypy homeassistant && mypy
  custom_components/home_keeper`. The pure modules (`models.py`, `recurrence.py`,
  `events.py`) stay HA-free and type-check standalone.
- **Run it on a Python at or above Home Assistant's own floor** (>=3.14.2 since HA
  2026.3). On an older interpreter `pip install homeassistant` does not fail — it
  backtracks to the last HA that supported it, so mypy checks a months-old API and
  passes. Both mypy jobs therefore run `python ci/check-ha-version.py`, which
  compares the installed version against PyPI and fails on a stale resolve (#199).
- **`[tool.mypy] python_version` tracks HA's floor, not the integration's.** HA's
  source uses syntax from its own minimum Python (2026.8 uses PEP 758
  parenthesis-free `except A, B:`); targeting anything older makes mypy bail on a
  syntax error inside HA, reporting nothing about our code.
- **Read the HA version from `homeassistant.const.__version__`.**
  `homeassistant.__version__` does not exist — `homeassistant/__init__.py` is a
  one-line docstring — so a step reading it dies with an `AttributeError`.

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
- **Never comment on a GitHub issue.** Issues are the user↔maintainer channel;
  an agent posting there answers for the maintainer to someone who didn't ask.
  Analysis, findings and status go in the PR carrying the work. A PR that fixes
  an issue links it (`Fixes #N`) and the release shipping it closes it — that's the
  only signal the issue needs. PR comments are unaffected (the `/q review` above and
  replies to review threads are still required).
  - The ban is on *you* posting, not on repo automation working from a fixed
    template: `release.yml`'s `notify-issues` job and `ha-beta.yml`'s regression
    reporter both comment on issues by design.
