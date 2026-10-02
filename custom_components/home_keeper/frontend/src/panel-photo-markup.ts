/**
 * The markup of a task photo (#399): the `<img>`, the link that opens the original,
 * and the cover on the task page, a list row and the completion dialog.
 *
 * Every `<img>` starts with the signed URL the cache already holds, or none, and
 * carries `data-sign`, so `_signFiles` fills the URL in after the render when it was
 * not minted yet. A tap opens the original in a new tab through a plain anchor,
 * which the iOS app needs (see `documents.ts`).
 *
 * Kept apart from `panel-task-photos.ts` so `panel-dialogs.ts` can use it without an
 * import cycle: the Photos section needs the confirm dialog from there.
 */

import { t } from './i18n';
import type { PanelHost } from './panel-host';
import {
  completionFullUrl,
  completionThumbUrl,
  coverOf,
  headPhotoLabels,
  lastCompletionPhoto,
  taskPhotoKey,
} from './task-photos';
import type { Task, TaskPhoto } from './types';
import { escapeHTML, safeFileHref } from './utils';

/** An `<img>` for one photo, at thumbnail or full size. */
export function photoImg(
  p: PanelHost,
  task: Task,
  photo: TaskPhoto,
  className: string,
  alt: string,
): string {
  const key = taskPhotoKey({ taskId: task.id, photoId: photo.id, thumb: true });
  const url = p._signedUrl(key);
  const src = url ? ` src="${safeFileHref(url)}"` : '';
  return `<img class="${className}" data-sign="${escapeHTML(key)}"${src} alt="${escapeHTML(
    alt,
  )}" loading="lazy" decoding="async" />`;
}

/** An anchor that opens the original of *photo* in a new tab, around *inner*. */
export function photoLink(p: PanelHost, task: Task, photo: TaskPhoto, className: string, inner: string): string {
  const key = taskPhotoKey({ taskId: task.id, photoId: photo.id, thumb: false });
  const url = p._signedUrl(key);
  const href = url ? ` href="${safeFileHref(url)}"` : '';
  return `<a class="${className}" data-sign="${escapeHTML(key)}"${href} target="_blank" rel="noopener" aria-label="${escapeHTML(
    t('photos.open', { name: photo.name }),
  )}">${inner}</a>`;
}

/** The cover beside the task name on the task page, or '' when there is none. */
export function taskCoverHtml(p: PanelHost, task: Task): string {
  const cover = coverOf(task);
  if (!cover) return '';
  return photoLink(
    p,
    task,
    cover,
    'hk-task-cover',
    photoImg(p, task, cover, 'hk-task-cover-img', t('photos.coverAlt', { task: task.name })),
  );
}

/** A link that opens the photo of the last completion, around its 256px copy. The
 *  image store serves it without a signed URL, so it needs no `data-sign`. */
function afterPhotoLink(task: Task, url: string, className: string, imgClass: string): string {
  const alt = escapeHTML(t('photos.afterAlt', { task: task.name }));
  return `<a class="${className}" href="${safeFileHref(completionFullUrl(url))}" target="_blank" rel="noopener" aria-label="${alt}"><img class="${imgClass}" src="${safeFileHref(
    completionThumbUrl(url),
  )}" alt="${alt}" loading="lazy" decoding="async" /></a>`;
}

/**
 * The photos beside the task name on the task page (#399).
 *
 * When the last completion has a photo, the cover and that photo show as a
 * labelled pair, so the page shows the work and its result together. Otherwise
 * the cover shows alone, as before, or nothing when the task has no photo.
 */
export function taskHeadPhotosHtml(p: PanelHost, task: Task): string {
  const after = lastCompletionPhoto(task);
  if (!after) return taskCoverHtml(p, task);
  const labels = headPhotoLabels(task);
  const tile = (inner: string, label: string): string =>
    `<div class="hk-head-photo">${inner}<span class="hk-photo-badge">${escapeHTML(label)}</span></div>`;
  const cover = taskCoverHtml(p, task);
  return (
    `<div class="hk-head-photos">${cover ? tile(cover, labels.cover) : ''}` +
    `${tile(afterPhotoLink(task, after, 'hk-task-cover', 'hk-task-cover-img'), labels.last)}</div>`
  );
}

/** Whether *task* is a one-off that is done, which the Completed group holds. */
function isCompletedOneOff(task: Task): boolean {
  return task.recurrence_type === 'one-off' && !task.next_due && !!task.last_completed;
}

/** The small cover on a task list row, or '' when there is none. Not a link: the
 *  row itself opens the task.
 *
 *  A one-off that is done shows the photo of its completion instead, with a check
 *  mark, so the Completed group shows the result of the work (#399). */
export function listCoverHtml(p: PanelHost, task: Task): string {
  const after = isCompletedOneOff(task) ? lastCompletionPhoto(task) : null;
  if (after) {
    return (
      `<span class="hk-row-after"><img class="hk-row-cover" src="${safeFileHref(
        completionThumbUrl(after),
      )}" alt="${escapeHTML(t('photos.afterAlt', { task: task.name }))}" loading="lazy" decoding="async" />` +
      `<span class="hk-row-after-check" aria-hidden="true"><ha-icon icon="mdi:check"></ha-icon></span></span>`
    );
  }
  const cover = coverOf(task);
  if (!cover) return '';
  return photoImg(p, task, cover, 'hk-row-cover', t('photos.coverAlt', { task: task.name }));
}

/** The cover at the top of the completion dialog, so the person who logs the work
 *  sees what it was about. Null when the task has no photo. */
export function dialogCoverEl(p: PanelHost, task: Task): HTMLElement | null {
  const cover = coverOf(task);
  if (!cover) return null;
  const wrap = document.createElement('div');
  wrap.className = 'hk-completion-cover';
  wrap.innerHTML = `${photoLink(
    p,
    task,
    cover,
    'hk-completion-cover-link',
    photoImg(p, task, cover, 'hk-completion-cover-img', t('photos.coverAlt', { task: task.name })),
  )}<span>${escapeHTML(t('photos.taskPhoto'))}</span>`;
  return wrap;
}
