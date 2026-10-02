import { describe, expect, it } from 'vitest';
import { SIGNED_URL_REFRESH_MS } from '../src/documents.ts';
import {
  TaskPhotoUrlCache,
  canAddPhoto,
  coverOf,
  coverRefs,
  detailRefs,
  photosOf,
  taskPhotoKey,
} from '../src/task-photos.ts';

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
