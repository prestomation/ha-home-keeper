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
import { coverOf, taskPhotoKey } from './task-photos';
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

/** The small cover on a task list row, or '' when there is none. Not a link: the
 *  row itself opens the task. */
export function listCoverHtml(p: PanelHost, task: Task): string {
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
