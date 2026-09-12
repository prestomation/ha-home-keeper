// Maps a PR's changed files back to the generated documentation pages they
// affect, and renders a Markdown list of deep links into the PR preview build.
// Used by `.github/workflows/docs-preview.yml` to post a sticky comment listing
// exactly which doc pages changed.
//
// The canonical → page mapping lives in `doc-map.mjs` (shared with sync-docs so
// the two never drift). Every source is one file mapping to one page, User Guide
// pages included, so only the pages a PR actually touched are linked.
//
// The pure functions below are exported for unit testing; the file only touches
// the filesystem / env when run directly as a script.
import {pathToFileURL} from 'node:url';
import {
  USER_SECTIONS,
  DEV_DOCS,
  GENERATED_DEV_PAGES,
  guideFile,
  guideRoute,
} from './doc-map.mjs';

// Hidden marker so the workflow can find & update its own sticky comment.
export const COMMENT_MARKER = '<!-- doc-preview-changed-pages -->';

// Canonical/hand-authored sources that map 1:1 to a single page route.
const STATIC_PAGES = {
  'CHANGELOG.md': {title: 'Release Notes', route: '/docs/release-notes'},
  // Hand-authored pages under website/ (see website/README.md).
  'website/docs/intro.md': {title: 'Introduction', route: '/docs/intro'},
  'website/src/pages/index.tsx': {title: 'Home (landing page)', route: '/'},
  // Authored User Guide pages, in sidebar order.
  ...Object.fromEntries(
    USER_SECTIONS.map((spec) => [guideFile(spec), {title: spec.title, route: guideRoute(spec)}]),
  ),
  // Developer Guide docs copied 1:1; the served route drops the `.md` that
  // sync-docs.mjs writes as the filename under website/developer/.
  ...Object.fromEntries(
    DEV_DOCS.map((d) => [
      d.file,
      {title: d.title, route: `/developer/${d.out.replace(/\.md$/, '')}`},
    ]),
  ),
  // Generated Developer Guide pages have no canonical Markdown file, so they are
  // keyed on the repo files they are generated *from*. Touching a service or an
  // event changes the API reference just as surely as editing a doc would, and
  // the comment should say so.
  ...Object.fromEntries(
    GENERATED_DEV_PAGES.flatMap((page) =>
      page.sources.map((source) => [source, {title: page.title, route: page.route}]),
    ),
  ),
};

// Resolve the set of affected pages ({title, route}) from the PR's changed files.
// Output is de-duplicated and ordered: User Guide pages first (in sidebar order),
// then the rest.
export function pagesForChanges({changedFiles}) {
  const pages = [];
  const seen = new Set();
  const add = (title, route) => {
    if (seen.has(route)) return;
    seen.add(route);
    pages.push({title, route});
  };

  const changed = new Set(changedFiles);
  for (const spec of USER_SECTIONS) {
    if (changed.has(guideFile(spec))) add(spec.title, guideRoute(spec));
  }

  for (const file of changedFiles) {
    const page = STATIC_PAGES[file];
    if (page) add(page.title, page.route);
  }

  return pages;
}

// Render the sticky-comment body. Always includes the marker so an existing
// comment can be updated to reflect the current state (including "none").
export function renderComment(pages, previewBaseUrl) {
  const base = (previewBaseUrl ?? '').replace(/\/+$/, '');
  const lines = [COMMENT_MARKER, ''];
  if (pages.length) {
    lines.push('### 📄 Documentation pages changed in this PR');
    lines.push('');
    lines.push('Preview the rendered pages you touched:');
    lines.push('');
    for (const p of pages) lines.push(`- [${p.title}](${base}${p.route})`);
  } else {
    lines.push('_No documentation pages changed in this PR._');
  }
  return lines.join('\n') + '\n';
}

// ---------------------------------------------------------------------------
// CLI entry — reads the PR context from the environment and prints the comment
// body to stdout. Inputs:
//   CHANGED_FILES     newline-separated repo-relative paths changed in the PR
//   PREVIEW_BASE_URL  base URL of the deployed PR preview
// ---------------------------------------------------------------------------
async function main() {
  const changedFiles = (process.env.CHANGED_FILES ?? '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);

  const pages = pagesForChanges({changedFiles});
  process.stdout.write(renderComment(pages, process.env.PREVIEW_BASE_URL));
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  await main();
}
