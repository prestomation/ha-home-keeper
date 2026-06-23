# Preview releases from a PR (without merging to main)

**Status: shipped (Model B — HACS-installable pre-release).** This documents the
design for producing an **installable build of the integration from a PR** — testable
*through HACS* before merging — without bumping the real version or cutting a real
release. It mirrors the existing **website PR preview** (`docs-preview.yml` → ephemeral
`gh-pages/pr-preview/pr-<n>/` + sticky comment) but for the integration zip.

Implemented by [`.github/workflows/preview-release.yml`](../.github/workflows/preview-release.yml).

## What ships (Model B — ephemeral pre-release, HACS-installable)

On an **opted-in** PR, CI builds the panel + `home_keeper.zip` from the PR head,
stamps a synthetic version into the zip's `manifest.json`, and publishes an **ephemeral
GitHub pre-release** (`prerelease: true`) with the zip attached, then posts a sticky PR
comment with install steps. A tester installs it from **HACS** (Home Keeper →
Redownload → *Show beta versions* → pick the `.dev<pr>` version), or downloads the zip
from the release for a manual drop-in.

> An earlier iteration shipped **Model A** (artifact-only, manual install, no release).
> We switched to Model B so the build is installable through HACS like a normal beta.
> Model A's trade-off was zero release/version pollution; Model B accepts a *gated,
> ephemeral, auto-cleaned* footprint in the beta channel to gain the HACS install path
> (see "Pollution & low-noise" below). The artifact-only approach remains a valid
> fallback if HACS-channel noise ever becomes a problem.

## How it's triggered (opt-in, gated)

- **Label `preview-release`** on the PR (`pull_request` `types: [labeled,
  synchronize, reopened, closed]`). Only users with **write access can apply labels**,
  so the label itself is a maintainer gate; pushing more commits to a labelled PR
  re-publishes, and closing the PR cleans up.
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

## Versioning (no real-version bump, HACS-parseable, no collisions)

The preview never edits committed files. At build time it computes a version and
stamps it into the zip's `manifest.json` only, and tags the pre-release `v<version>`:

```
<x.y.z>.dev<pr>     e.g. 0.4.0.dev81   (tag v0.4.0.dev81)
```

- A clean **PEP 440 dev release** (no `+local` segment, so HACS/`AwesomeVersion`
  parses it reliably and treats it as a beta).
- The `.dev<pr>` segment sorts **below** the `x.y.z` release, so it never appears as
  an available *upgrade* — it's only **selectable** in HACS' version list (with betas
  enabled), never pushed at users.
- Keyed by PR number, so two PRs off the same base never collide.
- Written in-workflow and **never committed** — the branch's `manifest.json` and
  `CHANGELOG.md` are untouched, so the strict release gates (changelog entry,
  `PANEL_VERSION == version`, unique `vX.Y.Z` tag) don't apply.

## Why a separate workflow (not a flag on `release.yml`)

`release.yml` enforces the production release contract (matching changelog +
`PANEL_VERSION`, unique tag) and only tags/publishes off `main`. Previews live in
their own `preview-release.yml` so those guarantees stay strict and un-bypassable —
the preview path can't accidentally publish a real release. (Creating a `v*.dev*` tag
does not trigger `release.yml`: it's gated on pushes to the `main` *branch*, not tags.)

## Cleanup (ephemeral)

The pre-release is **re-published on each push** (the prior release + tag are deleted
first so the tag tracks the current head) and **deleted when the PR closes** — a
`closed`-event `cleanup` job removes any release named `Preview · PR #<n> (…)` and its
tag, so nothing lingers in the Releases list or HACS' beta channel. A `concurrency`
group `preview-release-${{ github.event.number }}` with `cancel-in-progress` supersedes
an in-flight build, and the sticky comment is updated in place (one per PR).

## Additional considerations (carried from the design review)

- **Pollution & low-noise.** A pre-release is visible to users with *Show beta
  versions* enabled. We keep the footprint minimal: `prerelease: true` (off the stable
  channel), `.dev<pr>` sorting below the real release (never an "update"), the
  per-push re-publish, and the **auto-delete on close**. If beta-channel noise ever
  becomes a problem, the artifact-only Model A or a dedicated preview repo are the
  fallbacks.
- **Security / untrusted code.** Same-repo-only + the label gate + the environment
  approval; no `pull_request_target`. Note the publish job needs `contents: write`, so
  the same-repo/label/approval gates matter more than in an artifact-only build.
- **Panel build parity.** The preview runs `ci/build-panel.sh` exactly like
  `release.yml`, so the zip contains the same built `home-keeper-panel.js` a real
  release would — "works in preview" tracks "works on release".
- **HACS caching.** HACS may need a manual refresh (or its periodic poll) before a new
  pre-release appears; the sticky comment notes this.
- **Cost/concurrency.** Bounded by the label gate + `cancel-in-progress`.
- **Provenance.** Preview builds are intentionally **not** signed/attested as
  production releases; `prerelease: true`, the `.dev` version, and the "do not depend on
  it" wording keep them clearly non-production.

## Deferred (beyond Model B)

- **Dedicated preview repository** that testers add as a HACS custom repo — the
  cleanest isolation (no beta-channel footprint on the main repo at all), at the cost
  of standing up and maintaining a second repo.
- **`/preview-release` PR-comment command** as an alternative trigger to the label
  (more `issue_comment` plumbing; the label is simpler).
- **Artifact-only mode (former Model A)** kept in mind as the fallback if HACS-channel
  noise is unwelcome.
