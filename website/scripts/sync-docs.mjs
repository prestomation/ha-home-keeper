// Generates Docusaurus pages from the canonical Markdown sources so docs are
// authored once and never duplicated:
//
//   README.md            -> website/docs/guide/*.md   (User Guide, split by ## section)
//   CHANGELOG.md         -> website/docs/release-notes.md
//   docs/INTEGRATING.md  -> website/developer/integrating.md
//   docs/EVENTS.md       -> website/developer/events.md
//   docs/DESIGN.md       -> website/developer/architecture.md
//
// The generated trees (website/docs/guide, website/developer) are gitignored; the
// canonical files stay the single source of truth. Run via `npm run sync` (wired
// into prestart/prebuild). Re-run whenever the source docs change.
import {readFile, writeFile, mkdir, rm} from 'node:fs/promises';
import {dirname, resolve} from 'node:path';
import {posix} from 'node:path';
import {fileURLToPath} from 'node:url';
import {splitByH2, USER_SECTIONS, DEV_DOCS} from './doc-map.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const website = resolve(here, '..');
const repo = resolve(website, '..');
const REPO_URL = 'https://github.com/prestomation/ha-home-keeper';

// ---------------------------------------------------------------------------
// Link / image rewriting
// ---------------------------------------------------------------------------

// In-repo docs that have a home on this site.
const DOC_ROUTES = {
  'docs/INTEGRATING.md': '/developer/integrating',
  'docs/EVENTS.md': '/developer/events',
  'docs/DESIGN.md': '/developer/architecture',
};

// README same-page anchors that now live on their own User Guide pages.
const ANCHOR_ROUTES = {
  '#one-off-do-once-tasks': '/docs/guide/one-off-tasks',
  '#sensor-based-tasks-usage-meters--thresholds': '/docs/guide/sensor-tasks',
  '#appliances--virtual-devices': '/docs/guide/appliances',
  // The "Companions" subsection lives under the Settings section (→ settings page).
  '#companions': '/docs/guide/settings#companions',
  '#notifications--actionable-reminders-on-your-phone': '/docs/guide/notifications',
  '#profiles--saved-filters-you-reuse-everywhere': '/docs/guide/profiles',
  // The "Link a task to a consumable" subsection lives under the Sensor-based tasks
  // section (→ sensor-tasks page); "Parts & wear items" under Appliances.
  '#link-a-task-to-a-consumable-auto-reorder':
    '/docs/guide/sensor-tasks#link-a-task-to-a-consumable-auto-reorder',
  '#parts--wear-items': '/docs/guide/appliances#parts--wear-items',
};

// Rewrite every Markdown link/image target. `sourceDir` is the canonical file's
// directory relative to the repo root, so relative links resolve correctly.
function rewriteLinks(md, sourceDir) {
  return md.replace(/\]\(([^)]+)\)/g, (whole, url) => {
    const hashIndex = url.indexOf('#');
    const path = hashIndex === -1 ? url : url.slice(0, hashIndex);
    const hash = hashIndex === -1 ? '' : url.slice(hashIndex);

    // Leave external and already-site-absolute links alone.
    if (/^(https?:|mailto:|\/img\/|\/docs\/|\/developer\/)/.test(url)) {
      return whole;
    }

    // Pure same-page anchor -> the page that section became (or leave as-is).
    if (path === '') {
      return ANCHOR_ROUTES[hash] ? `](${ANCHOR_ROUTES[hash]})` : whole;
    }

    // Resolve the relative target to a repo-root-relative path.
    const rel = posix.normalize(posix.join(sourceDir, path)).replace(/^\.\//, '');

    // Screenshots -> the mirrored static tree (see sync-assets.mjs).
    const img = rel.match(/(?:^|\/)images\/(.+)$/);
    if (img) {
      return `](/img/screenshots/${img[1]})`;
    }

    // A doc that has a site route.
    if (DOC_ROUTES[rel]) {
      return `](${DOC_ROUTES[rel]}${hash})`;
    }

    // Anything else in the repo -> an absolute GitHub link.
    return `](${REPO_URL}/blob/main/${rel}${hash})`;
  });
}

function frontmatter({title, label, position}) {
  const lines = ['---', `title: ${JSON.stringify(title)}`];
  if (label) lines.push(`sidebar_label: ${JSON.stringify(label)}`);
  lines.push(`sidebar_position: ${position}`);
  // Parse as CommonMark, not MDX, so literal { } and < > in the prose/tables
  // (e.g. "Managed by {name}") aren't treated as JSX.
  lines.push('format: md', '---', '');
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// User Guide — README.md split by section
// ---------------------------------------------------------------------------

async function buildUserGuide() {
  const md = await readFile(resolve(repo, 'README.md'), 'utf8');
  const {sections} = splitByH2(md);
  const byTitle = new Map(sections.map((s) => [s.title, s]));
  const outDir = resolve(website, 'docs', 'guide');
  await rm(outDir, {recursive: true, force: true});
  await mkdir(outDir, {recursive: true});

  let position = 0;
  for (const spec of USER_SECTIONS) {
    const section = byTitle.get(spec.h);
    if (!section) {
      console.warn(`[sync-docs] README section not found: "${spec.h}"`);
      continue;
    }
    position += 1;
    const body = rewriteLinks(section.body.join('\n'), '').trim();
    const page =
      frontmatter({title: spec.title, label: spec.label, position}) + body + '\n';
    await writeFile(resolve(outDir, `${spec.slug}.md`), page);
  }
  // Category metadata so the autogenerated sidebar groups these under "Guide".
  await writeFile(
    resolve(outDir, '_category_.json'),
    JSON.stringify({label: 'Guide', collapsed: false}, null, 2) + '\n',
  );
  console.log(`[sync-docs] wrote ${position} User Guide pages`);
}

// ---------------------------------------------------------------------------
// Developer Guide — standalone docs copied 1:1
// ---------------------------------------------------------------------------

async function buildDeveloperGuide() {
  const outDir = resolve(website, 'developer');
  await rm(outDir, {recursive: true, force: true});
  await mkdir(outDir, {recursive: true});

  for (const spec of DEV_DOCS) {
    const raw = await readFile(resolve(repo, spec.file), 'utf8');
    // Drop the leading H1 — the frontmatter title renders it.
    const withoutH1 = raw.replace(/^#\s+.+\n+/, '');
    const body = rewriteLinks(withoutH1, posix.dirname(spec.file)).trim();
    const page =
      frontmatter({title: spec.title, label: spec.label, position: spec.pos}) +
      body +
      '\n';
    await writeFile(resolve(outDir, spec.out), page);
  }
  console.log(`[sync-docs] wrote ${DEV_DOCS.length} Developer Guide pages`);
}

// ---------------------------------------------------------------------------
// Release Notes — CHANGELOG.md copied as a single page
// ---------------------------------------------------------------------------

async function buildReleaseNotes() {
  const raw = await readFile(resolve(repo, 'CHANGELOG.md'), 'utf8');
  // Drop the leading H1 — frontmatter title renders it.
  const withoutH1 = raw.replace(/^#\s+.+\n+/, '');
  const body = rewriteLinks(withoutH1, '').trim();
  const page =
    frontmatter({title: 'Release Notes', label: 'Release Notes', position: 99}) +
    body +
    '\n';
  await writeFile(resolve(website, 'docs', 'release-notes.md'), page);
  console.log('[sync-docs] wrote Release Notes page');
}

await buildUserGuide();
await buildDeveloperGuide();
await buildReleaseNotes();
