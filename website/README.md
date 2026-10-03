---
title: Documentation site
summary: How the Docusaurus docs site is generated, built, previewed, and deployed, for maintainers.
---

# Home Keeper documentation site

This is the user-facing documentation site for Home Keeper. It uses
[Docusaurus](https://docusaurus.io/), and GitHub Pages serves it at
**https://prestomation.github.io/ha-home-keeper/**.

It has 2 audiences, each with its own sidebar:

- **User Guide** (at `/docs`): how to install and use Home Keeper.
- **Developer Guide** (at `/developer`): how other integrations talk to Home Keeper. It
  has the `docs/INTEGRATING.md` walkthrough and an **API reference** that is generated
  from the integration.

## Edit the canonical sources

The content pages are **not** written in `website/`. `scripts/sync-docs.mjs` generates
them from the canonical Markdown in the repository and rewrites links and images:

| Source (canonical) | Generated (gitignored) |
|---|---|
| `docs/guide/**/*.md` (one file per page) | website/docs/guide/ (User Guide) |
| `CHANGELOG.md` | website/docs/release-notes.md |
| `docs/INTEGRATING.md` | website/developer/integrating.md |
| `docs/GLUE_INTEGRATIONS.md` | website/developer/glue-integrations.md |
| `docs/EVENTS.md` | website/developer/events.md |
| `docs/design/architecture.md` | website/developer/architecture.md |
| `docs/SECURITY.md` | website/developer/security.md |

The full list is `DEV_DOCS` in `website/scripts/doc-map.mjs`.

`ci/generate_api_docs.py` renders the **API reference** (website/developer/api.md)
from the integration: `custom_components/home_keeper/api_surface.py` for the structure,
and `services.yaml` plus `strings.json` for each label and description. Thus the page
and the Home Assistant dialogs use the same text. `npm run sync` runs it after
`sync-docs.mjs`, which clears that directory first. It needs Python with `PyYAML`.

To change the docs, **edit `docs/guide/**/*.md` or `docs/*.md`**. Never edit the
generated trees (`website/docs/guide/`, `website/developer/`): each `npm run sync`
deletes and rebuilds them. To change the API reference, edit the integration. The only
hand-written pages in `website/` are the landing page (`src/pages/index.tsx`) and the
User Guide intro (`website/docs/intro.md`).

`docs/guide/` is the full user documentation. `README.md` is only the front page of the
repository. Put documentation for a new feature in `docs/guide/`.

## Local development

```bash
cd website
npm install
npm start        # dev server with live reload at http://localhost:3000/ha-home-keeper/
npm run build    # production build into website/build
npm run typecheck
```

`npm run sync` runs before `start`, `build`, and `typecheck`. It does 2 things:

- `scripts/sync-assets.mjs` copies the screenshots from `../docs/images` into
  `static/img/screenshots/`. Refer to them as `/img/screenshots/<file>.png`.
  `docs/images` stays the only home for screenshots.
- `scripts/sync-docs.mjs` generates the content pages (see above).

## Deployment

- **`docs-deploy.yml`** is a reusable workflow (`workflow_call`). The `deploy-docs` job
  in `release.yml` calls it after a **stable** release. It checks out the release tag
  from the `ref` input, sets `DOCS_VERSION` from `manifest.json` (the version badge in
  the navbar), and publishes to the root of the `gh-pages` branch. Thus the live site
  always shows the latest stable release.
  - It does not use the `release: [released]` event. `release.yml` creates the release
    with the default `GITHUB_TOKEN`, and an event from `GITHUB_TOKEN` never starts a new
    workflow run. A direct call runs in the same run.
  - `workflow_dispatch` is available for an urgent manual deploy or a recovery. Pass a
    `ref` (for example `v0.7.0`) to build a release tag, or omit it to build the branch
    HEAD.
- **`docs-preview.yml`** runs on PRs that change `website/**`, `CHANGELOG.md`, or
  `docs/**`. It publishes a preview under `pr-preview/pr-<n>/` on the `gh-pages` branch
  and posts a sticky comment with the URL. A second sticky comment links to each doc
  page that the PR changed. `scripts/changed-pages.mjs` finds those pages with the same
  source-to-page map, `scripts/doc-map.mjs`, that `sync-docs.mjs` uses. The preview is
  deleted when the PR closes.

Both workflows publish to the `gh-pages` branch. Thus **GitHub Pages must be set to
"Deploy from a branch" → `gh-pages` / root** in the repository settings. The production
deploy uses `clean-exclude: pr-preview/`, so it never deletes open previews.
