/**
 * Photos picked before a task exists (#399): the New task form in the panel and in
 * the card.
 *
 * The upload view needs a task id, so the form keeps the files in the browser, and
 * uploads them after `add_task` returns the new task. The list is in display order:
 * the first photo becomes the cover, because the backend adds each upload at the end.
 *
 * The browser work (preview URLs, the upload) comes in through parameters, so this
 * module has no DOM and no network of its own, and both bundles can use it.
 */

import { formatBytes } from './documents';
import { t } from './i18n';
import { MAX_TASK_PHOTO_BYTES, MAX_TASK_PHOTOS } from './limits';
import { escapeHTML, randomId } from './utils';

/** The image types the upload view accepts. The same list as `IMAGE_ACCEPT`. */
export const STAGED_PHOTO_TYPES: readonly string[] = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];

/** The `accept` value of a staged photo picker. */
export const STAGED_PHOTO_ACCEPT = STAGED_PHOTO_TYPES.join(',');

/** One photo the user picked, not uploaded yet. */
export interface StagedPhoto {
  /** A local key for the form's buttons. It is also the photo id of the upload. */
  key: string;
  file: File;
  /** An object URL for the preview. Release it with `releaseStaged`. */
  previewUrl: string;
}

/** Why a file was not staged. */
export type StageRejection = 'type' | 'size' | 'full';

export interface StageResult {
  list: StagedPhoto[];
  rejected: { file: File; reason: StageRejection }[];
}

export interface StageOptions {
  cap?: number;
  maxBytes?: number;
  makeKey?: () => string;
}

/**
 * Add *files* to the end of *list*. A file that is not an accepted image, that is
 * larger than *maxBytes*, or that comes after the list is full, is rejected.
 * *makeUrl* makes the preview URL (`URL.createObjectURL` in the browser). Returns a
 * new list.
 */
export function stageFiles(
  list: readonly StagedPhoto[],
  files: Iterable<File>,
  makeUrl: (file: File) => string,
  opts: StageOptions = {},
): StageResult {
  const cap = opts.cap ?? MAX_TASK_PHOTOS;
  const maxBytes = opts.maxBytes ?? MAX_TASK_PHOTO_BYTES;
  const makeKey = opts.makeKey ?? randomId;
  const next = [...list];
  const rejected: StageResult['rejected'] = [];
  for (const file of files) {
    if (!STAGED_PHOTO_TYPES.includes(file.type)) rejected.push({ file, reason: 'type' });
    else if (file.size > maxBytes) rejected.push({ file, reason: 'size' });
    else if (next.length >= cap) rejected.push({ file, reason: 'full' });
    else next.push({ key: makeKey(), file, previewUrl: makeUrl(file) });
  }
  return { list: next, rejected };
}

/** The message for 1 rejected file. */
export function rejectionMessage(file: File, reason: StageRejection, maxBytes = MAX_TASK_PHOTO_BYTES): string {
  if (reason === 'size') {
    return t('doc.uploadTooLargeLocal', {
      name: file.name,
      size: formatBytes(file.size),
      limit: formatBytes(maxBytes),
    });
  }
  if (reason === 'full') return t('photos.full', { max: String(MAX_TASK_PHOTOS) });
  return t('photos.notImage', { name: file.name });
}

/** Remove the photo with *key*, and release its preview URL. Returns a new list. */
export function unstage(
  list: readonly StagedPhoto[],
  key: string,
  revoke: (url: string) => void,
): StagedPhoto[] {
  const hit = list.find((s) => s.key === key);
  if (hit) revoke(hit.previewUrl);
  return list.filter((s) => s.key !== key);
}

/** Move the photo with *key* to the front, so it becomes the cover. Returns a new list. */
export function makeStagedCover(list: readonly StagedPhoto[], key: string): StagedPhoto[] {
  const hit = list.find((s) => s.key === key);
  if (!hit) return [...list];
  return [hit, ...list.filter((s) => s.key !== key)];
}

/** Release every preview URL of *list*. */
export function releaseStaged(list: readonly StagedPhoto[] | undefined, revoke: (url: string) => void): void {
  for (const s of list ?? []) revoke(s.previewUrl);
}

export interface UploadStagedResult {
  done: number;
  failed: StagedPhoto[];
}

/**
 * Upload *list* in order, 1 at a time, so the first photo becomes the cover. A
 * failure does not stop the others. *upload* sends 1 file with its photo id.
 */
export async function uploadStaged(
  list: readonly StagedPhoto[],
  upload: (photoId: string, file: File) => Promise<unknown>,
): Promise<UploadStagedResult> {
  let done = 0;
  const failed: StagedPhoto[] = [];
  for (const s of list) {
    try {
      await upload(s.key, s.file);
      done += 1;
    } catch {
      failed.push(s);
    }
  }
  return { done, failed };
}

/**
 * The tiles of a staged strip: each preview with a Remove button, and with Make
 * cover on each photo after the first when *withCover* is set. The first tile has
 * the Cover badge. The host wires the buttons by their `data-staged-key`.
 */
export function stagedTilesHtml(list: readonly StagedPhoto[], withCover: boolean): string {
  return list
    .map((s, i) => {
      const key = escapeHTML(s.key);
      const cover =
        withCover && i > 0
          ? `<ha-icon-button class="hk-staged-cover" data-staged-key="${key}" label="${escapeHTML(
              t('photos.makeCover'),
            )}"></ha-icon-button>`
          : '';
      const badge = i === 0 ? `<span class="hk-photo-badge">${escapeHTML(t('photos.cover'))}</span>` : '';
      return `<div class="hk-photo hk-staged" data-staged-tile="${key}"><div class="hk-photo-link"><img class="hk-photo-img" src="${escapeHTML(
        s.previewUrl,
      )}" alt="${escapeHTML(s.file.name)}" /></div>${badge}<div class="hk-photo-actions">${cover}<ha-icon-button class="hk-staged-remove" data-staged-key="${key}" label="${escapeHTML(
        t('photos.remove'),
      )}"></ha-icon-button></div></div>`;
    })
    .join('');
}
