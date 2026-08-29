# Home Keeper documentation site

The user-facing documentation site for Home Keeper, built with
[Docusaurus](https://docusaurus.io/) and deployed to GitHub Pages at
**https://prestomation.github.io/ha-home-keeper/**.

It has two audiences with independent sidebars:

- **User Guide** (served at `/docs`) — how to install and use Home Keeper.
- **Developer Guide** (served at `/developer`) — how other integrations talk to Home
  Keeper: the `docs/INTEGRATING.md` walkthrough, plus an **API reference** generated
  from the integration's own surfaces.

## Content is generated — edit the canonical sources

The content pages are **not** authored in `website/`. `scripts/sync-docs.mjs`
generates them from the repo's canonical Markdown and rewrites links/images:

| Source (canonical) | Generated (gitignored) |
|---|---|
| `README.md` (split by `##` section) | `website/docs/guide/*.md` (User Guide) |
| `CHANGELOG.md` | `website/docs/release-notes.md` |
| `docs/INTEGRATING.md` | `website/developer/integrating.md` |
| `docs/GLUE_INTEGRATIONS.md` | `website/developer/glue-integrations.md` |
| `docs/EVENTS.md` | `website/developer/events.md` |
| `docs/DESIGN.md` | `website/developer/architecture.md` |
| `docs/SECURITY.md` | `website/developer/security.md` |

One page has no Markdown source at all. `ci/generate_api_docs.py` renders
`website/developer/api.md` — the **API reference** — from the integration itself:
`custom_components/home_keeper/api_surface.py` for the structure, and `services.yaml`
plus `strings.json` for every label and description, so the page and Home Assistant's
own dialogs read from one string. `npm run sync` runs it after `sync-docs.mjs`, which
clears that directory first, and it needs Python with `PyYAML` on the machine doing
the build.

So to change the docs, **edit `README.md` or `docs/*.md`** — never the generated
trees (`website/docs/guide/`, `website/developer/`), which are wiped and rebuilt on
every `npm run sync`. To change the API reference, edit the integration. The only
hand-authored pages in `website/` are the landing page (`src/pages/index.tsx`) and
the User Guide intro (`docs/intro.md`).

`README.md` is the source for the whole User Guide, so it stays the comprehensive
user doc — don't slim it down to a stub.

## Local development

```bash
cd website
npm install
npm start        # dev server with live reload at http://localhost:3000/ha-home-keeper/
npm run build    # production build into website/build
npm run typecheck
```

`npm run sync` (auto-run before `start`/`build`/`typecheck`) does two things:
`scripts/sync-assets.mjs` mirrors the committed screenshots from `../docs/images` into
`static/img/screenshots/` (reference them in docs as `/img/screenshots/<file>.png`),
and `scripts/sync-docs.mjs` generates the content pages (see above). `docs/images`
stays the single home for screenshots — keep capturing there with the Playwright
harness.

## Deployment

- **`docs-deploy.yml`** — a reusable workflow (`workflow_call`) invoked by
  `release.yml`'s `deploy-docs` job after a **stable** release is cut. It checks out
  the release tag passed in via the `ref` input, injects `DOCS_VERSION` from
  `manifest.json` (surfaced as the navbar version badge), and publishes to the root of
  the `gh-pages` branch. The live site is therefore always pinned to the latest stable
  release — users never see docs for unreleased features.
  - It is **not** triggered by the `release: [released]` event: that release is
    created by `release.yml` using the default `GITHUB_TOKEN`, and events triggered by
    `GITHUB_TOKEN` never start a new workflow run (GitHub's anti-recursion safeguard),
    so the event would silently never fire. Calling the workflow directly runs it
    inside the same triggering run and sidesteps that restriction.
  - A `workflow_dispatch` trigger is also available for emergency manual deploys (e.g.
    an urgent typo fix that can't wait for the next release) and one-time recovery.
    Pass a `ref` input (e.g. `v0.7.0`) to pin the build to a release tag; omit it to
    build from the branch HEAD.
- **`docs-preview.yml`** — on pull requests (that touch `website/**` or the canonical
  doc sources `README.md` / `CHANGELOG.md` / `docs/**`), builds a preview and publishes
  it under `pr-preview/pr-<n>/` on the `gh-pages` branch, posting a sticky comment with
  the preview URL. It posts a **second** sticky comment listing deep links to just the
  doc pages the PR changed — `scripts/changed-pages.mjs` maps the changed sources to
  their generated routes (README is section-granular, so only the User Guide pages whose
  `##` section changed are linked), reusing the source→page mapping in
  `scripts/doc-map.mjs` so it never drifts from `sync-docs.mjs`. Previews are torn down
  when the PR closes.

Both publish to the `gh-pages` branch, so **GitHub Pages must be set to "Deploy from a
branch" → `gh-pages` / root** in the repository settings. The production deploy uses
`clean-exclude: pr-preview/` so it never wipes open previews.
