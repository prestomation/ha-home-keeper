---
title: CHANGELOG and release rules
summary: How to write a CHANGELOG bullet, when to cut a beta, and how a release notifies and closes issues.
---

# CHANGELOG and release rules

The release steps are in [RELEASE.md](../../RELEASE.md). This file gives the rules that a
feature PR must follow so that its work ships.

## CHANGELOG entries

- Update `CHANGELOG.md` for every user-facing change. Developer-only changes (CI config,
  `AGENTS.md`, `IDEAS.md`, the rules) need no entry.
- **One bullet, 3 sentences at most, for the whole bullet.** The bold lead counts as the
  first sentence. Then write what a user notices. Then a caveat or `(Fixes #N)` if one is
  needed. Never write a second paragraph.
- Cut the worked example, the before-and-after story, the list of surfaces that show the
  new value, and the inventory of new service fields and attributes. That detail goes in
  `docs/guide/`, `docs/`, or the PR body.
- **The bullet says what a user gets.** Do not narrate the mechanism: which buttons the
  feature hides or shows, what it rewrites, which fields it adds. If a trimmed bullet
  loses a real fact, split it into 2 bullets. Do not grow 1 bullet.
- Every bullet is user-facing text. It follows [writing-style.md](writing-style.md)
  and the vale `ai-tells` style.

### The bold lead

- **The lead is a label.** It is a short noun phrase of 2 to 5 words, 8 at most:
  `**Declarative companions.**`, `**Snooze and skip.**`.
- **Write it as a heading.** Drop the articles and prepositions: `**Seasonal tasks.**`,
  not `**Seasons on a task.**`. If a lead still has "a", "the", "of", "on", or "for",
  try again.
- A lead that opens `Home Keeper can now…`, `A user can now…`, `The panel now…` or
  `Give a task…` narrates. Cut it back to the noun.
- The lead must stand alone. `summarize()` in `ci/release-issues.py` quotes the whole
  bullet into the comment that an issue reporter gets, and the lead comes first.
- **An `### Added` lead links its documentation**, with the bold outside the link:
  `**[Import and export](https://prestomation.github.io/ha-home-keeper/docs/guide/import-export).**`.
  Use the absolute site URL. A guide page is `.../docs/guide/<slug>`, where the slug is the
  `USER_SECTIONS` entry in `website/scripts/doc-map.mjs`. Link the nearest page that says
  what the feature does, never the README.
- A `### Fixed` or `### Changed` lead can link the same way. It does not have to.
- Nothing validates these URLs, so copy the shape of a link that is already live. A link
  to a page that the release adds 404s for beta testers until a stable ships, because
  `deploy-docs` in `release.yml` runs only for a stable. Write the link in the feature PR
  anyway.

### Issues and credits

- **`(Fixes #N)` in a version's section is what notifies and closes the issue.**
  `release.yml`'s `notify-issues` job comments on every issue that the shipped section
  names, and closes it on a stable. An issue left out is never told and never closes.
- Only the closing keyword counts. `(Related to #N)` and a bare `(#N)` are ignored,
  because `(#N)` is also the squash-merge PR number.
- Put `(Fixes #N)` in the bullet's **first** paragraph. `ci/release-issues.py` quotes the
  bullet where the reference first appears. Change the format there, not in the workflow.
- **Credit an outside contributor** with `(Thanks @user!)` at the end of the bullet,
  after `(Fixes #N)`. The credit is outside the 3-sentence budget. An outside contributor
  has no write access when the PR opens. If a maintainer and a contributor share the work,
  the contributor gets the credit. `summarize()` removes the credit from the issue comment.
- **Link an issue from a PR with `Fixes #N`.** Closing on merge is off for this
  repository, so the keyword fills the issue's Development panel and closes nothing. The
  release that ships the fix closes the issue.

## Stable sections

- A stable `## [X.Y.Z]` section describes the changes since the last **stable**, for a
  user who upgrades from it. Roll the beta work into Added, Changed and Fixed as that user
  sees it. A feature that the betas introduced is **Added**, even if a later beta changed it.
- Include a `### Fixed` section with every issue that commits since the last stable fixed.
  Search the git log for `(Fixes #N)` and write each one as `(Fixes #N)`. `notify-issues`
  posts a CI warning for an issue that a commit named and the section forgot.

## Versions and betas

- `manifest.json` `version` is the source of truth. `const.py` `PANEL_VERSION` must match.
  A `bN`, `aN` or `rcN` suffix ships as a GitHub pre-release, which is the HACS beta channel.
- **Use the next release number for a beta.** After stable `X.Y.0` ships, bump `main` to
  `X.(Y+1).0b1` at once and rename `## [Unreleased]` to `## [X.(Y+1).0b1]`. Never cut
  `X.Y.0bN` after `X.Y.0`: PEP 440 sorts it below the stable, so HACS offers the stable
  to beta users as an upgrade.
- **A new feature cuts a beta.** The feature PR bumps `manifest.json` and `PANEL_VERSION`
  to the next `bN` and adds a matching `## [X.Y.0bN]` section. If the top section is an
  unreleased beta, fold the feature into it. If that beta is already tagged, open the next
  `bN`. A bug-fix or developer-only PR needs no new beta.
- `release.yml` skips a version that is already tagged and says nothing. So
  `lint.yml`'s `changelog-release-gap` job (`ci/check-changelog-release-gap.py`) fails a PR
  that edits the top section of a tagged version with no version bump.
- **Label a new-feature PR `preview-release`** as soon as it is open.
  `preview-release.yml` then publishes an installable `X.Y.Z.dev<pr>` pre-release from the
  PR head, so testers can try it in HACS before the merge. A bug-fix or developer-only PR
  does not need the label.
- The built `dist/home-keeper-panel.js` is gitignored. CI builds it.
