---
title: Release process
summary: How a maintainer cuts a stable, beta, or PR preview release, and how CI ships it.
---

# Release Process

## Overview

You release by merging one "release" PR to `main`. The PR bumps the version and adds a
changelog entry. After the merge, CI tags the commit and publishes the GitHub release.
There is no manual `git tag` step.

## Steps

1. **Open a release PR** that contains exactly these changes:
   - `custom_components/home_keeper/manifest.json`: bump `version` to `X.Y.Z`.
   - `custom_components/home_keeper/const.py`: bump `PANEL_VERSION` to `"X.Y.Z"`.
   - `CHANGELOG.md`: add a `## [X.Y.Z] - YYYY-MM-DD` section.

   The two version values must match. The release workflow does not ship if they differ.

2. **Merge the PR.** On the merge commit to `main`, `release.yml`:
   1. Reads the version from `manifest.json`.
   2. Checks that a matching `## [X.Y.Z]` entry is in `CHANGELOG.md` and that
      `PANEL_VERSION` matches. If a check fails, the workflow fails.
   3. Stops without output if tag `vX.Y.Z` exists. Thus a PR must bump the version for
      *every* release, including a beta iteration. An entry folded into a tagged
      section without a bump merges clean and ships nothing. `lint.yml`'s
      `changelog-release-gap` job (`ci/check-changelog-release-gap.py`) catches this at
      PR time.
   4. Builds `dist/home-keeper-panel.js` from TypeScript with Rollup.
   5. Builds `home_keeper.zip` (the HACS asset).
   6. Pushes tag `vX.Y.Z` and creates the GitHub Release. The body is the changelog
      section, and `home_keeper.zip` is attached.
   7. Comments on every issue that the section says this version fixes. On a stable
      release, it also closes the issue. See [Issue notifications](#issue-notifications).

3. **HACS finds the release** through `hacs.json` (`zip_release: true`,
   `filename: home_keeper.zip`).

### Link the docs from every feature bullet

An `### Added` bullet writes its bold lead as a Markdown link to the page that documents
the feature:

```markdown
- **[Import and export](https://prestomation.github.io/ha-home-keeper/docs/guide/import-export).**
  Settings has a new *Import and export* card that saves every task and appliance to
  one YAML file, and reads one back.
```

- **Why the lead.** `summarize()` in `ci/release-issues.py` quotes the whole bullet into
  the comment the issue reporter gets, so the link goes there too.
- **Use the absolute site URL.** People read the bullet on GitHub and in the release
  body, where a relative path does not resolve.
- **User Guide URL.** Use `https://prestomation.github.io/ha-home-keeper/docs/guide/<slug>`,
  where `<slug>` is the page's `USER_SECTIONS` entry in `website/scripts/doc-map.mjs`.
  For a deeper anchor, add the heading slug.
- **Developer Guide URL.** Add the file's `DOC_ROUTES` value in
  `website/scripts/doc-map.mjs` (`docs/INTEGRATING.md` → `/developer/integrating`) to
  `https://prestomation.github.io/ha-home-keeper`. The generated API reference is in
  `GENERATED_DEV_PAGES`, which gives its `route` directly.
- **A link to a page that the release adds resolves only when a _stable_ ships.**
  `deploy-docs` in `release.yml` runs only when `prerelease == 'false'`, so a beta does
  not publish the site. Write the link in the feature PR anyway. Beta testers get a 404
  until the stable ships, because the site shows only the latest stable. Prefer an
  existing page when one covers the feature.
- **Nothing validates these URLs.** A typo gives a 404 with no gate to catch it. Compare
  the shape with a live page before you commit the bullet.
- `### Fixed` and `### Changed` bullets can link the same way when a page covers the
  change. This is optional.

## Issue notifications

An issue closes when its fix **ships**, not when its PR merges. A merged PR is not in a
user's Home Assistant until a release carries it.

Closing-on-merge is off for this repository. A PR's `Fixes #N` links the issue (it fills
in the **Development** panel) and does not close it. Keep writing `Fixes #N`.

The `notify-issues` job in `release.yml` reads the shipped version's `## [X.Y.Z]`
CHANGELOG section and finds every `(Fixes #N)`. For each one:

- **On a beta**, it comments that the fix is ready to test, with the "Show beta
  versions" steps. The issue stays **open**.
- **On a stable**, it comments that the fix shipped, quotes the changelog bullet, and
  closes the issue as `completed`.

How the job behaves:

- **Only `(Fixes #N)` in the changelog notifies an issue.** If you forget it, the issue
  never gets a comment and never closes. The job posts a CI warning for each issue that a
  commit in the release refers to and the section does not. Read the job summary after a
  release. A developer-only issue (CI or tooling, with no changelog entry) also shows
  there. Close that one by hand.
- **The cross-check range depends on the release kind.** A stable compares against the
  previous stable, because its section includes all betas between them. A beta compares
  against the previous tag of any kind.
- **The job ignores a bare `(#N)`**, because squash-merge adds the PR number to commit
  subjects in that form. It also ignores `(Related to #N)`.
- **You can run it again safely.** Each comment has a `<!-- home-keeper-release vX.Y.Z -->`
  marker, and the job skips an issue that has one.
- **It cannot fail a release.** The release is tagged and published before the job runs.
  A bad issue number becomes a warning and a row in the job summary.

### Rehearse the job

Run the workflow manually (Actions → Release → Run workflow). Select **notify_dry_run**
and set **notify_version** to a past release, for example `0.15.0`. The job finds the
same issue list and writes the plan to the run summary. It posts and closes nothing. A
dry run never tags, publishes, or deploys. Only a push to `main`, or a dispatch on
`main` with **notify_dry_run** cleared, does that.

`ci/release-issues.py` does the parsing and also makes the release notes. Run it locally:

```bash
python3 ci/release-issues.py --version 0.15.0 --json    # issues it would notify
python3 ci/release-issues.py --version 0.15.0 --notes   # the release body
```

## Beta and pre-release releases

Betas use the same flow. Only the version string is different. Use a PEP 440
pre-release suffix: `bN` (beta), `aN` (alpha), or `rcN`, for example `0.2.0b1`.
`release.yml` finds the suffix and publishes a **pre-release**. HACS offers it only to
users who turn on "Show beta versions". Cut the final `0.2.0`, with its own
`## [0.2.0]` section, when it is ready.

## Preview releases

A preview release lets a tester install a PR's build through HACS before the merge. It
does not bump the version or cut a real release. `preview-release.yml` does the work.

- **Trigger.** Add the **`preview-release`** label to the PR. Only users with write
  access can add labels, so the label is a maintainer gate. Each push to the PR
  publishes again.
- **Same-repository PRs only.** A fork PR gets no write token, and the workflow does not
  use `pull_request_target`, so it never builds untrusted code with write scope.
- **Owner approval.** The publish job runs in the `preview-release` GitHub Environment.
  To make each build wait for approval, add **Required reviewers** to it (Settings →
  Environments). This is a repository setting, not workflow YAML.
- **Version.** The workflow takes the `X.Y.Z` core of `manifest.json` and stamps
  `X.Y.Z.dev<pr>` into the zip's manifest only. It never commits the change, so the
  release gates do not apply. The `.dev<pr>` version sorts *below* `X.Y.Z`, so HACS
  never offers it as an update. The PR number keeps it unique.
- **Build.** It runs `ci/build-panel.sh` and `ci/build-zip.sh`, as `release.yml` does.
  It then publishes a GitHub pre-release with tag `vX.Y.Z.dev<pr>` and `home_keeper.zip`
  attached, and posts a sticky PR comment with the install steps.
- **Install.** In HACS, open *Home Keeper* → ⋮ → **Redownload**, turn on **Show beta
  versions**, and select `X.Y.Z.dev<pr>`. HACS can need a refresh to show it. As an
  alternative, unzip `home_keeper.zip` from the release into
  `config/custom_components/home_keeper/`.
- **Cleanup.** Each push deletes the previous preview release and tag first. When the PR
  closes, the `cleanup` job deletes every release named `Preview · PR #<n> (…)` and its
  tag.
- **Separate from `release.yml`.** A `v*.dev*` tag does not start `release.yml`, which
  runs only on pushes to the `main` branch. Thus a preview cannot publish a real release.

## Constraints

- **Never push directly to `main`.** All changes go through PRs.
- **Never create GitHub releases manually.** `release.yml` makes the tag, zip, and
  release.
- **Git ignores `dist/home-keeper-panel.js`.** CI builds it from the TypeScript source.
- **`hacs.json` must have `zip_release: true`** with `filename: home_keeper.zip`.

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| "manifest.json is at X.Y.Z but CHANGELOG.md has no '## [X.Y.Z]' section" | Missing changelog entry | Add it in a follow-up PR |
| "manifest.json version does not match const.py PANEL_VERSION" | Bumped one but not the other | Align both in a PR |
| "Tag vX.Y.Z already exists" | Version wasn't bumped | Bump the version in a new PR |
| HACS install fails / "No valid version found" | Missing `home_keeper.zip` asset | Check `hacs.json` `zip_release: true` |
