/**
 * The file-upload pipeline behind the appliance editor: the size pre-check, the
 * progress bar, the failure messages, and the hidden file input every upload button
 * opens. One upload runs at a time (`_assetEdit.upload` is the single slot), so the
 * whole pipeline is a set of free functions over a `PanelHost` (see `panel-host.ts`)
 * rather than an object of its own.
 *
 * `setAssetError` and `errorAlert` live here too, with the pipeline that raises them
 * rather than with the editors that also show them: an upload failure has to clear the
 * form-level error, and this module sits *below* `panel-asset-editors.ts` in the import
 * graph. Everything here is deliberately ignorant of documents and parts — the editors
 * call in, never the other way round.
 */

import * as api from './api';
import { formatBytes } from './documents';
import { t } from './i18n';
import { MAX_DOCUMENT_BYTES } from './limits';
import type { PanelHost } from './panel-host';
import { DOCS_UPLOAD_413_URL } from './panel-icons';
import { UPLOAD_BAR_DELAY_MS, type UploadState } from './panel-types';
import { setBtnWeight, toast } from './utils';

/** What an upload control will accept — the types the backend stores (see
 *  `MAX_DOCUMENT_BYTES` for how much of one). Written once: both pickers offered a
 *  different list the day one of them was edited alone. */
export const UPLOAD_ACCEPT = 'application/pdf,image/png,image/jpeg,image/webp,image/gif';

/** Set (or clear) the appliance-form error, plus an optional "Learn more" link. */
export function setAssetError(p: PanelHost, message?: string, link?: string): void {
  p._assetEdit.error = message;
  p._assetEdit.errorLink = link;
}

/** An error alert with an optional "Learn more" link. */
export function errorAlert(message: string, link?: string): HTMLElement {
  const err = document.createElement('ha-alert');
  err.setAttribute('alert-type', 'error');
  err.textContent = message;
  if (link) {
    const a = document.createElement('a');
    a.href = link;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = t('btn.learnMore');
    a.style.marginInlineStart = '8px';
    err.appendChild(a);
  }
  return err;
}

/**
 * The hidden `<input type="file">` behind an upload button: *button* opens it, a pick
 * calls *onFile*, and the input is reset so picking the same file twice still fires.
 * The button is disabled while any upload is in flight — only one runs at a time.
 *
 * Returns the input for the caller to place in the DOM (it must be in the tree for the
 * click to reach it; `display:none` keeps it out of the layout).
 */
export function filePicker(
  p: PanelHost,
  button: HTMLElement,
  onFile: (file: File) => void,
): HTMLInputElement {
  const picker = document.createElement('input');
  picker.type = 'file';
  picker.accept = UPLOAD_ACCEPT;
  picker.style.display = 'none';
  picker.addEventListener('change', () => {
    const file = picker.files?.[0];
    if (file) onFile(file);
    picker.value = '';
  });
  button.addEventListener('click', () => picker.click());
  if (p._assetEdit.upload) button.setAttribute('disabled', '');
  return picker;
}

/**
 * Run an upload with a size pre-check, progress reporting and visible failures.
 *
 * Shared by the appliance-documents and part-file controls so both behave
 * identically. Returns the upload's result, or `undefined` if it failed or was
 * cancelled — the caller only grafts its own state on success.
 */
export async function runUpload<T>(
  p: PanelHost,
  key: string,
  file: File,
  run: (opts: api.UploadOptions) => Promise<T>,
): Promise<T | undefined> {
  // A previous failure is stale the moment a new upload starts.
  p._assetEdit.uploadError = undefined;
  setAssetError(p, undefined);

  // Refuse an oversized file *here*: uploading 30 MB just to have the backend 413 it
  // wastes minutes, and on a slow link looks like a hang.
  const tooLarge = uploadSizeError(file);
  if (tooLarge) {
    failUpload(p, key, tooLarge);
    return undefined;
  }

  p._assetEdit.upload = {
    key,
    filename: file.name,
    loaded: 0,
    total: file.size,
    indeterminate: true,
    sent: false,
    visible: false,
  };
  p._uploadAbort = new AbortController();
  // Small files finish before this fires, so they never flash a progress bar — the
  // disabled "Uploading…" button is the only affordance they need.
  p._uploadShowTimer = setTimeout(() => {
    if (p._assetEdit.upload) {
      p._assetEdit.upload.visible = true;
      p._render();
    }
  }, UPLOAD_BAR_DELAY_MS);
  p._render();

  try {
    const result = await run({
      onProgress: (progress) => onUploadProgress(p, key, progress),
      signal: p._uploadAbort.signal,
    });
    toast(p, t('doc.uploadComplete', { name: file.name }));
    return result;
  } catch (err) {
    const e = err as api.UploadError;
    // A cancellation is the user's own doing — no error to report.
    if (!e?.aborted) {
      const { message, link } = uploadErrorMessage(e, file);
      failUpload(p, key, message, link);
    }
    return undefined;
  } finally {
    if (p._uploadShowTimer) clearTimeout(p._uploadShowTimer);
    p._uploadShowTimer = undefined;
    p._uploadAbort = undefined;
    p._assetEdit.upload = undefined;
    p._render();
  }
}

/** The pre-check message for a file over the shared ceiling, else undefined. */
function uploadSizeError(file: File): string | undefined {
  if (file.size <= MAX_DOCUMENT_BYTES) return undefined;
  return t('doc.uploadTooLargeLocal', {
    name: file.name,
    size: formatBytes(file.size),
    limit: formatBytes(MAX_DOCUMENT_BYTES),
  });
}

/** Map an upload failure onto localized user-facing text (plus an optional docs link). */
function uploadErrorMessage(e: api.UploadError, file: File): { message: string; link?: string } {
  // A 413 with no Home Keeper message body means a reverse proxy in front of HA
  // rejected the upload (its request-body limit) — guide the user to the fix.
  if (e?.status === 413 && !e.serverMessage) {
    return { message: t('doc.uploadTooLargeProxy'), link: DOCS_UPLOAD_413_URL };
  }
  if (!e?.status) {
    // No HTTP status at all. If the body was still going out, the connection was cut
    // mid-upload — classically a proxy body limit, which closes rather than replying,
    // so the browser never sees the 413. Offer that fix without asserting it.
    if ((e?.bytesSent ?? 0) > 0 && e.bytesSent! < file.size) {
      return { message: t('doc.uploadNetworkOrProxy'), link: DOCS_UPLOAD_413_URL };
    }
    return { message: t('doc.uploadNetworkError') };
  }
  return { message: t('doc.uploadFailed', { error: String(e?.message ?? '') }) };
}

/** Report an upload failure where the user is actually looking: inline next to the
 *  control, plus HA's toast (viewport-fixed, so it can't scroll out of sight). */
function failUpload(p: PanelHost, key: string, message: string, link?: string): void {
  p._assetEdit.uploadError = { key, message, link };
  toast(p, message);
  p._scrollToError = key;
  p._render();
}

/** Patch the live progress bar in place. Deliberately does *not* re-render: a render
 *  replaces the whole shadow root, which would thrash on every progress event. */
function onUploadProgress(p: PanelHost, key: string, progress: api.UploadProgress): void {
  const state = p._assetEdit.upload;
  if (!state || state.key !== key) return;
  const before = uploadPercent(state);
  Object.assign(state, {
    loaded: progress.loaded,
    total: progress.total || state.total,
    indeterminate: progress.indeterminate,
    sent: progress.sent,
  });
  // Whole-percent changes only; a large upload fires progress events far more often
  // than the bar can meaningfully move.
  if (!progress.sent && uploadPercent(state) === before) return;
  const host = p.shadowRoot?.getElementById('hk-upload');
  // Gone — a re-render happened. State is authoritative; the next render rebuilds it.
  if (!host) return;
  applyUploadProgress(host, state);
}

/** Percent complete, or undefined while indeterminate. */
function uploadPercent(state: UploadState): number | undefined {
  if (state.indeterminate || !state.total) return undefined;
  return Math.min(100, Math.round((state.loaded / state.total) * 100));
}

/** Write a progress state onto an existing bar (shared by first render and updates). */
function applyUploadProgress(host: HTMLElement, state: UploadState): void {
  const pct = uploadPercent(state);
  const track = host.querySelector('.hk-upload-track');
  const fill = host.querySelector<HTMLElement>('.hk-upload-fill');
  const label = host.querySelector('.hk-upload-label');
  const bar = host.querySelector('#hk-upload-bar');
  if (track) track.classList.toggle('indeterminate', pct === undefined);
  if (fill && pct !== undefined) fill.style.width = `${pct}%`;
  if (bar) {
    // Screen readers announce a determinate bar by value; while indeterminate there
    // is no value to announce, so drop it and mark the region busy instead.
    if (pct === undefined) {
      bar.removeAttribute('aria-valuenow');
      bar.setAttribute('aria-busy', 'true');
    } else {
      bar.setAttribute('aria-valuenow', String(pct));
      bar.removeAttribute('aria-busy');
    }
  }
  if (label) label.textContent = uploadLabel(state);
}

/** The line under the bar: "manual.pdf · 42% · 4.2 MB of 10 MB", or a phase message
 *  while there's no percentage to show. */
function uploadLabel(state: UploadState): string {
  if (state.sent) return t('doc.uploadFinishing', { name: state.filename });
  const pct = uploadPercent(state);
  if (pct === undefined) return t('doc.uploadPreparing', { name: state.filename });
  return t('doc.uploadProgress', {
    name: state.filename,
    pct: String(pct),
    done: formatBytes(state.loaded),
    total: formatBytes(state.total),
  });
}

/** Render the progress bar and/or the inline error for one upload control. Called
 *  from both upload call sites so they stay identical. */
export function renderUploadStatus(p: PanelHost, host: HTMLElement, key: string): void {
  const state = p._assetEdit.upload;
  if (state?.key === key && state.visible) {
    const wrap = document.createElement('div');
    wrap.className = 'hk-upload';
    wrap.id = 'hk-upload';
    const bar = document.createElement('div');
    bar.id = 'hk-upload-bar';
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-valuemin', '0');
    bar.setAttribute('aria-valuemax', '100');
    bar.setAttribute('aria-label', t('doc.uploadPreparing', { name: state.filename }));
    const track = document.createElement('div');
    track.className = 'hk-upload-track';
    const fill = document.createElement('div');
    fill.className = 'hk-upload-fill';
    track.appendChild(fill);
    bar.appendChild(track);
    // No aria-live on the bar: announcing every percent tick would flood a screen
    // reader. The completion toast and the role="alert" error carry the outcome.
    const label = document.createElement('div');
    label.className = 'hk-upload-label';
    const cancel = document.createElement('ha-button');
    setBtnWeight(cancel, 'tertiary');
    cancel.textContent = t('btn.cancelUpload');
    // Safe at any point: the backend only writes the blob once the whole body has
    // been parsed, so an aborted upload leaves nothing behind.
    cancel.addEventListener('click', () => p._uploadAbort?.abort());
    wrap.append(bar, label, cancel);
    applyUploadProgress(wrap, state);
    host.appendChild(wrap);
  }
  const failure = p._assetEdit.uploadError;
  if (failure?.key === key) {
    const alert = errorAlert(failure.message, failure.link);
    alert.id = `hk-upload-err-${key}`;
    host.appendChild(alert);
  }
}

/** An upload button reads "Uploading…" while it owns the in-flight upload. Every
 *  upload button is disabled meanwhile — only one upload runs at a time. */
export function uploadButtonLabel(p: PanelHost, key: string, idle: string): string {
  return p._assetEdit.upload?.key === key ? t('btn.uploading') : idle;
}
