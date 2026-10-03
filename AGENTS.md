---
title: Agent guide
summary: The hard gates every agent must follow in Home Keeper, and an index of the rules and design docs.
---

# AGENTS.md — Home Keeper

Home Keeper is a Home Assistant integration (domain `home_keeper`) for home maintenance.
This page lists the hard gates. The detail is in the rules files below. Read the file for
your topic before you change code or push.

## Where the rules are

| Topic | File |
|---|---|
| Writing style (STE100) and glossary | [writing-style.md](.amazonq/rules/writing-style.md) |
| Branches, reviews, screenshots, walkthrough, user docs | [pr-workflow.md](.amazonq/rules/pr-workflow.md) |
| CHANGELOG, betas, releases, issues | [changelog-and-release.md](.amazonq/rules/changelog-and-release.md) |
| Test tiers, test rules, e2e, translations | [testing.md](.amazonq/rules/testing.md) |
| CI, mutation gate, typing, HA versions, vale, presets | [ci-and-ha-versions.md](.amazonq/rules/ci-and-ha-versions.md) |
| Admin and usage, privilege, pure core, entities, options, i18n | [architecture.md](.amazonq/rules/architecture.md) |
| Services, websocket commands, events, API surface | [services-and-events.md](.amazonq/rules/services-and-events.md) |
| Tasks, sensors, completions, appliances, syncs, import | [data-and-storage.md](.amazonq/rules/data-and-storage.md) |
| Panel and card | [frontend.md](.amazonq/rules/frontend.md) |
| Dev docs, design docs, `ci/docs.py` | [dev-docs.md](.amazonq/rules/dev-docs.md) |
| How each subsystem works | [docs/design/](docs/design/architecture.md#design-doc-index) |
| Release steps | [RELEASE.md](RELEASE.md) |
| Ideas that are not built | [IDEAS.md](IDEAS.md) |

## Project in brief

- Backend: `custom_components/home_keeper/`. The pure core imports no Home Assistant code.
- Storage: 1 JSON document, `.storage/home_keeper`.
- Frontend: TypeScript and Rollup in `custom_components/home_keeper/frontend/`. CI builds
  `dist/`, which is gitignored.
- Administration is in the admin-only sidebar panel. Usage is through native `todo`,
  `calendar` and device-page entities. Do not mix the 2.
- Docs site: `website/` (Docusaurus). It renders `docs/guide/` and copies some `docs/*.md`.
  Edit the sources, never the generated trees.

## Hard gates

### Writing

- **All English text follows ASD-STE100.** Docs, strings, comments, PR text and chat
  replies. Read [writing-style.md](.amazonq/rules/writing-style.md) before you write prose.

### Branches and merges

- **Never push to `main`.** Use a feature branch and a PR.
- **Every check green, plus approval, before a merge.** A failure you did not cause is
  still yours to clear. Never merge on a red or running check.
- **Read what a soft gate produced.** A `continue-on-error` step is always green.
- **Always squash merge.**
- **Run the tests locally before you push.** Never use CI as the test runner.
  Pure unit tests: `pip install pytest PyYAML Babel hypothesis jsonschema`, then
  `pytest tests/unit`. Run `mypy` too
  ([ci-and-ha-versions.md](.amazonq/rules/ci-and-ha-versions.md)).
- **Ask Amazon Q for a review after each push.** Post `/q review {request}` and ask for
  critical feedback on named topics. Triage what comes back.
- **Never comment on a GitHub issue.** Findings go in the PR. Link the issue with
  `Fixes #N`; the release closes it. The 1 exception is the `preview-comment` skill, after
  the maintainer approves the exact text.

### Plans and PR bodies

- **A plan lives in the PR body.** It starts with the CHANGELOG bullet it will ship.
- **List one-way doors.** The plan and the PR body name every external contract the
  change commits to: service fields, event payloads, storage, attributes, user-data keys.
- **Add a Security section.** The plan and the PR body say if each service, websocket
  command, HTTP method and event that the change adds or changes is admin-only or open,
  and why ([architecture.md](.amazonq/rules/architecture.md#how-to-decide)).
- **A subjective UI choice starts with an artifact.** Mock up the options at desktop and
  phone width, then agree on 1.

### UI evidence

- **A PR that touches `frontend/src/` embeds screenshots: desktop and phone.** Every
  changed surface needs both. Capture with the Playwright harness, read each PNG, commit
  under `docs/images/`, and embed with a SHA-pinned HTML `<img>`. The phone step goes in
  the `setViewportSize(PHONE)` block with a `-mobile-` name.
- **A new UI feature extends the walkthrough tour** (`tests/e2e/walkthrough.capture.ts`)
  in the same PR. CI records it and posts it as a PR comment. Never commit a video.
  Capture is a hard gate.
- **A new major feature is documented in `docs/guide/`** in the same change, with
  screenshots. `README.md` stays short.

### Mutation gate

- **`mutation.yml` fails a PR below an 80% mutation score on the code it changed.** Kill
  a surviving mutant with a real assertion, or mark a truly equivalent one with a reason.
  Never lower the threshold. The allowlist is `only_mutate` in `pyproject.toml` and
  `mutate` in `stryker.conf.json`.

### CHANGELOG and versions

- **Each user-facing change gets 1 bullet of at most 3 sentences**, the lead included.
- **The bold lead is a 2 to 5 word noun phrase**, with no articles. An `### Added` lead
  links its guide page by absolute URL: `**[Text](url).**`.
- **The bullet says what a user gets.** No mechanism, no inventory.
- **`(Fixes #N)` goes in the bullet's first paragraph.** It is what notifies and closes
  the issue. A bare `(#N)` does nothing.
- **Credit an outside contributor** with `(Thanks @user!)`.
- **A stable section covers everything since the last stable**, with a `### Fixed` list
  of every `(Fixes #N)` since then.
- **Betas use the next release number.** After `X.Y.0` ships, `main` goes to
  `X.(Y+1).0b1`. Never cut `X.Y.0bN` after `X.Y.0`.
- **A new feature cuts a beta in the same PR.** Bump `manifest.json` and `PANEL_VERSION`
  to the next `bN`, or fold into the top beta if it is still unreleased.
- **Label a new-feature PR `preview-release`** as soon as it is open.

### Code contracts

- **Every data action is a `home_keeper.*` service.** A websocket command never
  replaces it ([services-and-events.md](.amazonq/rules/services-and-events.md)).
- **Gate an admin-only operation in the command and in the service**
  ([architecture.md](.amazonq/rules/architecture.md#privilege-model)).
- **Every state change fires a `home_keeper_<noun>_<verb>` event** from the store.
- **Every integrator surface is declared in `api_surface.py`.**
- **A new persisted field round-trips through import and export**, or is excluded with a
  reason ([data-and-storage.md](.amazonq/rules/data-and-storage.md#import-and-export)).
- **An options flow returns `options.merge_flow_input(...)`**, never `user_input`.
- Escape all user content with `escapeHTML`. Navigate the panel only by URL.
- All datetimes are timezone-aware. Recurrence code takes an explicit `now`.

### Dev docs

- **Before you change code, run `python3 ci/docs.py for <path>`.** It prints the design
  docs and goals for that file. `list`, `read`, `outline` and `search` find the rest.
- **On design-doc drift, check the goals.** If the change works against a goal, stop and
  ask the user. Else make the doc describe the code as it is now, with no history, and
  run `python3 ci/docs.py stamp <id>`.
- **A change to Goals or Non-goals needs a "Goal changes" PR section** that the
  maintainer agreed to.
- **Each new file under `custom_components/home_keeper/` goes in a design doc's
  `implements`.**
- **Caps**: design 150 lines, reference 300, rules 200, process 200, backlog 300, skill
  200; 100 characters a line; `CLAUDE.md` plus this file 250. At most 2 length exceptions.
- **Unbuilt work goes in `IDEAS.md`.** There are no plan files.
- `docs-audit` in `lint.yml` runs `python3 ci/docs.py check --base origin/main`. Details:
  [dev-docs.md](.amazonq/rules/dev-docs.md).

### Keep the rules current

- **A new or changed convention updates `.amazonq/rules/` in the same change**, and this
  file if it is a hard gate. Keep each fact in 1 place.
