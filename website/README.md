# Home Keeper documentation site

The user-facing documentation site for Home Keeper, built with
[Docusaurus](https://docusaurus.io/) and deployed to GitHub Pages at
**https://prestomation.github.io/ha-home-keeper/**.

It has two audiences with independent sidebars:

- **User Guide** (served at `/docs`) — how to install and use Home Keeper.
- **Developer Guide** (served at `/developer`) — the equivalent of
  `docs/INTEGRATING.md`: how other integrations talk to Home Keeper.

## Content is generated — edit the canonical sources

The content pages are **not** authored in `website/`. `scripts/sync-docs.mjs`
generates them from the repo's canonical Markdown and rewrites links/images:

| Source (canonical) | Generated (gitignored) |
|---|---|
| `README.md` (split by `##` section) | `website/docs/guide/*.md` (User Guide) |
| `docs/INTEGRATING.md` | `website/developer/integrating.md` |
| `docs/EVENTS.md` | `website/developer/events.md` |
| `docs/DESIGN.md` | `website/developer/architecture.md` |

So to change the docs, **edit `README.md` or `docs/*.md`** — never the generated
trees (`website/docs/guide/`, `website/developer/`), which are wiped and rebuilt on
every `npm run sync`. The only hand-authored pages in `website/` are the landing page
(`src/pages/index.tsx`) and the User Guide intro (`docs/intro.md`).

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

- **`docs-deploy.yml`** — on push to `main` (touching `website/**` or
  `docs/images/**`), builds and publishes to the root of the `gh-pages` branch.
- **`docs-preview.yml`** — on pull requests, builds a preview and publishes it under
  `pr-preview/pr-<n>/` on the `gh-pages` branch, posting a sticky comment with the
  preview URL. Previews are torn down when the PR closes.

Both publish to the `gh-pages` branch, so **GitHub Pages must be set to "Deploy from a
branch" → `gh-pages` / root** in the repository settings. The production deploy uses
`clean-exclude: pr-preview/` so it never wipes open previews.
