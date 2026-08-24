// Shared, pure mapping data + helpers describing how the canonical Markdown
// sources map onto the generated Docusaurus pages. Imported by both
// `sync-docs.mjs` (which renders the pages) and `changed-pages.mjs` (which maps
// a PR's changed files back to the pages they affect). Keep it side-effect free
// so it can be imported anywhere, including unit tests.

// Split Markdown into a preamble and `## ` sections, ignoring fenced code.
export function splitByH2(md) {
  const lines = md.split('\n');
  const preamble = [];
  const sections = [];
  let current = null;
  let inFence = false;
  let fence = '';
  for (const line of lines) {
    const fenceMatch = line.match(/^(```|~~~)/);
    if (fenceMatch) {
      if (!inFence) {
        inFence = true;
        fence = fenceMatch[1];
      } else if (line.startsWith(fence)) {
        inFence = false;
      }
    }
    const h2 = !inFence && line.match(/^## (.+)$/);
    if (h2) {
      current = {title: h2[1].trim(), body: []};
      sections.push(current);
    } else if (current) {
      current.body.push(line);
    } else {
      preamble.push(line);
    }
  }
  return {preamble: preamble.join('\n'), sections};
}

// Ordered set of README sections to publish. Sections not listed (e.g.
// "Integrating with Home Keeper", "Quality scale", "Development") are skipped —
// they belong to the Developer Guide or only make sense in the repo.
export const USER_SECTIONS = [
  {h: 'Features at a glance', slug: 'features', title: 'Features', label: 'Features'},
  {h: 'Installation', slug: 'installation', title: 'Installation'},
  {h: 'Concepts', slug: 'concepts', title: 'Core concepts', label: 'Concepts'},
  {h: 'One-off (do-once) tasks', slug: 'one-off-tasks', title: 'One-off tasks', label: 'One-off tasks'},
  {h: 'Notes are Markdown', slug: 'markdown-notes', title: 'Markdown notes', label: 'Markdown notes'},
  {h: 'Logging completions (note, cost, photo, who)', slug: 'completions', title: 'Logging completions', label: 'Completions'},
  {h: 'Condition-driven (triggered) tasks', slug: 'triggered-tasks', title: 'Triggered tasks', label: 'Triggered tasks'},
  {h: 'Sensor-based tasks (usage meters, thresholds & states)', slug: 'sensor-tasks', title: 'Sensor-based tasks', label: 'Sensor-based tasks'},
  {h: 'Settings', slug: 'settings', title: 'Settings'},
  {h: 'Profiles (saved filters you reuse everywhere)', slug: 'profiles', title: 'Profiles', label: 'Profiles'},
  {h: 'Notifications (actionable reminders on your phone)', slug: 'notifications', title: 'Notifications', label: 'Notifications'},
  {h: 'Dashboard task card', slug: 'dashboard-card', title: 'Dashboard card', label: 'Dashboard card'},
  {h: 'Appliances & virtual devices', slug: 'appliances', title: 'Appliances', label: 'Appliances'},
  {h: 'Services', slug: 'services', title: 'Services'},
  {h: 'Events & automations', slug: 'events', title: 'Events & automations', label: 'Events'},
  {h: 'Integrations', slug: 'integrations', title: 'Integrations'},
  {h: 'Localization', slug: 'localization', title: 'Localization'},
  {h: 'Upgrading to Home Assistant 2026.8', slug: 'migration-2026-8', title: 'Upgrading to Home Assistant 2026.8', label: 'HA 2026.8 migration'},
];

// Standalone canonical docs copied 1:1 into the Developer Guide. `out` is the
// generated filename under `website/developer/`; the served route drops `.md`.
export const DEV_DOCS = [
  {file: 'docs/INTEGRATING.md', out: 'integrating.md', title: 'Integrating with Home Keeper', label: 'Integrating', pos: 1},
  {file: 'docs/GLUE_INTEGRATIONS.md', out: 'glue-integrations.md', title: 'Glue integrations', label: 'Glue integrations', pos: 2},
  {file: 'docs/EVENTS.md', out: 'events.md', title: 'Events reference', label: 'Events', pos: 3},
  {file: 'docs/DESIGN.md', out: 'architecture.md', title: 'Architecture', label: 'Architecture', pos: 4},
  {file: 'docs/SECURITY.md', out: 'security.md', title: 'Security model', label: 'Security', pos: 5},
];

// README same-page anchors that now live on their own User Guide pages.
export const ANCHOR_ROUTES = {
  '#one-off-do-once-tasks': '/docs/guide/one-off-tasks',
  '#sensor-based-tasks-usage-meters-thresholds--states': '/docs/guide/sensor-tasks',
  '#appliances--virtual-devices': '/docs/guide/appliances',
  '#notes-are-markdown': '/docs/guide/markdown-notes',
  // The "Companions" subsection lives under the Settings section (→ settings page).
  '#companions': '/docs/guide/settings#companions',
  '#notifications-actionable-reminders-on-your-phone': '/docs/guide/notifications',
  '#profiles-saved-filters-you-reuse-everywhere': '/docs/guide/profiles',
  '#dashboard-task-card': '/docs/guide/dashboard-card',
  // The "Link a task to a consumable" subsection lives under the Sensor-based tasks
  // section (→ sensor-tasks page); "Parts & wear items" under Appliances; and
  // "Sync problem binary sensors" under Condition-driven tasks (→ triggered-tasks),
  // which the Sensor-based tasks page links across to when contrasting the two.
  '#link-a-task-to-a-consumable-auto-reorder':
    '/docs/guide/sensor-tasks#link-a-task-to-a-consumable-auto-reorder',
  '#parts--wear-items': '/docs/guide/appliances#parts--wear-items',
  // Auto-buy and its shopping-list mirror are subsections of "Parts & wear items"
  // (→ appliances page); the Settings and Events sections both link across to them.
  '#auto-create-a-buy-task-when-a-part-runs-low':
    '/docs/guide/appliances#auto-create-a-buy-task-when-a-part-runs-low',
  '#send-buy-reminders-to-your-shopping-list':
    '/docs/guide/appliances#send-buy-reminders-to-your-shopping-list',
  // So is measured stock, which the consumable-link section (→ sensor-tasks page)
  // points at when explaining how much a completion draws down.
  '#stock-you-measure-rather-than-count':
    '/docs/guide/appliances#stock-you-measure-rather-than-count',
  '#sync-problem-binary-sensors-as-tasks':
    '/docs/guide/triggered-tasks#sync-problem-binary-sensors-as-tasks',
};


// GitHub's heading-slug rules, which Docusaurus also follows: lowercase, drop
// punctuation, turn each remaining space into a hyphen. Two spaces left behind by a
// dropped "&" therefore become "--", which is why the real anchors read
// `#parts--wear-items`.
export function slugify(heading) {
  return heading
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/\s/g, '-');
}

// Drop fenced code blocks. A `](#anchor)` inside one is shown literally, never
// linked, so it must not be mistaken for a link the site has to resolve.
function stripFences(lines) {
  const kept = [];
  let inFence = false;
  let fence = '';
  for (const line of lines) {
    const fenceMatch = line.match(/^(```|~~~)/);
    if (fenceMatch) {
      if (!inFence) {
        inFence = true;
        fence = fenceMatch[1];
      } else if (line.startsWith(fence)) {
        inFence = false;
      }
      continue;
    }
    if (!inFence) kept.push(line);
  }
  return kept;
}

// Every heading in `md`, paired with the `## ` section it sits under.
//
// Repeated headings get GitHub's disambiguating suffix: the second "Installation"
// anchors at `#installation-1`, the third at `#installation-2`. Without that, a
// perfectly good `](#installation-1)` link would be reported as pointing at nothing,
// and a guard that cries wolf is a guard someone turns off.
function headingSections(md) {
  const {sections} = splitByH2(md);
  const found = new Map();
  const seen = new Map();
  const add = (heading, sectionTitle) => {
    const base = slugify(heading);
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    found.set(count === 0 ? base : `${base}-${count}`, sectionTitle);
  };
  for (const section of sections) {
    add(section.title, section.title);
    for (const line of stripFences(section.body)) {
      const heading = line.match(/^#{3,6} (.+)$/);
      if (heading) add(heading[1].trim(), section.title);
    }
  }
  return found;
}

// Every `#anchor` a section's prose points at. Inline `[text](#a)` is the form the
// README actually uses; reference definitions (`[ref]: #a`) and raw `<a href="#a">`
// are checked too, so the guard doesn't quietly ignore a link written another way.
// A link split across a newline is the one form still missed.
function anchorsIn(prose) {
  const patterns = [
    /\]\((#[^)\s]+)\)/g, // [text](#anchor)
    /^\s*\[[^\]]+\]:\s*(#\S+)/gm, // [ref]: #anchor
    /<a\s[^>]*href=["'](#[^"']+)["']/gi, // <a href="#anchor">
  ];
  return patterns.flatMap((re) => [...prose.matchAll(re)].map((m) => m[1]));
}

/**
 * README same-page anchors the generated site would break on.
 *
 * The User Guide splits README by `## ` section, so a `](#some-heading)` link only
 * survives when its target heading is in the *same* section — otherwise the anchor
 * lands on the wrong page and Docusaurus fails the build on a broken link, unless
 * `ANCHOR_ROUTES` redirects it. That failure only ever shows up in a full site build,
 * which is a slow way to learn you forgot a one-line map entry.
 *
 * Returns `{anchor, from, reason}` for each problem: `unknown` when no heading in
 * README matches at all, `cross-section` when the link leaves its own page with no
 * route. Anchors in sections the guide doesn't publish are ignored — they never
 * reach the site, and so is anything inside a fenced code block.
 *
 * This narrows the window, it does not close it: a link whose `](` and `#anchor` sit
 * on different lines still slips past (see :func:`anchorsIn`), and the Docusaurus
 * build stays the backstop.
 */
export function unroutedReadmeAnchors(md, anchorRoutes) {
  const published = new Set(USER_SECTIONS.map((s) => s.h));
  const owners = headingSections(md);
  const {sections} = splitByH2(md);
  const issues = [];
  for (const section of sections) {
    if (!published.has(section.title)) continue;
    const prose = stripFences(section.body).join('\n');
    for (const anchor of anchorsIn(prose)) {
      if (anchorRoutes[anchor]) continue;
      const owner = owners.get(anchor.slice(1));
      if (owner === undefined) {
        issues.push({anchor, from: section.title, reason: 'unknown'});
      } else if (owner !== section.title) {
        issues.push({anchor, from: section.title, reason: 'cross-section'});
      }
    }
  }
  return issues;
}
