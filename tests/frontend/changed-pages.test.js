import {describe, it, expect} from 'vitest';
import {
  COMMENT_MARKER,
  readmeChangedHeadings,
  pagesForChanges,
  renderComment,
} from '../../website/scripts/changed-pages.mjs';

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
