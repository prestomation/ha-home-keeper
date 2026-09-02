import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {describe, it, expect} from 'vitest';
import {
  ANCHOR_ROUTES,
  USER_SECTIONS,
  UNPUBLISHED_SECTIONS,
  slugify,
  unlistedReadmeSections,
  unroutedReadmeAnchors,
} from '../../website/scripts/doc-map.mjs';

/**
 * The User Guide splits README by `## ` section, so a same-page `](#heading)` link
 * only survives the split when its target is in the same section. Anything crossing
 * a section boundary needs an `ANCHOR_ROUTES` entry, or Docusaurus fails the build
 * on a broken anchor — which is a four-minute CI job away from the one-line map edit
 * that fixes it. This is that check, in milliseconds.
 */

const README = readFileSync(resolve(process.cwd(), 'README.md'), 'utf8');

describe('slugify', () => {
  it('matches the GitHub/Docusaurus heading slug', () => {
    expect(slugify('Stock you measure rather than count')).toBe(
      'stock-you-measure-rather-than-count',
    );
    expect(slugify('One-off (do-once) tasks')).toBe('one-off-do-once-tasks');
    // A dropped "&" leaves two spaces behind, hence the doubled hyphen.
    expect(slugify('Parts & wear items')).toBe('parts--wear-items');
    expect(slugify('Sensor-based tasks (usage meters, thresholds & states)')).toBe(
      'sensor-based-tasks-usage-meters-thresholds--states',
    );
  });
});

describe('README same-page anchors', () => {
  it('every cross-section anchor has a route', () => {
    // A failure names the anchor: add it to ANCHOR_ROUTES in doc-map.mjs, pointing
    // at the guide page whose section owns that heading.
    expect(unroutedReadmeAnchors(README, ANCHOR_ROUTES)).toEqual([]);
  });

  it('flags an anchor that leaves its own page unrouted', () => {
    const md = [
      '## Appliances & virtual devices',
      '',
      '#### Stock you measure rather than count',
      '',
      '## Sensor-based tasks (usage meters, thresholds & states)',
      '',
      'See [measured stock](#stock-you-measure-rather-than-count).',
      '',
    ].join('\n');
    expect(unroutedReadmeAnchors(md, {})).toEqual([
      {
        anchor: '#stock-you-measure-rather-than-count',
        from: 'Sensor-based tasks (usage meters, thresholds & states)',
        reason: 'cross-section',
      },
    ]);
    // With the route in place it is fine again.
    const routed = {
      '#stock-you-measure-rather-than-count':
        '/docs/guide/appliances#stock-you-measure-rather-than-count',
    };
    expect(unroutedReadmeAnchors(md, routed)).toEqual([]);
  });

  it('flags an anchor no heading answers', () => {
    const md = '## Settings\n\nSee [nothing](#no-such-heading).\n';
    expect(unroutedReadmeAnchors(md, {})).toEqual([
      {anchor: '#no-such-heading', from: 'Settings', reason: 'unknown'},
    ]);
  });

  it('allows an anchor pointing within its own section', () => {
    const md = [
      '## Settings',
      '',
      '### Companions',
      '',
      'Jump to [companions](#companions).',
      '',
    ].join('\n');
    expect(unroutedReadmeAnchors(md, {})).toEqual([]);
  });

  it('ignores sections the guide never publishes', () => {
    // "Development" is not in USER_SECTIONS, so its links never reach the site.
    const md = '## Development\n\nSee [nothing](#no-such-heading).\n';
    expect(unroutedReadmeAnchors(md, {})).toEqual([]);
  });

  it('gives a repeated heading GitHub’s -1 suffix', () => {
    // Without this the second "Installation" would overwrite the first in the
    // heading map, and a valid `#installation-1` link would be cried wolf over.
    const md = [
      '## Settings',
      '',
      '### Installation',
      '',
      '### Installation',
      '',
      'Jump to [the second one](#installation-1).',
      '',
    ].join('\n');
    expect(unroutedReadmeAnchors(md, {})).toEqual([]);
    // A third would be `-2`; a fourth that does not exist is still unknown.
    expect(unroutedReadmeAnchors(md.replace('installation-1', 'installation-2'), {})).toEqual([
      {anchor: '#installation-2', from: 'Settings', reason: 'unknown'},
    ]);
  });

  it('checks reference-style and raw HTML anchors too', () => {
    const refStyle = [
      '## Settings',
      '',
      'See [measured stock][ms].',
      '',
      '[ms]: #no-such-heading',
      '',
    ].join('\n');
    expect(unroutedReadmeAnchors(refStyle, {})).toEqual([
      {anchor: '#no-such-heading', from: 'Settings', reason: 'unknown'},
    ]);

    const html = '## Settings\n\n<a href="#no-such-heading">jump</a>\n';
    expect(unroutedReadmeAnchors(html, {})).toEqual([
      {anchor: '#no-such-heading', from: 'Settings', reason: 'unknown'},
    ]);
  });

  it('ignores an anchor-like string inside a fenced code block', () => {
    const md = [
      '## Settings',
      '',
      '```yaml',
      '# [x](#not-a-real-link)',
      '```',
      '',
    ].join('\n');
    expect(unroutedReadmeAnchors(md, {})).toEqual([]);
  });
});

describe('README sections on the site', () => {
  it('lists every README section as published or unpublished', () => {
    // A failure names the heading: add it to USER_SECTIONS in doc-map.mjs, or to
    // UNPUBLISHED_SECTIONS if it only makes sense in the repository.
    expect(unlistedReadmeSections(README)).toEqual([]);
  });

  it('flags a section that is in neither list', () => {
    const md = '## Installation\n\ntext\n\n## Brand new\n\ntext\n';
    expect(unlistedReadmeSections(md, USER_SECTIONS, UNPUBLISHED_SECTIONS)).toEqual(['Brand new']);
  });

  it('keeps the two lists disjoint', () => {
    const published = new Set(USER_SECTIONS.map((s) => s.h));
    expect(UNPUBLISHED_SECTIONS.filter((h) => published.has(h))).toEqual([]);
  });
});
