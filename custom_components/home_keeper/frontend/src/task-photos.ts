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
import { t } from './i18n';
import { MAX_TASK_PHOTOS } from './limits';
import type { Completion, Hass, Task, TaskPhoto } from './types';
import { isSafeImageUrl } from './utils';

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

/**
 * The completion that set the task's last completed time, or the newest entry.
 *
 * `completions` is in the order the entries were logged, not by date: a backdated
 * entry goes to the end without moving `last_completed`. So the last entry is not
 * always the latest one.
 */
export function lastCompletion(
  task: Pick<Task, 'completions' | 'last_completed'>,
): Completion | undefined {
  const list = Array.isArray(task.completions) ? task.completions : [];
  const match = list.find((c) => c.ts === task.last_completed);
  if (match) return match;
  let newest: Completion | undefined;
  for (const c of list) {
    if (!newest || Date.parse(c.ts) > Date.parse(newest.ts)) newest = c;
  }
  return newest;
}

/** The photo of the last completion (the "after" photo), or null when it has none
 *  or its URL is not safe to show. */
export function lastCompletionPhoto(
  task: Pick<Task, 'completions' | 'last_completed'>,
): string | null {
  const photo = lastCompletion(task)?.photo;
  return isSafeImageUrl(photo) ? photo : null;
}

/** An image store URL: `/api/image/serve/<id>/<original | NxN>`. The completion
 *  dialog's picture upload stores the 512px copy. */
const IMAGE_STORE_URL = /^(\/api\/image\/serve\/[^/?#]+)\/(?:original|\d+x\d+)$/;

/** Home Assistant's image store serves a 256px copy beside the original. A
 *  thumbnail asks for that copy. Any other URL is used as it is. */
export function completionThumbUrl(url: string): string {
  return url.replace(IMAGE_STORE_URL, '$1/256x256');
}

/** The full-size photo that a tap opens: the image store's original. */
export function completionFullUrl(url: string): string {
  return url.replace(IMAGE_STORE_URL, '$1/original');
}

/**
 * The labels of the 2 photos on the task page: the cover, and the photo of the
 * last completion. A one-off task has one piece of work, so its pair reads as
 * before and after. A task that repeats has many, and its cover shows the task,
 * not the state before the last completion.
 */
export function headPhotoLabels(task: Pick<Task, 'recurrence_type'>): {
  cover: string;
  last: string;
} {
  return task.recurrence_type === 'one-off'
    ? { cover: t('photos.before'), last: t('photos.after') }
    : { cover: t('photos.cover'), last: t('photos.lastCompletion') };
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
    // Kept after it settles: awaiting a settled batch costs one microtask, and
    // clearing it would race a call that started waiting on it.
    this._pending = batch;
    return batch;
  }
}
