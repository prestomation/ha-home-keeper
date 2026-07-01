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
  {h: 'Logging completions (note, cost, photo, who)', slug: 'completions', title: 'Logging completions', label: 'Completions'},
  {h: 'Condition-driven (triggered) tasks', slug: 'triggered-tasks', title: 'Triggered tasks', label: 'Triggered tasks'},
  {h: 'Sensor-based tasks (usage meters & thresholds)', slug: 'sensor-tasks', title: 'Sensor-based tasks', label: 'Sensor-based tasks'},
  {h: 'Settings', slug: 'settings', title: 'Settings'},
  {h: 'Profiles — saved filters you reuse everywhere', slug: 'profiles', title: 'Profiles', label: 'Profiles'},
  {h: 'Notifications — actionable reminders on your phone', slug: 'notifications', title: 'Notifications', label: 'Notifications'},
  {h: 'Dashboard task card', slug: 'dashboard-card', title: 'Dashboard card', label: 'Dashboard card'},
  {h: 'Appliances & virtual devices', slug: 'appliances', title: 'Appliances', label: 'Appliances'},
  {h: 'Services', slug: 'services', title: 'Services'},
  {h: 'Events & automations', slug: 'events', title: 'Events & automations', label: 'Events'},
  {h: 'Integrations', slug: 'integrations', title: 'Integrations'},
  {h: 'Localization', slug: 'localization', title: 'Localization'},
];

// Standalone canonical docs copied 1:1 into the Developer Guide. `out` is the
// generated filename under `website/developer/`; the served route drops `.md`.
export const DEV_DOCS = [
  {file: 'docs/INTEGRATING.md', out: 'integrating.md', title: 'Integrating with Home Keeper', label: 'Integrating', pos: 1},
  {file: 'docs/GLUE_INTEGRATIONS.md', out: 'glue-integrations.md', title: 'Glue integrations', label: 'Glue integrations', pos: 2},
  {file: 'docs/EVENTS.md', out: 'events.md', title: 'Events reference', label: 'Events', pos: 3},
  {file: 'docs/DESIGN.md', out: 'architecture.md', title: 'Architecture', label: 'Architecture', pos: 4},
];
