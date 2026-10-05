/**
 * The Photos section of the task page (#399): the strip, the add tile, and the cover
 * and remove buttons. The photo markup itself is in `panel-photo-markup.ts`.
 */

import * as api from './api';
import { t } from './i18n';
import { MAX_TASK_PHOTO_BYTES, MAX_TASK_PHOTOS } from './limits';
import { openConfirmDialog } from './panel-dialogs';
import { setIcon } from './panel-history';
import type { PanelHost } from './panel-host';
import { MDI_DELETE } from './panel-icons';
import { photoImg, photoLink } from './panel-photo-markup';
import { IMAGE_ACCEPT, filePicker, renderUploadStatus, runUpload, uploadButtonLabel } from './panel-upload';
import {
  STAGED_PHOTO_ACCEPT,
  makeStagedCover,
  rejectionMessage,
  stageFiles,
  stagedTilesHtml,
  unstage,
} from './photo-staging';
import { canAddPhoto, photosOf } from './task-photos';
import type { Task } from './types';
import { escapeHTML, randomId, toast } from './utils';

/** mdi:star-outline, the "make cover" action. */
const MDI_STAR_OUTLINE =
  'M12,15.39L8.24,17.66L9.23,13.38L5.91,10.5L10.29,10.13L12,6.09L13.71,10.13L18.09,10.5L14.77,13.38L15.76,17.66M22,9.24L14.81,8.63L12,2L9.19,8.63L2,9.24L7.45,13.97L5.82,21L12,17.27L18.18,21L16.54,13.97L22,9.24Z';
/** mdi:camera-plus-outline, the add tile. */
const MDI_CAMERA_PLUS =
  'M21 6V8H19V6H17V4H19V2H21V4H23V6H21M18.5 15C18.5 17.5 16.5 19.5 14 19.5S9.5 17.5 9.5 15 11.5 10.5 14 10.5 18.5 12.5 18.5 15M16.5 15C16.5 13.62 15.38 12.5 14 12.5S11.5 13.62 11.5 15 12.62 17.5 14 17.5 16.5 16.38 16.5 15M15.5 8H18V20C18 21.1 17.1 22 16 22H4C2.9 22 2 21.1 2 20V8C2 6.9 2.9 6 4 6H7L9 4H15.5V6H9.83L7.83 8H4V20H16V8.5';

/** The upload key of a task's photo control (one upload runs at a time). */
export function taskPhotoUploadKey(taskId: string): string {
  return `task-photo:${taskId}`;
}

/**
 * The Photos section at the top of the Schedule tab. A task with no photos shows it
 * as an invitation. Photos belong to the household, so an owning integration cannot
 * lock them: `photos` in `managed_by.locked_fields` has no effect.
 */
export function photosSection(p: PanelHost, task: Task): string {
  const photos = photosOf(task);
  return `
      <div class="hk-section">${escapeHTML(t('photos.title'))}
        <span class="hk-section-count">${escapeHTML(
          t('photos.count', { n: String(photos.length), max: String(MAX_TASK_PHOTOS) }),
        )}</span></div>
      <ha-card class="hk-detail-card hk-photos-card"><div class="hk-detail-inner">
        ${photoStripHtml(p, task)}
      </div></ha-card>`;
}

/** The hint, the strip of tiles with the add tile, and the upload status line. The
 *  task page and the Edit form both show it. */
function photoStripHtml(p: PanelHost, task: Task): string {
  const photos = photosOf(task);
  const tiles = photos
    .map((photo, i) => {
      const actions = `<div class="hk-photo-actions">${
        i > 0
          ? `<ha-icon-button class="hk-photo-cover-btn" data-photo-id="${escapeHTML(
              photo.id,
            )}" label="${escapeHTML(t('photos.makeCover'))}"></ha-icon-button>`
          : ''
      }<ha-icon-button class="hk-photo-remove" data-photo-id="${escapeHTML(
        photo.id,
      )}" label="${escapeHTML(t('photos.remove'))}"></ha-icon-button></div>`;
      const badge = i === 0 ? `<span class="hk-photo-badge">${escapeHTML(t('photos.cover'))}</span>` : '';
      return `<div class="hk-photo" data-photo-tile="${escapeHTML(photo.id)}">${photoLink(
        p,
        task,
        photo,
        'hk-photo-link',
        photoImg(p, task, photo, 'hk-photo-img', photo.name),
      )}${badge}${actions}</div>`;
    })
    .join('');
  const key = taskPhotoUploadKey(task.id);
  const add =
    canAddPhoto(task)
      ? `<button type="button" class="hk-photo-add">
          <ha-svg-icon class="hk-photo-add-icon"></ha-svg-icon>
          <span>${escapeHTML(uploadButtonLabel(p, key, t('photos.add')))}</span>
        </button>`
      : '';
  const hint = !photos.length ? `<p class="hk-photo-hint">${escapeHTML(t('photos.empty'))}</p>` : '';
  return `${hint}
        <div class="hk-photo-strip">${tiles}${add}</div>
        <div class="hk-photo-upload-status"></div>`;
}

/** Wire the Photos section: the add tile, the cover and remove buttons, and the
 *  upload progress and error under the strip. */
export function wireTaskPhotos(p: PanelHost, root: ParentNode, task: Task): void {
  const key = taskPhotoUploadKey(task.id);
  const status = root.querySelector<HTMLElement>('.hk-photo-upload-status');
  if (status) renderUploadStatus(p, status, key);
  root.querySelectorAll<HTMLElement>('.hk-photo-add-icon').forEach((el) => setIcon(el, MDI_CAMERA_PLUS));
  root.querySelectorAll<HTMLElement>('.hk-photo-cover-btn').forEach((el) => setIcon(el, MDI_STAR_OUTLINE));
  root.querySelectorAll<HTMLElement>('.hk-photo-remove').forEach((el) => setIcon(el, MDI_DELETE));

  const add = root.querySelector<HTMLElement>('.hk-photo-add');
  if (add) {
    const picker = filePicker(p, add, (file) => void uploadPhoto(p, task.id, file), IMAGE_ACCEPT);
    add.after(picker);
  }
  root.querySelectorAll<HTMLElement>('.hk-photo-cover-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const photoId = btn.dataset.photoId;
      if (photoId) void photoAction(p, () => api.setTaskPhotoCover(p._hass!, task.id, photoId));
    });
  });
  root.querySelectorAll<HTMLElement>('.hk-photo-remove').forEach((btn) => {
    btn.addEventListener('click', () => {
      const photo = photosOf(task).find((x) => x.id === btn.dataset.photoId);
      if (!photo) return;
      openConfirmDialog(p, t('photos.confirmRemove', { name: photo.name }), () => {
        void photoAction(p, () => api.removeTaskPhoto(p._hass!, task.id, photo.id));
      });
    });
  });
}

async function uploadPhoto(p: PanelHost, taskId: string, file: File): Promise<void> {
  const hass = p._hass;
  if (!hass) return;
  const photoId = randomId();
  const task = await runUpload(
    p,
    taskPhotoUploadKey(taskId),
    file,
    (opts) => api.uploadTaskPhoto(hass, taskId, photoId, file, opts),
    MAX_TASK_PHOTO_BYTES,
  );
  if (task) await p._refresh();
}

async function photoAction(p: PanelHost, run: () => Promise<Task>): Promise<void> {
  if (!p._hass) return;
  try {
    await run();
  } catch (err) {
    toast(p, String((err as { message?: string })?.message || err));
  }
  await p._refresh();
}

/** The heading of the form's Photos section, with the "n of 6" count. */
function formPhotosHeading(n: number): HTMLElement {
  const heading = document.createElement('div');
  heading.className = 'hk-eyebrow hk-form-section hk-form-photos-head';
  heading.innerHTML = `${escapeHTML(t('photos.title'))} <span class="hk-section-count">${escapeHTML(
    t('photos.count', { n: String(n), max: String(MAX_TASK_PHOTOS) }),
  )}</span>`;
  return heading;
}

/**
 * The Photos section of the task form, under Basics.
 *
 * - A new task has no id yet, so the photos wait in the browser (`p._edit.photos`)
 *   and upload after Create.
 * - A saved task shows the strip of its task page, and each change takes effect at
 *   once. It reads the stored task, not the draft, so an upload shows at once.
 *
 * Returns null only when the saved task is not loaded yet.
 */
export function formPhotosSection(p: PanelHost, task: Partial<Task>): HTMLElement | null {
  const wrap = document.createElement('div');
  wrap.className = 'hk-form-photos';
  if (task.id) {
    const stored = p._tasks.find((x) => x.id === task.id);
    if (!stored) return null;
    const body = document.createElement('div');
    body.className = 'hk-form-photos-body';
    body.innerHTML = photoStripHtml(p, stored);
    wrap.append(formPhotosHeading(photosOf(stored).length), body);
    wireTaskPhotos(p, body, stored);
    return wrap;
  }
  const list = p._edit.photos ?? [];
  const body = document.createElement('div');
  body.className = 'hk-form-photos-body';
  const add =
    list.length < MAX_TASK_PHOTOS
      ? `<button type="button" class="hk-photo-add hk-staged-add">
          <ha-svg-icon class="hk-photo-add-icon"></ha-svg-icon>
          <span>${escapeHTML(t('photos.add'))}</span>
        </button>`
      : '';
  body.innerHTML = `<div class="hk-photo-strip">${stagedTilesHtml(list, true)}${add}</div>
    <p class="hk-photo-hint hk-staged-help">${escapeHTML(t('photos.stagedHelp'))}</p>`;
  wrap.append(formPhotosHeading(list.length), body);
  body.querySelectorAll<HTMLElement>('.hk-photo-add-icon').forEach((el) => setIcon(el, MDI_CAMERA_PLUS));
  body.querySelectorAll<HTMLElement>('.hk-staged-cover').forEach((el) => setIcon(el, MDI_STAR_OUTLINE));
  body.querySelectorAll<HTMLElement>('.hk-staged-remove').forEach((el) => setIcon(el, MDI_DELETE));
  const addBtn = body.querySelector<HTMLElement>('.hk-staged-add');
  if (addBtn) {
    const picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = STAGED_PHOTO_ACCEPT;
    picker.multiple = true;
    picker.style.display = 'none';
    picker.addEventListener('change', () => {
      const res = stageFiles(p._edit.photos ?? [], Array.from(picker.files ?? []), (f) =>
        URL.createObjectURL(f),
      );
      picker.value = '';
      p._edit.photos = res.list;
      const first = res.rejected[0];
      if (first) toast(p, rejectionMessage(first.file, first.reason));
      p._render();
    });
    addBtn.addEventListener('click', () => picker.click());
    addBtn.after(picker);
  }
  body.querySelectorAll<HTMLElement>('.hk-staged-cover').forEach((btn) => {
    btn.addEventListener('click', () => {
      p._edit.photos = makeStagedCover(p._edit.photos ?? [], btn.dataset.stagedKey ?? '');
      p._render();
    });
  });
  body.querySelectorAll<HTMLElement>('.hk-staged-remove').forEach((btn) => {
    btn.addEventListener('click', () => {
      p._edit.photos = unstage(p._edit.photos ?? [], btn.dataset.stagedKey ?? '', (u) =>
        URL.revokeObjectURL(u),
      );
      p._render();
    });
  });
  return wrap;
}
