// Maps a PR's changed files back to the generated documentation pages they
// affect, and renders a Markdown list of deep links into the PR preview build.
// Used by `.github/workflows/docs-preview.yml` to post a sticky comment listing
// exactly which doc pages changed.
//
// The canonical → page mapping lives in `doc-map.mjs` (shared with sync-docs so
// the two never drift). README is section-granular: only the User Guide pages
// whose `##` section actually changed are linked, not every guide page.
//
// The pure functions below are exported for unit testing; the file only touches
// the filesystem / env when run directly as a script.
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {splitByH2, USER_SECTIONS, DEV_DOCS} from './doc-map.mjs';

// Hidden marker so the workflow can find & update its own sticky comment.
export const COMMENT_MARKER = '<!-- doc-preview-changed-pages -->';

// Canonical/hand-authored sources that map 1:1 to a single page route.
// (README is handled separately — it fans out to many section pages.)
const STATIC_PAGES = {
  'CHANGELOG.md': {title: 'Release Notes', route: '/docs/release-notes'},
  // Hand-authored pages under website/ (see website/README.md).
  'website/docs/intro.md': {title: 'Introduction', route: '/docs/intro'},
  'website/src/pages/index.tsx': {title: 'Home (landing page)', route: '/'},
  // Developer Guide docs copied 1:1; the served route drops the `.md` that
  // sync-docs.mjs writes as the filename under website/developer/.
  ...Object.fromEntries(
    DEV_DOCS.map((d) => [
      d.file,
      {title: d.title, route: `/developer/${d.out.replace(/\.md$/, '')}`},
    ]),
  ),
};

// Given the README before/after, return the list of `##` section headings whose
// body changed (or were added). A missing/empty base (new file) treats every
// section as changed. Section titles are compared by heading text, so inserting
// or reordering a section only flags the ones that actually differ.
//
// Renames are keyed by heading text, exactly like the generator: sync-docs.mjs
// also looks sections up by their exact `## ` text (USER_SECTIONS `h`) and skips
// generating a page whose heading it can't find. So renaming a section without
// updating USER_SECTIONS drops the page from the site *and* from this list in
// lockstep — the two never disagree about what exists to link to.
export function readmeChangedHeadings(baseMd, headMd) {
  const base = new Map(
    splitByH2(baseMd ?? '').sections.map((s) => [s.title, s.body.join('\n')]),
  );
  const changed = [];
  for (const s of splitByH2(headMd).sections) {
    const before = base.get(s.title);
    if (before === undefined || before !== s.body.join('\n')) {
      changed.push(s.title);
    }
  }
  return changed;
}

// Resolve the set of affected pages ({title, route}) from the PR's changed files
// and the README section headings that changed. Output is de-duplicated and
// ordered: README User Guide pages first (in sidebar order), then the rest.
export function pagesForChanges({changedFiles, changedReadmeHeadings = []}) {
  const pages = [];
  const seen = new Set();
  const add = (title, route) => {
    if (seen.has(route)) return;
    seen.add(route);
    pages.push({title, route});
  };

  if (changedFiles.includes('README.md') && changedReadmeHeadings.length) {
    const changedSet = new Set(changedReadmeHeadings);
    for (const spec of USER_SECTIONS) {
      if (changedSet.has(spec.h)) add(spec.title, `/docs/guide/${spec.slug}`);
    }
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
//   README_BASE       path to the base (pre-PR) README.md (optional)
//   README_HEAD       path to the head README.md (default: repo README.md)
//   PREVIEW_BASE_URL  base URL of the deployed PR preview
// ---------------------------------------------------------------------------
async function main() {
  const changedFiles = (process.env.CHANGED_FILES ?? '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);

  let changedReadmeHeadings = [];
  if (changedFiles.includes('README.md')) {
    const headPath = process.env.README_HEAD ?? 'README.md';
    const headMd = await readFile(headPath, 'utf8');
    let baseMd = '';
    if (process.env.README_BASE) {
      baseMd = await readFile(process.env.README_BASE, 'utf8').catch(() => '');
    }
    changedReadmeHeadings = readmeChangedHeadings(baseMd, headMd);
  }

  const pages = pagesForChanges({changedFiles, changedReadmeHeadings});
  process.stdout.write(renderComment(pages, process.env.PREVIEW_BASE_URL));
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  await main();
}
