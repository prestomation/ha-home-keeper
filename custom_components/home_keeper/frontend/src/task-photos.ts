/**
 * Task photos (#399) on the panel side: which photos a surface shows, and the cache
 * of their signed URLs.
 *
 * A photo is served only through a short-lived signed URL, like an appliance file
 * (see `documents.ts`). The task list shows a cover thumbnail on every row that has
 * one, so signing one photo per round trip would cost a websocket call per row. This
 * cache signs every stale photo of a render in one `sign_task_photo_urls` call.
 */

import * as api from './api';
import { SIGNED_URL_REFRESH_MS } from './documents';
import { MAX_TASK_PHOTOS } from './limits';
import type { Hass, Task, TaskPhoto } from './types';

/** One photo URL a surface shows: the original, or with `thumb` the small copy. */
export interface TaskPhotoRef {
  taskId: string;
  photoId: string;
  thumb: boolean;
}

/** The task's photos. A task stored before #399 has none. */
export function photosOf(task: Pick<Task, 'photos'> | null | undefined): TaskPhoto[] {
  return Array.isArray(task?.photos) ? task.photos : [];
}

/** The cover photo (the first one), or undefined. */
export function coverOf(task: Pick<Task, 'photos'> | null | undefined): TaskPhoto | undefined {
  return photosOf(task)[0];
}

/** Whether the task has room for another photo. */
export function canAddPhoto(task: Pick<Task, 'photos'>): boolean {
  return photosOf(task).length < MAX_TASK_PHOTOS;
}

/** The cache key of a ref — also what a surface stamps on its `<img data-sign>`. */
export function taskPhotoKey(ref: TaskPhotoRef): string {
  return `task-photo:${ref.taskId}:${ref.photoId}:${ref.thumb ? 'thumb' : 'full'}`;
}

/** The thumbnail of each task's cover: what the task list shows. */
export function coverRefs(tasks: Task[]): TaskPhotoRef[] {
  const refs: TaskPhotoRef[] = [];
  for (const task of tasks) {
    const cover = coverOf(task);
    if (cover) refs.push({ taskId: task.id, photoId: cover.id, thumb: true });
  }
  return refs;
}

/** Every URL the task page needs: each photo's thumbnail for the strip and the
 *  header, and each original for the link that opens it. */
export function detailRefs(task: Task): TaskPhotoRef[] {
  return photosOf(task).flatMap((photo) => [
    { taskId: task.id, photoId: photo.id, thumb: true },
    { taskId: task.id, photoId: photo.id, thumb: false },
  ]);
}

/**
 * Signed URLs for task photos, signed ahead of the render that shows them.
 *
 * The same rules as `SignedUrlCache`: an entry is reused until it is stale, entries
 * for photos the surface no longer shows are dropped, and a failed sign keeps the
 * URL that was there before. The difference is that every stale ref goes out in one
 * batch.
 */
export class TaskPhotoUrlCache {
  private _entries = new Map<string, { url: string; signedAt: number }>();
  private _pending: Promise<boolean> | undefined;

  /** The cached URL for a key, or undefined if it is not signed yet. */
  getByKey(key: string): string | undefined {
    return this._entries.get(key)?.url;
  }

  /**
   * Make sure every ref has a fresh URL, and drop the entries for anything else.
   * Pass the complete set the surface shows. Resolves to true when a URL was
   * (re-)minted, so the caller knows whether to patch the page.
   *
   * A call made while a batch is in flight waits for that batch first, then signs
   * only what is still missing.
   */
  async ensure(hass: Hass, refs: TaskPhotoRef[], now = Date.now()): Promise<boolean> {
    if (this._pending) await this._pending;
    const needed = new Map<string, TaskPhotoRef>();
    for (const ref of refs) needed.set(taskPhotoKey(ref), ref);
    for (const key of [...this._entries.keys()]) {
      if (!needed.has(key)) this._entries.delete(key);
    }
    const stale = [...needed].filter(([key]) => {
      const cached = this._entries.get(key);
      return !cached || now - cached.signedAt >= SIGNED_URL_REFRESH_MS;
    });
    if (stale.length === 0) return false;
    const batch = (async (): Promise<boolean> => {
      try {
        const urls = await api.signTaskPhotoUrls(
          hass,
          stale.map(([, ref]) => ({ task_id: ref.taskId, photo_id: ref.photoId, thumb: ref.thumb })),
        );
        let signed = false;
        const at = Date.now();
        for (const item of urls) {
          if (!item.url) continue;
          const key = taskPhotoKey({ taskId: item.task_id, photoId: item.photo_id, thumb: item.thumb });
          this._entries.set(key, { url: item.url, signedAt: at });
          signed = true;
        }
        return signed;
      } catch {
        // Keep any prior URL; the next render tries again.
        return false;
      }
    })();
    this._pending = batch;
    try {
      return await batch;
    } finally {
      if (this._pending === batch) this._pending = undefined;
    }
  }
}
