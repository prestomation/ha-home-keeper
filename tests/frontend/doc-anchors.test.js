import {readdirSync, existsSync} from 'node:fs';
import {resolve} from 'node:path';
import {describe, it, expect} from 'vitest';
import {
  USER_SECTIONS,
  GUIDE_GROUPS,
  GUIDE_ROUTES,
  guideFile,
  guideRoute,
  guideFileDrift,
} from '../../website/scripts/doc-map.mjs';

/**
 * The User Guide is one authored file per page under `docs/guide/`, and
 * `USER_SECTIONS` is the only record of which file becomes which page. A file with
 * no entry is never published, and an entry with no file fails the site build — so
 * this is that check, in milliseconds rather than a four-minute CI job.
 */

const repo = process.cwd();

function guideFilesOnDisk() {
  return readdirSync(resolve(repo, 'docs', 'guide'), {recursive: true})
    .map((f) => `docs/guide/${f}`.replaceAll('\\', '/'))
    .filter((f) => f.endsWith('.md'))
    .sort();
}

describe('guideFileDrift', () => {
  it('finds no drift between USER_SECTIONS and the files on disk', () => {
    // A failure names the file: add it to USER_SECTIONS in doc-map.mjs, or delete
    // the entry if the page is gone.
    expect(guideFileDrift(guideFilesOnDisk())).toEqual({unlisted: [], missing: []});
  });

  it('reports a file with no entry', () => {
    expect(guideFileDrift(['docs/guide/start/brand-new.md'], []).unlisted).toEqual([
      'docs/guide/start/brand-new.md',
    ]);
  });

  it('reports an entry with no file', () => {
    const spec = {slug: 'ghost', title: 'Ghost', group: 'start'};
    expect(guideFileDrift([], [spec]).missing).toEqual(['docs/guide/start/ghost.md']);
  });
});

describe('USER_SECTIONS', () => {
  it('puts every page in a sidebar group', () => {
    const dirs = new Set(GUIDE_GROUPS.map((g) => g.dir));
    expect(USER_SECTIONS.filter((s) => !dirs.has(s.group)).map((s) => s.slug)).toEqual([]);
  });

  it('keeps every slug unique, because the slug is the URL', () => {
    const slugs = USER_SECTIONS.map((s) => s.slug);
    expect(slugs.length).toBe(new Set(slugs).size);
  });

  it('names a file that exists for every page', () => {
    const missing = USER_SECTIONS.map(guideFile).filter(
      (f) => !existsSync(resolve(repo, f)),
    );
    expect(missing).toEqual([]);
  });
});

describe('GUIDE_ROUTES', () => {
  it('routes every authored file to its page', () => {
    for (const spec of USER_SECTIONS) {
      expect(GUIDE_ROUTES[guideFile(spec)]).toBe(guideRoute(spec));
    }
  });

  it('has no route for a file outside the guide', () => {
    expect(GUIDE_ROUTES['docs/EVENTS.md']).toBeUndefined();
  });
});
