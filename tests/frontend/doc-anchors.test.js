import {existsSync} from 'node:fs';
import {resolve} from 'node:path';
import {describe, it, expect} from 'vitest';
import {
  USER_SECTIONS,
  GUIDE_GROUPS,
  GUIDE_ROUTES,
  guideFile,
  guideRoute,
  guideFileDrift,
  guideFilesOnDisk,
} from '../../website/scripts/doc-map.mjs';

/**
 * The User Guide is one authored file per page under `docs/guide/`, and
 * `USER_SECTIONS` is the only record of which file becomes which page. A file with
 * no entry is never published, and an entry with no file fails the site build — so
 * this is that check, in milliseconds rather than a four-minute CI job.
 */

const repo = process.cwd();

describe('guideFileDrift', () => {
  it('finds no drift between USER_SECTIONS and the files on disk', () => {
    // A failure names the file: add it to USER_SECTIONS in doc-map.mjs, or delete
    // the entry if the page is gone.
    expect(guideFileDrift(guideFilesOnDisk(repo))).toEqual({unlisted: [], missing: []});
  });

  it('reports a file with no entry', () => {
    expect(guideFileDrift(['docs/guide/start/brand-new.md'], []).unlisted).toEqual([
      'docs/guide/start/brand-new.md',
    ]);
  });

  it('reports a file in a nested subdirectory, which has no valid entry', () => {
    // guideFile() only builds docs/guide/<group>/<slug>.md, so a deeper path can
    // never be listed. Failing the build is the right answer, not ignoring it.
    expect(guideFileDrift(['docs/guide/tasks/sub/nested.md']).unlisted).toEqual([
      'docs/guide/tasks/sub/nested.md',
    ]);
  });

  it('reports an entry with no file', () => {
    const spec = {slug: 'ghost', title: 'Ghost', group: 'start'};
    expect(guideFileDrift([], [spec]).missing).toEqual(['docs/guide/start/ghost.md']);
  });
});

describe('guideFilesOnDisk', () => {
  it('returns every guide file, sorted, in repo-relative POSIX form', () => {
    const files = guideFilesOnDisk(repo);
    expect(files).toEqual([...files].sort());
    expect(files.every((f) => f.startsWith('docs/guide/') && f.endsWith('.md'))).toBe(true);
    expect(files).toContain('docs/guide/views/settings.md');
    // A slug collision across two groups would break the URL, so the map must not
    // allow one even though the two files sit in different directories.
    expect(files.length).toBe(USER_SECTIONS.length);
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
