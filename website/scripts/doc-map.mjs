// Shared mapping data + helpers describing how the canonical Markdown sources map
// onto the generated Docusaurus pages. Imported by both `sync-docs.mjs` (which
// renders the pages) and `changed-pages.mjs` (which maps a PR's changed files back
// to the pages they affect). Keep it side-effect free at import time so it can be
// imported anywhere, including unit tests. `guideFilesOnDisk()` reads the
// filesystem, but only when called.
import {readdirSync} from 'node:fs';
import {posix} from 'node:path';

// Ordered set of User Guide pages. Each entry names one authored file at
// `docs/guide/<group>/<slug>.md`; the array order sets the sidebar position.
// Every file under `docs/guide/` must have an entry here and every entry must have
// a file: `sync-docs.mjs` fails the build otherwise, so a new page cannot silently
// stay off the site and a listed page cannot silently vanish.
export const USER_SECTIONS = [
  {slug: 'features', title: 'Features', label: 'Features', group: 'start'},
  {slug: 'installation', title: 'Installation', group: 'start'},
  {slug: 'concepts', title: 'Core concepts', label: 'Concepts', group: 'start'},
  {slug: 'panel', title: 'The panel', label: 'The panel', group: 'start'},
  {slug: 'one-off-tasks', title: 'One-off tasks', label: 'One-off tasks', group: 'tasks'},
  {slug: 'markdown-notes', title: 'Markdown notes', label: 'Markdown notes', group: 'tasks'},
  {slug: 'completions', title: 'Logging completions', label: 'Completions', group: 'tasks'},
  {slug: 'snooze-and-skip', title: 'Snooze, skip and due today', label: 'Snooze, skip & due today', group: 'tasks'},
  {slug: 'nfc-tags', title: 'NFC and RFID tags', label: 'NFC and RFID tags', group: 'tasks'},
  {slug: 'triggered-tasks', title: 'Triggered tasks', label: 'Triggered tasks', group: 'tasks'},
  {slug: 'sensor-tasks', title: 'Sensor-based tasks', label: 'Sensor-based tasks', group: 'tasks'},
  {slug: 'appliances', title: 'Appliances', label: 'Appliances', group: 'appliances'},
  {slug: 'profiles', title: 'Profiles', label: 'Profiles', group: 'views'},
  {slug: 'todo-sync', title: 'To-do list sync', label: 'To-do list sync', group: 'views'},
  {slug: 'notifications', title: 'Notifications', label: 'Notifications', group: 'views'},
  {slug: 'dashboard-card', title: 'Dashboard card', label: 'Dashboard card', group: 'views'},
  {slug: 'settings', title: 'Settings', group: 'views'},
  {slug: 'import-export', title: 'Import and export', label: 'Import and export', group: 'automation'},
  {slug: 'services', title: 'Services', group: 'automation'},
  {slug: 'events', title: 'Events & automations', label: 'Events', group: 'automation'},
  {slug: 'integrations', title: 'Integrations', group: 'automation'},
  {slug: 'localization', title: 'Localization', group: 'reference'},
  {
    slug: 'migration-2026-8',
    title: 'Upgrading to Home Assistant 2026.8',
    label: 'HA 2026.8 migration',
    group: 'reference',
  },
  {slug: 'quality-scale', title: 'Quality scale', group: 'reference'},
];

// Sidebar categories for the User Guide, in order. Each USER_SECTIONS entry names
// one by `group`. Pages keep their `/docs/guide/<slug>` URL; the group only sets
// the directory and the sidebar category.
export const GUIDE_GROUPS = [
  {dir: 'start', label: 'Start'},
  {dir: 'tasks', label: 'Tasks'},
  {dir: 'appliances', label: 'Appliances'},
  {dir: 'views', label: 'Views and delivery'},
  {dir: 'automation', label: 'Automate and extend'},
  {dir: 'reference', label: 'Reference'},
];

// Where a User Guide page is authored, relative to the repository root.
export function guideFile(spec) {
  return `docs/guide/${spec.group}/${spec.slug}.md`;
}

// The route a User Guide page is served at.
export function guideRoute(spec) {
  return `/docs/guide/${spec.slug}`;
}

/**
 * Every authored guide file, relative to `repoRoot`, in POSIX form and sorted.
 *
 * Hand-rolled rather than `readdir(…, {recursive: true})`, which needs Node 20.1,
 * or `Dirent.parentPath`, which needs Node 21.4 — `website/package.json` declares
 * `engines.node >= 18`. The generator and `tests/frontend/doc-anchors.test.js` both
 * call this, so the drift guard cannot pass in the test and fail in the build.
 */
export function guideFilesOnDisk(repoRoot, dir = 'docs/guide') {
  const files = [];
  for (const entry of readdirSync(posix.join(repoRoot, dir), {withFileTypes: true})) {
    const rel = posix.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...guideFilesOnDisk(repoRoot, rel));
    else if (entry.name.endsWith('.md')) files.push(rel);
  }
  return files.sort();
}

// Authored guide file -> the route its page is served at, so a relative link
// between two guide pages becomes an on-site link rather than a GitHub blob URL.
export const GUIDE_ROUTES = Object.fromEntries(
  USER_SECTIONS.map((spec) => [guideFile(spec), guideRoute(spec)]),
);

/**
 * Disagreements between `USER_SECTIONS` and the files on disk.
 *
 * `files` is every `docs/guide/**\/*.md` path, relative to the repository root.
 * Returns `{unlisted, missing}`: files with no entry, and entries with no file.
 * `sync-docs.mjs` fails the build on either, which is what stops a new page from
 * being written and never reaching the sidebar.
 */
export function guideFileDrift(files, userSections = USER_SECTIONS) {
  const listed = new Set(userSections.map(guideFile));
  const present = new Set(files);
  return {
    unlisted: files.filter((f) => !listed.has(f)),
    missing: userSections.map(guideFile).filter((f) => !present.has(f)),
  };
}

// Standalone canonical docs copied 1:1 into the Developer Guide. `out` is the
// generated filename under `website/developer/`; the served route drops `.md`.
// Position 2 is left to the generated API reference below.
export const DEV_DOCS = [
  {file: 'docs/INTEGRATING.md', out: 'integrating.md', title: 'Integrating with Home Keeper', label: 'Integrating', pos: 1},
  {file: 'docs/GLUE_INTEGRATIONS.md', out: 'glue-integrations.md', title: 'Glue integrations', label: 'Glue integrations', pos: 3},
  {file: 'docs/EVENTS.md', out: 'events.md', title: 'Events reference', label: 'Events', pos: 4},
  {file: 'docs/DESIGN.md', out: 'architecture.md', title: 'Architecture', label: 'Architecture', pos: 5},
  {file: 'docs/SECURITY.md', out: 'security.md', title: 'Security model', label: 'Security', pos: 6},
];

// Developer Guide pages with no canonical Markdown source: `ci/generate_api_docs.py`
// renders them straight into `website/developer/` after sync-docs.mjs has cleared it.
// `sources` are the repo files the page is generated *from*, so a PR that only
// changes a service or an event still shows up in the changed-pages comment.
// tests/unit/test_generate_api_docs.py pins these values to the generator's own
// frontmatter — the two are in different languages and can't import each other.
export const GENERATED_DEV_PAGES = [
  {
    out: 'api.md',
    route: '/developer/api',
    title: 'API reference',
    pos: 2,
    sources: [
      'custom_components/home_keeper/api_surface.py',
      'custom_components/home_keeper/services.yaml',
      'custom_components/home_keeper/strings.json',
    ],
  },
];

// In-repo docs that have a home on this site, so a relative link between two
// canonical docs becomes an on-site link rather than a GitHub blob URL. Every
// DEV_DOCS entry needs a row here; tests/frontend/changed-pages.test.js checks that,
// because GLUE_INTEGRATIONS.md was published for months with its links still
// pointing off-site.
export const DOC_ROUTES = {
  'docs/INTEGRATING.md': '/developer/integrating',
  'docs/GLUE_INTEGRATIONS.md': '/developer/glue-integrations',
  'docs/EVENTS.md': '/developer/events',
  'docs/DESIGN.md': '/developer/architecture',
  'docs/SECURITY.md': '/developer/security',
};
