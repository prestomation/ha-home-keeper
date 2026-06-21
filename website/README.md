# Home Keeper documentation site

The user-facing documentation site for Home Keeper, built with
[Docusaurus](https://docusaurus.io/) and deployed to GitHub Pages at
**https://prestomation.github.io/ha-home-keeper/**.

It has two audiences with independent sidebars:

- **User Guide** (`docs/`, served at `/docs`) — how to install and use Home Keeper.
- **Developer Guide** (`developer/`, served at `/developer`) — the equivalent of
  `docs/INTEGRATING.md`: how other integrations talk to Home Keeper.

## Local development

```bash
cd website
npm install
npm start        # dev server with live reload at http://localhost:3000/ha-home-keeper/
npm run build    # production build into website/build
npm run typecheck
```

Screenshots are **not** copied into the repo. `scripts/sync-assets.mjs` mirrors the
integration's committed screenshots from `../docs/images` into
`static/img/screenshots/` automatically before `start`/`build` (so reference them in
docs as `/img/screenshots/<file>.png`). `docs/images` stays the single home for
screenshots — keep capturing there with the Playwright harness.

## Deployment

- **`docs-deploy.yml`** — on push to `main` (touching `website/**` or
  `docs/images/**`), builds and publishes to the root of the `gh-pages` branch.
- **`docs-preview.yml`** — on pull requests, builds a preview and publishes it under
  `pr-preview/pr-<n>/` on the `gh-pages` branch, posting a sticky comment with the
  preview URL. Previews are torn down when the PR closes.

Both publish to the `gh-pages` branch, so **GitHub Pages must be set to "Deploy from a
branch" → `gh-pages` / root** in the repository settings. The production deploy uses
`clean-exclude: pr-preview/` so it never wipes open previews.
