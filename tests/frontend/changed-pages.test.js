import {describe, it, expect} from 'vitest';
import {
  COMMENT_MARKER,
  readmeChangedHeadings,
  pagesForChanges,
  renderComment,
} from '../../website/scripts/changed-pages.mjs';
import {DEV_DOCS, DOC_ROUTES} from '../../website/scripts/doc-map.mjs';

const README = `# Home Keeper

Intro preamble paragraph.

## Features at a glance

Feature list here.

## Settings

Settings body.

## Development

Contributor-only notes.
`;

describe('readmeChangedHeadings', () => {
  it('flags only the section whose body changed', () => {
    const head = README.replace('Settings body.', 'Settings body, edited.');
    expect(readmeChangedHeadings(README, head)).toEqual(['Settings']);
  });

  it('flags a newly added section', () => {
    const head = README + '\n## Localization\n\nNew section.\n';
    expect(readmeChangedHeadings(README, head)).toEqual(['Localization']);
  });

  it('ignores changes confined to the preamble', () => {
    const head = README.replace('Intro preamble paragraph.', 'Different intro.');
    expect(readmeChangedHeadings(README, head)).toEqual([]);
  });

  it('returns nothing when the body is identical', () => {
    expect(readmeChangedHeadings(README, README)).toEqual([]);
  });

  it('treats every section as changed when there is no base', () => {
    expect(readmeChangedHeadings('', README)).toEqual([
      'Features at a glance',
      'Settings',
      'Development',
    ]);
  });
});

describe('pagesForChanges', () => {
  it('maps changed README sections to their User Guide routes in sidebar order', () => {
    const pages = pagesForChanges({
      changedFiles: ['README.md'],
      changedReadmeHeadings: ['Settings', 'Features at a glance'],
    });
    expect(pages).toEqual([
      {title: 'Features', route: '/docs/guide/features'},
      {title: 'Settings', route: '/docs/guide/settings'},
    ]);
  });

  it('does not link README sections that are not published (e.g. Development)', () => {
    const pages = pagesForChanges({
      changedFiles: ['README.md'],
      changedReadmeHeadings: ['Development'],
    });
    expect(pages).toEqual([]);
  });

  it('maps developer docs, changelog and hand-authored pages', () => {
    const pages = pagesForChanges({
      changedFiles: [
        'docs/INTEGRATING.md',
        'docs/EVENTS.md',
        'CHANGELOG.md',
        'website/docs/intro.md',
        'website/src/pages/index.tsx',
      ],
    });
    expect(pages).toEqual([
      {title: 'Integrating with Home Keeper', route: '/developer/integrating'},
      {title: 'Events reference', route: '/developer/events'},
      {title: 'Release Notes', route: '/docs/release-notes'},
      {title: 'Introduction', route: '/docs/intro'},
      {title: 'Home (landing page)', route: '/'},
    ]);
  });

  it('maps the API reference\u2019s generation sources to its route', () => {
    // The page has no canonical Markdown file, so a PR that only adds a service
    // or an event would otherwise show no changed doc page at all.
    for (const source of [
      'custom_components/home_keeper/api_surface.py',
      'custom_components/home_keeper/services.yaml',
      'custom_components/home_keeper/strings.json',
    ]) {
      expect(pagesForChanges({changedFiles: [source]})).toEqual([
        {title: 'API reference', route: '/developer/api'},
      ]);
    }
  });

  it('ignores files with no page mapping', () => {
    expect(
      pagesForChanges({changedFiles: ['custom_components/home_keeper/store.py']}),
    ).toEqual([]);
  });

  it('de-duplicates repeated routes', () => {
    const pages = pagesForChanges({
      changedFiles: ['docs/EVENTS.md', 'docs/EVENTS.md'],
    });
    expect(pages).toEqual([
      {title: 'Events reference', route: '/developer/events'},
    ]);
  });
});

describe('renderComment', () => {
  const base = 'https://prestomation.github.io/ha-home-keeper/pr-preview/pr-9/';

  it('renders a marked, bulleted list with absolute preview URLs', () => {
    const body = renderComment(
      [{title: 'Settings', route: '/docs/guide/settings'}],
      base,
    );
    expect(body).toContain(COMMENT_MARKER);
    expect(body).toContain(
      '- [Settings](https://prestomation.github.io/ha-home-keeper/pr-preview/pr-9/docs/guide/settings)',
    );
  });

  it('collapses a trailing slash so routes are not doubled', () => {
    const body = renderComment([{title: 'Home', route: '/'}], base);
    expect(body).toContain(
      '- [Home](https://prestomation.github.io/ha-home-keeper/pr-preview/pr-9/)',
    );
    expect(body).not.toContain('pr-9//');
  });

  it('still emits the marker when nothing changed', () => {
    const body = renderComment([], base);
    expect(body).toContain(COMMENT_MARKER);
    expect(body).toContain('No documentation pages changed');
  });
});

describe('DOC_ROUTES', () => {
  it('has a route for every published Developer Guide doc', () => {
    // A doc in DEV_DOCS is served on this site, so a relative link to it from
    // another canonical doc should resolve here — not rewrite to a GitHub blob
    // URL. GLUE_INTEGRATIONS.md was published for months without a route, and
    // every link to it left the site.
    const missing = DEV_DOCS.map((d) => d.file).filter((f) => !DOC_ROUTES[f]);
    expect(missing).toEqual([]);
  });

  it('routes match the page each doc is generated into', () => {
    for (const doc of DEV_DOCS) {
      expect(DOC_ROUTES[doc.file]).toBe(
        `/developer/${doc.out.replace(/\.md$/, '')}`,
      );
    }
  });
});
