# Preview releases from a PR (without merging to main)

**Status: shipped (Model A).** This documents the design for producing an
**installable build of the integration from a PR** — testable before merging —
without bumping the real version, tagging, or publishing anything HACS-visible. It
mirrors the existing **website PR preview** (`docs-preview.yml` → ephemeral
`gh-pages/pr-preview/pr-<n>/` + sticky comment) but for the integration zip.

Implemented by [`.github/workflows/preview-release.yml`](../.github/workflows/preview-release.yml).

## What ships (Model A — artifact, manual install)

On an **opted-in** PR, CI builds the panel + `home_keeper.zip` from the PR head,
stamps a synthetic version into the zip's `manifest.json`, uploads the zip as a
**workflow artifact**, and posts a **sticky PR comment** with the download link and
manual-install steps. No tag, no GitHub Release, nothing HACS picks up.

We deliberately chose Model A over a HACS-installable pre-release (Model B) because
artifact-only delivery has **zero release/version pollution** and no mutable-tag
caveats — and "let me try this PR's build" is satisfied by a manual drop-in. Model B
(an ephemeral `preview/pr-<n>` pre-release, or a dedicated preview repo) is recorded
under "Deferred" for if HACS-native install testing is ever actually needed.

## How it's triggered (opt-in, gated)

- **Label `preview-release`** on the PR (`pull_request` `types: [labeled,
  synchronize, reopened]`). Only users with **write access can apply labels**, so the
  label itself is a maintainer gate; pushing more commits to a labelled PR rebuilds.
- **Same-repo PRs only.** The job's `if:` requires
  `head.repo.full_name == github.repository`. A fork PR gets no write token, and we
  refuse to build untrusted code with elevated scope. We do **not** use
  `pull_request_target` (it would run with the base repo's secrets against PR-authored
  code — the classic privilege-escalation footgun). Fork contributions are reviewed
  and landed normally.
- **Owner approval (optional but recommended).** The job runs in the
  `preview-release` **GitHub Environment**. Configure **Required reviewers** on it
  (Settings → Environments → `preview-release`) and every preview build pauses for an
  explicit approval before running. *This is the one manual setup step — workflow YAML
  can reference the environment, but the reviewer list is a repo setting.*

## Versioning (no real-version bump, no collisions)

The preview never edits committed files. At build time it computes a **PEP 440 local
version** and stamps it into the zip's `manifest.json` only:

```
<base_version>.dev<pr>+pr<pr>.g<short_sha>     e.g. 0.4.0.dev81+pr81.gd1f30f3
```

- The `.devN` segment sorts **below** any real `0.4.x` release, so an installed
  preview can never masquerade as "latest" and HACS would never prefer it.
- The `+pr<n>.g<sha>` local segment ties the build to its PR and commit.
- It is written in-workflow and **never committed** — the branch's `manifest.json`
  and `CHANGELOG.md` are untouched, so the strict release gates (changelog entry,
  `PANEL_VERSION == version`, unique `vX.Y.Z` tag) don't apply.

## Why a separate workflow (not a flag on `release.yml`)

`release.yml` enforces the production release contract (matching changelog +
`PANEL_VERSION`, unique tag) and only tags/publishes off `main`. Previews live in
their own `preview-release.yml` so those guarantees stay strict and un-bypassable —
the preview path can't accidentally publish a real release.

## Cleanup

Artifacts carry `retention-days: 5` and expire on their own; a `concurrency` group
`preview-release-${{ github.event.number }}` with `cancel-in-progress` supersedes an
in-flight build when new commits land. The sticky comment is updated in place (one
comment per PR), so there's nothing to delete on close. (Model B, if added, would also
need a `closed`-event step to delete its tag/Release — Model A has no such state.)

## Additional considerations (carried from the design review)

- **Security / untrusted code.** Covered by same-repo-only + the label gate + the
  environment approval; no `pull_request_target`.
- **Panel build parity.** The preview runs `ci/build-panel.sh` exactly like
  `release.yml`, so the zip contains the same built `home-keeper-panel.js` a real
  release would — "works in preview" tracks "works on release".
- **Discoverability.** Nothing lands in the Releases list or HACS; the artifact is
  visible only to people who can see the PR's Actions run.
- **Cost/concurrency.** Bounded by the label gate + `cancel-in-progress`.
- **Provenance.** Preview artifacts are intentionally **not** signed/attested as
  production builds; the synthetic `.devN` version and the comment's "do not depend on
  it" wording keep them clearly non-production.

## Deferred (Model B and beyond)

- **HACS-installable preview** — an ephemeral `prerelease: true` Release tagged
  `preview/pr-<n>` (a non-`vX.Y.Z` namespace) with the zip attached, plus a
  `closed`-event cleanup step. Only worth it if testers specifically need the HACS
  install path; it reintroduces beta-channel visibility and mutable-tag caching
  caveats.
- **Dedicated preview repository** that testers add as a HACS custom repo — the
  cleanest isolation for HACS-native testing, at the cost of standing up and
  maintaining a second repo.
- **`/preview-release` PR-comment command** as an alternative trigger to the label
  (more `issue_comment` plumbing; the label is simpler).
