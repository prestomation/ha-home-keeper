# Release Process

## Overview

Releases are produced by merging a single "release" PR to `main`. The PR bumps the
version and adds a changelog entry. After merge, CI tags the commit and publishes
the GitHub release automatically. No manual `git tag` step.

## Steps

1. **Open a release PR** that contains exactly these changes:
   - `custom_components/home_keeper/manifest.json` — bump `version` to `X.Y.Z`
   - `custom_components/home_keeper/const.py` — bump `PANEL_VERSION` to `"X.Y.Z"`
   - `CHANGELOG.md` — add a `## [X.Y.Z] - YYYY-MM-DD` section

   The two version values must match. The release workflow refuses to ship if they
   don't.

2. **Merge the PR.** On the merge commit to `main`, `release.yml` will:
   1. Read the version from `manifest.json`.
   2. Verify a matching `## [X.Y.Z]` entry exists in `CHANGELOG.md` and that
      `PANEL_VERSION` matches. If either check fails, the workflow fails loudly.
   3. Skip silently if tag `vX.Y.Z` already exists. This is why a PR must bump the
      version for *every* release, including a beta iteration: folding a new entry
      into an already-tagged `## [X.Y.Z]` section without bumping the version merges
      clean and then ships nothing, because this step sees nothing new to tag.
      `lint.yml`'s `changelog-release-gap` job (`ci/check-changelog-release-gap.py`)
      catches that case at PR time.
   4. Build `dist/home-keeper-panel.js` from TypeScript via Rollup.
   5. Build `home_keeper.zip` (the HACS asset).
   6. Push tag `vX.Y.Z` and create the GitHub Release with the changelog section as
      the body and `home_keeper.zip` attached.
   7. Comment on every issue the changelog section says this version fixes, and — on
      a stable release — close it. See "Issue notifications" below.

3. **HACS picks it up** via `hacs.json` (`zip_release: true`, `filename:
   home_keeper.zip`).

### Link the docs from every feature bullet

An `### Added` bullet writes its bold lead as a Markdown link to the page that
documents the feature:

```markdown
- **[Import and export](https://prestomation.github.io/ha-home-keeper/docs/guide/import-export).**
  Settings has a new *Import and export* card that saves every task and appliance to
  one YAML file, and reads one back.
```

- **Why the lead.** `summarize()` in `ci/release-issues.py` quotes only the bold lead
  into the comment the issue reporter gets, so a linked lead carries the docs link
  into that comment too. A link also costs nothing against the three-sentence bullet
  budget.
- **Use the absolute site URL.** The bullet is read on GitHub and in the release body,
  not only in the repository, so a relative path does not resolve.
- **Finding a User Guide URL.** The page is
  `https://prestomation.github.io/ha-home-keeper/docs/guide/<slug>`, where `<slug>` is
  the README section's `USER_SECTIONS` entry in `website/scripts/doc-map.mjs`. A
  deeper anchor is that page plus the heading slug.
- **Finding a Developer Guide URL.** The route is that file's `DOC_ROUTES` value in
  `website/scripts/doc-map.mjs` (`docs/INTEGRATING.md` → `/developer/integrating`),
  appended to `https://prestomation.github.io/ha-home-keeper`. The generated API
  reference is `GENERATED_DEV_PAGES` instead, which carries its `route` directly.
- **A link to a page the release itself adds resolves only when a _stable_ ships.**
  `deploy-docs` in `release.yml` is gated on `prerelease == 'false'`, so a beta never
  republishes the site. Write the link in the feature PR anyway — that is the moment
  the author knows which page documents the feature, and the stable cut then rolls the
  bullet up unchanged — but know what it costs: the bullet ships in a `## [X.Y.ZbN]`
  section whose link 404s for every beta tester until the stable publishes. That is the
  price of pinning the site to the latest stable so nobody reads docs for an unreleased
  feature, and it is a deliberate trade, not an oversight. Prefer an existing page when
  one already covers the feature.
- **Nothing validates these URLs.** A typo 404s forever, and no gate catches it. Check
  the shape against a page that is already live before you commit the bullet.
- `### Fixed` and `### Changed` bullets may link the same way when a page covers the
  change. They do not have to.

## Issue notifications

An issue closes when its fix **ships**, not when its PR merges. A merged PR is not in
anyone's Home Assistant yet — it may sit on `main` for days and go out in a beta before
it reaches everyone.

Closing-on-merge is turned off for this repository, so a PR's `Fixes #N` links the
issue (filling in its **Development** panel) without closing it, and the issue stays
open on its own. Keep writing `Fixes #N` — the link is worth having.

The `notify-issues` job in `release.yml` closes the loop. It reads the shipped
version's `## [X.Y.Z]` CHANGELOG section, pulls out every `(Fixes #N)` reference, and
for each one:

- **On a beta** — comments that the fix is available for testing, with the "Show beta
  versions" instructions, and leaves the issue **open**.
- **On a stable** — comments that it shipped, quotes the changelog bullet, and closes
  the issue as `completed`.

Notes on how it behaves:

- **`(Fixes #N)` in the changelog is the only thing that notifies an issue.** Forget it
  and the issue is never told and never closes. The job posts a CI warning naming any
  issue that a commit in the release referenced but the section left out — check the
  job summary after a release. A **developer-only** issue (a CI or tooling fix, which
  correctly gets no changelog entry) shows up here too; that one is expected, and
  closing it is a manual call.
- **The cross-check range depends on the kind of release.** A stable is compared
  against the previous stable, because its section rolls up every beta in between. A
  beta is compared against the previous tag of any kind, because its section covers
  only its own increment.
- **Bare `(#N)` is ignored**, because it's also the PR number squash-merge appends to
  commit subjects, and the two can't be distinguished. So is `(Related to #N)`.
- **Re-running is safe.** Each comment carries a `<!-- home-keeper-release vX.Y.Z -->`
  marker and the job skips any issue that already has one.
- **It can't fail a release.** The release is already tagged and published by the time
  it runs; a bad issue number becomes a warning and a row in the job summary.

### Rehearsing it

Run the workflow manually (Actions → Release → Run workflow) with **notify_dry_run**
checked and **notify_version** set to a past release such as `0.15.0`. The job resolves
the same issue list and writes the full plan to the run summary without posting or
closing anything.

The parsing itself lives in `ci/release-issues.py`, which also cuts the release notes.
Run it locally against any version:

```bash
python3 ci/release-issues.py --version 0.15.0 --json    # issues it would notify
python3 ci/release-issues.py --version 0.15.0 --notes   # the release body
```

## Beta / pre-release releases

Betas go through the *exact same flow* — the only difference is the version string.
Use a PEP 440 pre-release suffix: `bN` (beta), `aN` (alpha), or `rcN` (e.g.
`0.2.0b1`). `release.yml` recognizes the suffix and publishes the GitHub release as
a **pre-release**, so HACS offers it only to users who enabled "Show beta versions".
Cut the final `0.2.0` (with its own `## [0.2.0]` changelog section) when ready.

## Preview releases (test a PR build without merging)

Sometimes you want to **install and try a PR's build via HACS** before merging it —
without bumping the version or cutting a real release. Add the **`preview-release`**
label to the PR and `preview-release.yml` builds the panel + `home_keeper.zip` from the
PR head, stamps a synthetic version (`X.Y.Z.dev<pr>`) into the zip's manifest, and
publishes an **ephemeral GitHub pre-release** with the zip attached. Install it from
HACS: open *Home Keeper* → ⋮ → **Redownload**, enable **Show beta versions**, and pick
`X.Y.Z.dev<pr>` (or download `home_keeper.zip` from the release and unzip into
`config/custom_components/home_keeper/`).

- **Opt-in only** — nothing happens without the label (and only users with write
  access can label).
- **Same-repo PRs only** — fork PRs get no token and are not built this way.
- **Owner approval** — the publish job runs in the `preview-release` GitHub
  Environment; add **Required reviewers** to it (Settings → Environments) to make each
  build wait for an explicit approval.
- **Ephemeral & low-noise** — it's a **pre-release** (`prerelease: true`), so it's
  offered only to users who enabled *Show beta versions*; the `.dev<pr>` version sorts
  *below* the real `X.Y.Z` release so it never nags anyone as an update; it's
  re-published on each push and **deleted automatically when the PR closes**.

See [docs/PR_PREVIEW_RELEASE_PLAN.md](docs/PR_PREVIEW_RELEASE_PLAN.md) for the full
design and rationale.

## Constraints

- **Never push directly to `main`.** All changes go through PRs.
- **Never create GitHub releases manually** — `release.yml` handles tag, zip, release.
- **`dist/home-keeper-panel.js` is gitignored.** It's built by CI from TypeScript
  source.
- **`hacs.json` must have `zip_release: true`** with `filename: home_keeper.zip`.

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| "manifest.json is at X.Y.Z but CHANGELOG.md has no '## [X.Y.Z]' section" | Missing changelog entry | Add it in a follow-up PR |
| "manifest.json version does not match const.py PANEL_VERSION" | Bumped one but not the other | Align both in a PR |
| "Tag vX.Y.Z already exists" | Version wasn't bumped | Bump the version in a new PR |
| HACS install fails / "No valid version found" | Missing `home_keeper.zip` asset | Check `hacs.json` `zip_release: true` |
