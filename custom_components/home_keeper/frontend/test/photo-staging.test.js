import { describe, expect, it } from 'vitest';
import { formatBytes } from '../src/documents.ts';
import { MAX_TASK_PHOTO_BYTES, MAX_TASK_PHOTOS } from '../src/limits.ts';
import {
  STAGED_PHOTO_ACCEPT,
  STAGED_PHOTO_TYPES,
  makeStagedCover,
  rejectionMessage,
  releaseStaged,
  stageFiles,
  stagedTilesHtml,
  unstage,
  uploadStaged,
} from '../src/photo-staging.ts';
import { t } from '../src/i18n.ts';

const file = (name, type = 'image/jpeg', size = 10) => ({ name, type, size });
const keys = () => {
  let n = 0;
  return () => `k${(n += 1)}`;
};
const url = (f) => `blob:${f.name}`;
const staged = (...names) =>
  stageFiles([], names.map((n) => file(n)), url, { makeKey: keys() }).list;

describe('stageFiles', () => {
  it('adds accepted images at the end, with a key and a preview URL', () => {
    const first = stageFiles([], [file('a.jpg')], url, { makeKey: () => 'k1' }).list;
    const { list, rejected } = stageFiles(first, [file('b.png', 'image/png')], url, {
      makeKey: () => 'k2',
    });
    expect(list).toEqual([
      { key: 'k1', file: file('a.jpg'), previewUrl: 'blob:a.jpg' },
      { key: 'k2', file: file('b.png', 'image/png'), previewUrl: 'blob:b.png' },
    ]);
    expect(rejected).toEqual([]);
    expect(first).toHaveLength(1);
  });

  it('rejects a file that is not an accepted image, and makes no preview for it', () => {
    const made = [];
    const pdf = file('manual.pdf', 'application/pdf');
    const { list, rejected } = stageFiles([], [pdf], (f) => {
      made.push(f);
      return 'x';
    });
    expect(list).toEqual([]);
    expect(rejected).toEqual([{ file: pdf, reason: 'type' }]);
    expect(made).toEqual([]);
  });

  it('takes a file at the size limit and rejects 1 byte more', () => {
    const atLimit = file('ok.jpg', 'image/jpeg', 100);
    const over = file('big.jpg', 'image/jpeg', 101);
    const { list, rejected } = stageFiles([], [atLimit, over], url, { maxBytes: 100 });
    expect(list.map((s) => s.file)).toEqual([atLimit]);
    expect(rejected).toEqual([{ file: over, reason: 'size' }]);
  });

  it('uses the task photo limits by default', () => {
    const over = file('big.jpg', 'image/jpeg', MAX_TASK_PHOTO_BYTES + 1);
    const atLimit = file('ok.jpg', 'image/jpeg', MAX_TASK_PHOTO_BYTES);
    const many = Array.from({ length: MAX_TASK_PHOTOS + 1 }, (_, i) => file(`${i}.jpg`));
    expect(stageFiles([], [over, atLimit], url).rejected).toEqual([{ file: over, reason: 'size' }]);
    const { list, rejected } = stageFiles([], many, url);
    expect(list).toHaveLength(MAX_TASK_PHOTOS);
    expect(rejected).toEqual([{ file: many[MAX_TASK_PHOTOS], reason: 'full' }]);
  });

  it('rejects the files after the cap, counting the photos already staged', () => {
    const before = staged('a.jpg');
    const extra = [file('b.jpg'), file('c.jpg')];
    const { list, rejected } = stageFiles(before, extra, url, { cap: 2 });
    expect(list.map((s) => s.file.name)).toEqual(['a.jpg', 'b.jpg']);
    expect(rejected).toEqual([{ file: extra[1], reason: 'full' }]);
  });

  it('gives each photo its own key by default', () => {
    const { list } = stageFiles([], [file('a.jpg'), file('b.jpg')], url);
    expect(list[0].key).toBeTruthy();
    expect(list[0].key).not.toBe(list[1].key);
  });
});

describe('accepted types', () => {
  it('is the image list of the upload view', () => {
    expect(STAGED_PHOTO_TYPES).toEqual(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);
    expect(STAGED_PHOTO_ACCEPT).toBe('image/png,image/jpeg,image/webp,image/gif');
  });
});

describe('rejectionMessage', () => {
  it('names the file and the limits', () => {
    const big = file('big.jpg', 'image/jpeg', 2048);
    expect(rejectionMessage(big, 'size', 1024)).toBe(
      t('doc.uploadTooLargeLocal', { name: 'big.jpg', size: formatBytes(2048), limit: formatBytes(1024) }),
    );
    expect(rejectionMessage(big, 'full')).toBe(t('photos.full', { max: String(MAX_TASK_PHOTOS) }));
    expect(rejectionMessage(file('a.pdf'), 'type')).toBe(t('photos.notImage', { name: 'a.pdf' }));
  });

  it('uses the task photo size limit by default', () => {
    const big = file('big.jpg', 'image/jpeg', MAX_TASK_PHOTO_BYTES + 1);
    expect(rejectionMessage(big, 'size')).toContain(formatBytes(MAX_TASK_PHOTO_BYTES));
  });
});

describe('unstage, makeStagedCover and releaseStaged', () => {
  it('removes 1 photo and releases only its preview', () => {
    const list = staged('a.jpg', 'b.jpg');
    const released = [];
    const next = unstage(list, 'k1', (u) => released.push(u));
    expect(next.map((s) => s.key)).toEqual(['k2']);
    expect(released).toEqual(['blob:a.jpg']);
    expect(list).toHaveLength(2);
  });

  it('releases nothing for an unknown key', () => {
    const released = [];
    expect(unstage(staged('a.jpg'), 'nope', (u) => released.push(u))).toHaveLength(1);
    expect(released).toEqual([]);
  });

  it('moves the chosen photo to the front and keeps the others in order', () => {
    const list = staged('a.jpg', 'b.jpg', 'c.jpg');
    expect(makeStagedCover(list, 'k3').map((s) => s.key)).toEqual(['k3', 'k1', 'k2']);
    expect(makeStagedCover(list, 'nope').map((s) => s.key)).toEqual(['k1', 'k2', 'k3']);
    expect(makeStagedCover(list, 'nope')).not.toBe(list);
  });

  it('releases every preview, and accepts no list', () => {
    const released = [];
    releaseStaged(staged('a.jpg', 'b.jpg'), (u) => released.push(u));
    expect(released).toEqual(['blob:a.jpg', 'blob:b.jpg']);
    releaseStaged(undefined, () => released.push('x'));
    expect(released).toHaveLength(2);
  });
});

describe('uploadStaged', () => {
  it('uploads in order, 1 at a time, with the key as the photo id', async () => {
    const calls = [];
    let running = 0;
    const result = await uploadStaged(staged('a.jpg', 'b.jpg'), async (id, f) => {
      running += 1;
      expect(running).toBe(1);
      calls.push([id, f.name]);
      await Promise.resolve();
      running -= 1;
    });
    expect(calls).toEqual([
      ['k1', 'a.jpg'],
      ['k2', 'b.jpg'],
    ]);
    expect(result).toEqual({ done: 2, failed: [] });
  });

  it('goes on after a failure and returns the failed photos', async () => {
    const list = staged('a.jpg', 'b.jpg', 'c.jpg');
    const result = await uploadStaged(list, async (id) => {
      if (id === 'k2') throw new Error('413');
    });
    expect(result.done).toBe(2);
    expect(result.failed).toEqual([list[1]]);
  });
});

describe('stagedTilesHtml', () => {
  it('shows a Cover badge on the first tile only, and Make cover on the others', () => {
    const html = stagedTilesHtml(staged('a.jpg', 'b.jpg'), true);
    const doc = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html');
    const tiles = [...doc.querySelectorAll('.hk-staged')];
    expect(tiles.map((el) => el.dataset.stagedTile)).toEqual(['k1', 'k2']);
    expect(tiles[0].querySelector('.hk-photo-badge')?.textContent).toBe(t('photos.cover'));
    expect(tiles[1].querySelector('.hk-photo-badge')).toBeNull();
    expect(tiles[0].querySelector('.hk-staged-cover')).toBeNull();
    expect(tiles[1].querySelector('.hk-staged-cover')?.dataset.stagedKey).toBe('k2');
    expect(tiles[1].querySelector('.hk-staged-cover')?.getAttribute('label')).toBe(t('photos.makeCover'));
    expect(tiles.map((el) => el.querySelector('.hk-staged-remove')?.dataset.stagedKey)).toEqual(['k1', 'k2']);
    expect(tiles[0].querySelector('.hk-staged-remove')?.getAttribute('label')).toBe(t('photos.remove'));
    expect(tiles[1].querySelector('img')?.getAttribute('src')).toBe('blob:b.jpg');
    expect(tiles[1].querySelector('img')?.getAttribute('alt')).toBe('b.jpg');
    // The only text is the Cover badge: no stray text between or inside the tiles.
    expect(doc.body.firstElementChild.textContent).toBe(t('photos.cover'));
    expect(doc.body.firstElementChild.children).toHaveLength(2);
  });

  it('shows no Make cover without withCover', () => {
    const html = stagedTilesHtml(staged('a.jpg', 'b.jpg'), false);
    expect(html).not.toContain('hk-staged-cover');
    const doc = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html');
    expect(doc.body.firstElementChild.textContent).toBe(t('photos.cover'));
    expect(doc.querySelectorAll('.hk-photo-actions')[1].children).toHaveLength(1);
  });

  it('escapes the file name', () => {
    const list = stageFiles([], [file('<b>.jpg')], () => 'blob:x', { makeKey: () => 'k' }).list;
    expect(stagedTilesHtml(list, true)).not.toContain('<b>');
  });

  it('is empty for no photos', () => {
    expect(stagedTilesHtml([], true)).toBe('');
  });
});
