import { describe, expect, it } from 'vitest';
import { SIGNED_URL_REFRESH_MS } from '../src/documents.ts';
import {
  TaskPhotoUrlCache,
  canAddPhoto,
  completionFullUrl,
  completionThumbUrl,
  coverOf,
  coverRefs,
  detailRefs,
  headPhotoLabels,
  lastCompletion,
  lastCompletionPhoto,
  photosOf,
  taskPhotoKey,
} from '../src/task-photos.ts';
import { t } from '../src/i18n.ts';

const photo = (id) => ({ id, name: `${id}.jpg`, filename: `${id}.jpg`, content_type: 'image/jpeg', size: 1 });
const task = (id, n) => ({ id, name: id, photos: Array.from({ length: n }, (_, i) => photo(`${id}p${i}`)) });

// A hass stub for the batch sign: records each batch, and mints a URL per ref that
// names the batch, so a re-sign is observable.
function makeHass({ fail = false, gone = new Set() } = {}) {
  const batches = [];
  const hass = {
    callWS(msg) {
      if (msg.type !== 'home_keeper/sign_task_photo_urls') return Promise.resolve({});
      batches.push(msg.photos);
      if (fail) return Promise.reject(new Error('sign failed'));
      const n = batches.length;
      return Promise.resolve({
        urls: msg.photos.map((ref) => ({
          ...ref,
          url: gone.has(ref.photo_id) ? null : `/p/${ref.photo_id}/${ref.thumb ? 't' : 'f'}?sig=${n}`,
        })),
      });
    },
  };
  return { hass, batches };
}

describe('task photo reads', () => {
  it('a task stored before photos has none', () => {
    expect(photosOf({ id: 't' })).toEqual([]);
    expect(photosOf({ id: 't', photos: null })).toEqual([]);
    expect(photosOf(null)).toEqual([]);
    expect(photosOf(undefined)).toEqual([]);
  });

  it('the cover is the first photo', () => {
    expect(coverOf(task('t', 3)).id).toBe('tp0');
    expect(coverOf(task('t', 0))).toBeUndefined();
    expect(coverOf(null)).toBeUndefined();
  });

  it('a task takes photos up to 6', () => {
    expect(canAddPhoto(task('t', 0))).toBe(true);
    expect(canAddPhoto(task('t', 5))).toBe(true);
    expect(canAddPhoto(task('t', 6))).toBe(false);
    expect(canAddPhoto({ id: 't' })).toBe(true);
  });

  it('the key names the task, the photo and the size', () => {
    expect(taskPhotoKey({ taskId: 't', photoId: 'p', thumb: true })).toBe('task-photo:t:p:thumb');
    expect(taskPhotoKey({ taskId: 't', photoId: 'p', thumb: false })).toBe('task-photo:t:p:full');
  });

  it('the list signs the cover thumbnail of each task that has one', () => {
    expect(coverRefs([task('a', 2), task('b', 0), task('c', 1)])).toEqual([
      { taskId: 'a', photoId: 'ap0', thumb: true },
      { taskId: 'c', photoId: 'cp0', thumb: true },
    ]);
    expect(coverRefs([])).toEqual([]);
  });

  it('the task page signs the thumbnail and the original of every photo', () => {
    expect(detailRefs(task('a', 2))).toEqual([
      { taskId: 'a', photoId: 'ap0', thumb: true },
      { taskId: 'a', photoId: 'ap0', thumb: false },
      { taskId: 'a', photoId: 'ap1', thumb: true },
      { taskId: 'a', photoId: 'ap1', thumb: false },
    ]);
    expect(detailRefs(task('a', 0))).toEqual([]);
  });
});

describe('TaskPhotoUrlCache', () => {
  const A = { taskId: 'a', photoId: 'p1', thumb: true };
  const B = { taskId: 'a', photoId: 'p1', thumb: false };
  const C = { taskId: 'b', photoId: 'p2', thumb: true };

  it('signs every stale ref in one batch', async () => {
    const { hass, batches } = makeHass();
    const cache = new TaskPhotoUrlCache();

    expect(await cache.ensure(hass, [A, B, C])).toBe(true);

    expect(batches).toEqual([
      [
        { task_id: 'a', photo_id: 'p1', thumb: true },
        { task_id: 'a', photo_id: 'p1', thumb: false },
        { task_id: 'b', photo_id: 'p2', thumb: true },
      ],
    ]);
    expect(cache.getByKey(taskPhotoKey(A))).toBe('/p/p1/t?sig=1');
    expect(cache.getByKey(taskPhotoKey(B))).toBe('/p/p1/f?sig=1');
    expect(cache.getByKey(taskPhotoKey(C))).toBe('/p/p2/t?sig=1');
  });

  it('reuses a fresh URL and signs nothing', async () => {
    const { hass, batches } = makeHass();
    const cache = new TaskPhotoUrlCache();
    await cache.ensure(hass, [A]);

    expect(await cache.ensure(hass, [A])).toBe(false);
    expect(batches).toHaveLength(1);
  });

  it('signs only the refs that are new', async () => {
    const { hass, batches } = makeHass();
    const cache = new TaskPhotoUrlCache();
    await cache.ensure(hass, [A]);
    await cache.ensure(hass, [A, C]);

    expect(batches[1]).toEqual([{ task_id: 'b', photo_id: 'p2', thumb: true }]);
  });

  it('re-signs a URL at the refresh age, not before', async () => {
    const { hass, batches } = makeHass();
    const cache = new TaskPhotoUrlCache();
    const start = Date.now();
    await cache.ensure(hass, [A], start);

    expect(await cache.ensure(hass, [A], start + SIGNED_URL_REFRESH_MS - 1000 * 60)).toBe(false);
    expect(batches).toHaveLength(1);
    expect(await cache.ensure(hass, [A], Date.now() + SIGNED_URL_REFRESH_MS)).toBe(true);
    expect(batches).toHaveLength(2);
    expect(cache.getByKey(taskPhotoKey(A))).toBe('/p/p1/t?sig=2');
  });

  it('drops the URLs of photos the surface no longer shows', async () => {
    const { hass } = makeHass();
    const cache = new TaskPhotoUrlCache();
    await cache.ensure(hass, [A, C]);

    expect(await cache.ensure(hass, [C])).toBe(false);
    expect(cache.getByKey(taskPhotoKey(A))).toBeUndefined();
    expect(cache.getByKey(taskPhotoKey(C))).toBe('/p/p2/t?sig=1');
  });

  it('an empty set drops everything and signs nothing', async () => {
    const { hass, batches } = makeHass();
    const cache = new TaskPhotoUrlCache();
    await cache.ensure(hass, [A]);

    expect(await cache.ensure(hass, [])).toBe(false);
    expect(batches).toHaveLength(1);
    expect(cache.getByKey(taskPhotoKey(A))).toBeUndefined();
  });

  it('a photo that is gone stays unsigned', async () => {
    const { hass } = makeHass({ gone: new Set(['p1']) });
    const cache = new TaskPhotoUrlCache();

    expect(await cache.ensure(hass, [A])).toBe(false);
    expect(cache.getByKey(taskPhotoKey(A))).toBeUndefined();
  });

  it('a gone photo does not stop the others in its batch', async () => {
    const { hass } = makeHass({ gone: new Set(['p1']) });
    const cache = new TaskPhotoUrlCache();

    expect(await cache.ensure(hass, [A, C])).toBe(true);
    expect(cache.getByKey(taskPhotoKey(C))).toBe('/p/p2/t?sig=1');
  });

  it('a failed sign keeps the URL that was there', async () => {
    const ok = makeHass();
    const cache = new TaskPhotoUrlCache();
    await cache.ensure(ok.hass, [A]);
    const failing = makeHass({ fail: true });

    expect(await cache.ensure(failing.hass, [A], Date.now() + SIGNED_URL_REFRESH_MS)).toBe(false);
    expect(cache.getByKey(taskPhotoKey(A))).toBe('/p/p1/t?sig=1');
  });

  it('a call made during a batch waits for it and signs only what is missing', async () => {
    const { hass, batches } = makeHass();
    const cache = new TaskPhotoUrlCache();

    const first = cache.ensure(hass, [A]);
    const second = cache.ensure(hass, [A, C]);
    expect(await first).toBe(true);
    expect(await second).toBe(true);

    expect(batches).toEqual([
      [{ task_id: 'a', photo_id: 'p1', thumb: true }],
      [{ task_id: 'b', photo_id: 'p2', thumb: true }],
    ]);
  });

  it('after a failed batch the next call tries again', async () => {
    const cache = new TaskPhotoUrlCache();
    await cache.ensure(makeHass({ fail: true }).hass, [A]);
    const { hass, batches } = makeHass();

    expect(await cache.ensure(hass, [A])).toBe(true);
    expect(batches).toHaveLength(1);
  });
});

describe('photo limits', () => {
  it('mirror const.py', async () => {
    const limits = await import('../src/limits.ts');
    expect(limits.MAX_TASK_PHOTO_BYTES).toBe(26214400);
    expect(limits.MAX_TASK_PHOTOS).toBe(6);
  });
});

describe('the photo of the last completion (#399)', () => {
  const c = (ts, photo) => ({ ts, ...(photo ? { photo } : {}) });

  it('takes the completion that set last_completed, not the last entry', () => {
    // A backdated entry goes to the end of the list without moving last_completed.
    const task = {
      last_completed: '2026-09-20T10:00:00Z',
      completions: [c('2026-09-20T10:00:00Z', '/a.jpg'), c('2026-08-01T10:00:00Z', '/b.jpg')],
    };
    expect(lastCompletion(task).ts).toBe('2026-09-20T10:00:00Z');
    expect(lastCompletionPhoto(task)).toBe('/a.jpg');
  });

  it('falls back to the newest entry when none matches last_completed', () => {
    const task = {
      last_completed: '2026-01-01T00:00:00Z',
      completions: [
        c('2026-08-01T10:00:00Z', '/b.jpg'),
        c('2026-09-20T10:00:00Z', '/a.jpg'),
        c('2026-09-01T10:00:00Z', '/c.jpg'),
      ],
    };
    expect(lastCompletionPhoto(task)).toBe('/a.jpg');
    // The first of 2 entries with the same time stays: a later tie does not replace it.
    const tie = { completions: [c('2026-09-20T10:00:00Z', '/x.jpg'), c('2026-09-20T10:00:00Z', '/y.jpg')] };
    expect(lastCompletionPhoto(tie)).toBe('/x.jpg');
  });

  it('gives nothing for a task with no completions, or a last one with no photo', () => {
    expect(lastCompletion({})).toBeUndefined();
    expect(lastCompletionPhoto({ completions: null })).toBeNull();
    const noPhoto = { last_completed: 'x', completions: [c('2026-08-01T10:00:00Z', '/b.jpg'), c('x')] };
    // The last completion has no photo, so an older one does not take its place.
    expect(lastCompletionPhoto(noPhoto)).toBeNull();
  });

  it('refuses a URL that is not safe to show', () => {
    for (const photo of ['javascript:alert(1)', 'data:image/png;base64,xx', '//evil.example/a.jpg']) {
      expect(lastCompletionPhoto({ completions: [c('2026-08-01T10:00:00Z', photo)] })).toBeNull();
    }
    expect(lastCompletionPhoto({ completions: [c('2026-08-01T10:00:00Z', 'https://x.example/a.jpg')] })).toBe(
      'https://x.example/a.jpg',
    );
  });

  it('asks the image store for its 256px copy, and leaves any other URL as it is', () => {
    expect(completionThumbUrl('/api/image/serve/abc123/original')).toBe('/api/image/serve/abc123/256x256');
    // The dialog's picture upload stores the 512px copy.
    expect(completionThumbUrl('/api/image/serve/abc123/512x512')).toBe('/api/image/serve/abc123/256x256');
    expect(completionThumbUrl('/api/image/serve/abc123/512x512?x=1')).toBe('/api/image/serve/abc123/512x512?x=1');
    expect(completionThumbUrl('/api/image/serve/abc123/large')).toBe('/api/image/serve/abc123/large');
    expect(completionThumbUrl('/local/after.jpg')).toBe('/local/after.jpg');
    expect(completionThumbUrl('https://x.example/api/image/serve/a/original')).toBe(
      'https://x.example/api/image/serve/a/original',
    );
  });

  it('opens the image store original, and any other URL as it is', () => {
    expect(completionFullUrl('/api/image/serve/abc123/512x512')).toBe('/api/image/serve/abc123/original');
    expect(completionFullUrl('/api/image/serve/abc123/original')).toBe('/api/image/serve/abc123/original');
    expect(completionFullUrl('/local/after.jpg')).toBe('/local/after.jpg');
  });

  it('labels a one-off pair before and after, and a repeating pair cover and last completion', () => {
    expect(headPhotoLabels({ recurrence_type: 'one-off' })).toEqual({
      cover: t('photos.before'),
      last: t('photos.after'),
    });
    expect(headPhotoLabels({ recurrence_type: 'floating' })).toEqual({
      cover: t('photos.cover'),
      last: t('photos.lastCompletion'),
    });
  });
});
