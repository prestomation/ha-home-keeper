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
   3. Skip silently if tag `vX.Y.Z` already exists.
   4. Build `home-keeper-panel.js` from TypeScript via Rollup.
   5. Build `home_keeper.zip` (the HACS asset).
   6. Push tag `vX.Y.Z` and create the GitHub Release with the changelog section as
      the body and `home_keeper.zip` attached.

3. **HACS picks it up** via `hacs.json` (`zip_release: true`, `filename:
   home_keeper.zip`).

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
- **`home-keeper-panel.js` is gitignored.** It's built by CI from TypeScript source.
- **`hacs.json` must have `zip_release: true`** with `filename: home_keeper.zip`.

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| "manifest.json is at X.Y.Z but CHANGELOG.md has no '## [X.Y.Z]' section" | Missing changelog entry | Add it in a follow-up PR |
| "manifest.json version does not match const.py PANEL_VERSION" | Bumped one but not the other | Align both in a PR |
| "Tag vX.Y.Z already exists" | Version wasn't bumped | Bump the version in a new PR |
| HACS install fails / "No valid version found" | Missing `home_keeper.zip` asset | Check `hacs.json` `zip_release: true` |
