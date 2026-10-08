/**
 * The QR label dialog.
 *
 * It opens in 2 ways. The **QR label** button on an appliance or task page opens it
 * for that 1 object, with a preview, the link, Copy and Download PNG. The
 * **Print labels** button on a list opens it with a checklist of what the list shows,
 * so an admin can print many labels on 1 sheet. Both print through the browser: the
 * sheet goes into a hidden iframe, and the browser's dialog gives Print and Save as
 * PDF. The pure part (links, text, layout, SVG) is `qr-labels.ts`.
 */
import { assetMatchesQuery, taskMatchesQuery } from './card-filter';
import { makeDialog } from './dialogs';
import { t, tn } from './i18n';
import type { PanelHost } from './panel-host';
import { LS_LABELS } from './panel-types';
import {
  LABEL_DPIS,
  LABEL_LINES,
  CUSTOM_MAX_MM,
  CUSTOM_MIN_MM,
  LABEL_PAPERS,
  QR_BORDER,
  ROLL_SIZES,
  clampMm,
  clampSkip,
  defaultPaper,
  dotsPerMm,
  fitLabel,
  isRoll,
  labelBaseUrl,
  labelFileName,
  labelLines,
  labelPrintHtml,
  labelSizeMm,
  labelsPerPage,
  labelUrl,
  layoutText,
  parseLabelOpts,
  pngSize,
  qrModules,
  qrPixelPlan,
  qrSvg,
  type LabelLine,
  type LabelOpts,
  type LabelPaper,
  type LabelSource,
  type PrintLabel,
} from './qr-labels';
import type { Asset, Task } from './types';
import {
  areaName,
  assetForTask,
  btnAttrs,
  assetTitle,
  copyText,
  escapeHTML,
  recurrenceSummary,
  setBtnWeight,
  tasksForAsset,
  toast,
} from './utils';

export type LabelKind = 'asset' | 'task';

/** The label dialog's state. `single` is the detail-page form: 1 object, no list. */
export interface LabelDialogState {
  open: boolean;
  kind: LabelKind;
  /** The objects the dialog offers, in list order. */
  ids: string[];
  /** The checked ones. In the single form it is always `ids`. */
  picked: string[];
  single: boolean;
  /** Appliances only: also print a label for each task of the picked appliances. */
  withTasks: boolean;
  skip: number;
}

export function emptyLabelDialog(): LabelDialogState {
  return { open: false, kind: 'asset', ids: [], picked: [], single: false, withTasks: false, skip: 0 };
}

/** Open the dialog for 1 object, from its detail page. */
export function openLabelDialog(p: PanelHost, kind: LabelKind, id: string): void {
  p._labelDialog = { ...emptyLabelDialog(), open: true, kind, ids: [id], picked: [id], single: true };
  p._render();
}

/**
 * Open the dialog with a checklist of what the current list shows: the active or
 * archived appliances, or the tasks, narrowed by the search box. Nothing starts
 * checked, so a print never holds more than the admin chose.
 */
export function openLabelPicker(p: PanelHost): void {
  const devices = p._hass?.devices;
  const areas = p._hass?.areas;
  let ids: string[];
  let kind: LabelKind;
  if (p._view === 'appliances') {
    kind = 'asset';
    const archived = p._assetFilter === 'archived';
    ids = p._assets
      .filter((a) => Boolean(a.archived_at) === archived)
      .filter((a) => !p._query || assetMatchesQuery(a, p._query, devices, areas))
      .sort((a, b) => assetTitle(a, devices).localeCompare(assetTitle(b, devices)))
      .map((a) => a.id);
  } else {
    kind = 'task';
    ids = p._tasks
      .filter((task) => !p._query || taskMatchesQuery(task, p._query, devices, areas))
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((task) => task.id);
  }
  p._labelDialog = { ...emptyLabelDialog(), open: true, kind, ids };
  p._render();
}

function closeLabelDialog(p: PanelHost): void {
  p._labelDialog = emptyLabelDialog();
  p._render();
}

/** The saved paper and text-line choices, or the defaults for this instance. */
function readOpts(p: PanelHost): LabelOpts {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(LS_LABELS);
  } catch {
    // Storage blocked (private window, policy): the defaults stand.
  }
  return parseLabelOpts(raw, defaultPaper(p._hass?.config?.country));
}

function saveOpts(opts: LabelOpts): void {
  try {
    localStorage.setItem(LS_LABELS, JSON.stringify(opts));
  } catch {
    // A choice that does not persist is still used for this print.
  }
}

/** What a label can say about an appliance. */
function assetSource(p: PanelHost, asset: Asset): LabelSource {
  return {
    name: assetTitle(asset, p._hass?.devices),
    model: [asset.manufacturer, asset.model].filter(Boolean).join(' '),
    area: areaName(p._hass?.areas, asset.area_id),
  };
}

/** What a label can say about a task: its appliance stands where a model would. */
function taskSource(p: PanelHost, task: Task): LabelSource {
  const asset = assetForTask(task, p._assets);
  return {
    name: task.name,
    model: asset ? assetTitle(asset, p._hass?.devices) : '',
    area: areaName(p._hass?.areas, task.area_id ?? asset?.area_id),
    schedule: recurrenceSummary(task),
  };
}

interface LabelTarget {
  kind: LabelKind;
  id: string;
  src: LabelSource;
}

/**
 * The objects to print, in order. With "also print tasks", each appliance is
 * followed by its own tasks, and a task that 2 picked appliances share prints once.
 */
function printTargets(p: PanelHost): LabelTarget[] {
  const s = p._labelDialog;
  const out: LabelTarget[] = [];
  const seen = new Set<string>();
  for (const id of s.picked) {
    if (s.kind === 'task') {
      const task = p._tasks.find((x) => x.id === id);
      if (task) out.push({ kind: 'task', id, src: taskSource(p, task) });
      continue;
    }
    const asset = p._assets.find((x) => x.id === id);
    if (!asset) continue;
    out.push({ kind: 'asset', id, src: assetSource(p, asset) });
    if (!s.withTasks || s.single) continue;
    for (const task of tasksForAsset(asset, p._tasks)) {
      if (seen.has(task.id)) continue;
      seen.add(task.id);
      out.push({ kind: 'task', id: task.id, src: taskSource(p, task) });
    }
  }
  return out;
}

/** The link a code holds for 1 object: the HA address and the panel path. */
function targetUrl(p: PanelHost, kind: LabelKind, id: string): string {
  const href = p._hrefFor({
    view: kind === 'asset' ? 'appliances' : 'tasks',
    detail: { kind, id },
  });
  return labelUrl(labelBaseUrl(p._hass?.config, window.location.origin), href);
}

/** The number of distinct tasks the picked appliances have. */
function taskCount(p: PanelHost): number {
  const ids = new Set<string>();
  for (const id of p._labelDialog.picked) {
    const asset = p._assets.find((x) => x.id === id);
    if (asset) for (const task of tasksForAsset(asset, p._tasks)) ids.add(task.id);
  }
  return ids.size;
}

/** The id of the hidden print frame. A spec reads its `srcdoc`. */
export const PRINT_FRAME_ID = 'hk-label-print';

/**
 * Print a sheet through a hidden iframe, so the browser prints only the labels and
 * not the Home Assistant page around the panel. The frame stays until `afterprint`,
 * because Firefox returns from `print()` before its dialog closes.
 */
function printSheet(html: string): void {
  document.getElementById(PRINT_FRAME_ID)?.remove();
  const frame = document.createElement('iframe');
  frame.id = PRINT_FRAME_ID;
  frame.setAttribute('aria-hidden', 'true');
  frame.tabIndex = -1;
  frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;';
  frame.addEventListener('load', () => {
    const win = frame.contentWindow;
    if (!win) return;
    win.addEventListener('afterprint', () => frame.remove());
    // No `win.focus()`: a current browser prints the frame without it, and focus in
    // the hidden frame would leave the dialog deaf to Escape.
    win.print();
  });
  frame.srcdoc = html;
  document.body.appendChild(frame);
}

/**
 * Draw 1 whole label, the code and its text, on a canvas at the chosen density, and save
 * it as a PNG for the app of a label printer. Each module of the code is a whole number
 * of dots (`qrPixelPlan`), so no module prints wider than the next.
 */
async function downloadLabelPng(
  label: PrintLabel,
  opts: LabelOpts,
  filename: string,
): Promise<boolean> {
  try {
    const size = labelSizeMm(opts);
    const rotate = isRoll(opts.paper) && opts.rotate;
    const { width, height } = pngSize(size, opts.dpi, rotate);
    const dpmm = dotsPerMm(opts.dpi);
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return false;
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, width, height);
    if (rotate) {
      ctx.translate(width, 0);
      ctx.rotate(Math.PI / 2);
    }
    const fit = fitLabel(size.w, size.h, label.lines.length > 0);
    const mods = qrModules(label.url);
    const plan = qrPixelPlan(fit.qr, mods.length + QR_BORDER * 2, dpmm);
    const x0 = Math.round(fit.qrX * dpmm) + plan.offset + QR_BORDER * plan.module;
    const y0 = Math.round(fit.qrY * dpmm) + plan.offset + QR_BORDER * plan.module;
    ctx.fillStyle = '#000';
    mods.forEach((row, y) =>
      row.forEach((dark, x) => {
        if (dark) ctx.fillRect(x0 + x * plan.module, y0 + y * plan.module, plan.module, plan.module);
      }),
    );
    if (fit.mode !== 'code') {
      const font = (bold: boolean, sizeMm: number): string =>
        `${bold ? '700' : '400'} ${sizeMm * dpmm}px system-ui, -apple-system, "Segoe UI", sans-serif`;
      const measure = (text: string, bold: boolean, sizeMm: number): number => {
        ctx.font = font(bold, sizeMm);
        return ctx.measureText(text).width / dpmm;
      };
      ctx.textBaseline = 'top';
      const center = fit.mode === 'below';
      ctx.textAlign = center ? 'center' : 'left';
      const x = (center ? fit.textX + fit.textW / 2 : fit.textX) * dpmm;
      for (const row of layoutText(label.lines, fit.textW, fit.textH, measure)) {
        ctx.font = font(row.bold, row.sizeMm);
        ctx.fillText(row.text, x, (fit.textY + row.top) * dpmm);
      }
    }
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'));
    if (!blob) return false;
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 0);
    return true;
  } catch {
    return false;
  }
}

/** The text of 1 paper in the size list. */
function paperName(paper: LabelPaper): string {
  if (paper === 'roll_custom') return t('labels.paper.custom');
  if (isRoll(paper)) return t('labels.paper.roll', ROLL_SIZES[paper]);
  return t(SHEET_KEYS[paper]);
}

const SHEET_KEYS: Record<'letter30' | 'a4_21', string> = {
  letter30: 'labels.paper.letter30',
  a4_21: 'labels.paper.a4_21',
};

const LINE_KEYS: Record<LabelLine, string> = {
  name: 'labels.line.name',
  model: 'labels.line.model',
  area: 'labels.line.area',
  schedule: 'labels.line.schedule',
};

/** Build the label dialog into `host`. */
export function renderLabelDialog(p: PanelHost, host: HTMLElement): void {
  const s = p._labelDialog;
  const opts = readOpts(p);
  const one = s.single ? s.ids[0] : null;
  const oneTarget = one ? printTargets(p)[0] : undefined;
  if (s.single && !oneTarget) return;
  const title = oneTarget ? t('labels.titleOne', { name: oneTarget.src.name }) : t('labels.title');
  const { dialog, body, footer, mount } = makeDialog(title, () => {
    if (p._labelDialog.open) closeLabelDialog(p);
  });
  dialog.classList.add('hk-label-dialog');
  body.classList.add('hk-label-body');

  const parts: string[] = [];
  if (oneTarget) {
    const url = targetUrl(p, oneTarget.kind, oneTarget.id);
    parts.push(`
      <div class="hk-label-preview" data-label-preview>
        <div class="hk-label-qr">${qrSvg(url)}</div>
        <div class="hk-label-text" data-label-text></div>
      </div>
      <label class="hk-label-field">
        <span>${escapeHTML(t('labels.link'))}</span>
        <span class="hk-label-link-row">
          <input class="hk-label-link" data-label-link readonly value="${escapeHTML(url)}">
          <ha-button ${btnAttrs('secondary')} data-label-copy>${escapeHTML(t('labels.copy'))}</ha-button>
        </span>
      </label>`);
  } else {
    const names = s.ids.map((id) => {
      if (s.kind === 'asset') {
        const asset = p._assets.find((x) => x.id === id);
        return asset ? assetTitle(asset, p._hass?.devices) : id;
      }
      return p._tasks.find((x) => x.id === id)?.name ?? id;
    });
    const rows = s.ids
      .map(
        (id, i) => `
        <label class="hk-label-pick">
          <input type="checkbox" data-label-pick="${escapeHTML(id)}"${
            s.picked.includes(id) ? ' checked' : ''
          }>
          <span>${escapeHTML(names[i])}</span>
        </label>`,
      )
      .join('');
    parts.push(`
      <div class="hk-label-list-head">
        <span class="hk-eyebrow">${escapeHTML(
          t(s.kind === 'asset' ? 'labels.pickAppliances' : 'labels.pickTasks'),
        )}</span>
        <ha-button ${btnAttrs('tertiary')} data-label-all>${escapeHTML(t('labels.selectAll'))}</ha-button>
        <ha-button ${btnAttrs('tertiary')} data-label-none>${escapeHTML(t('labels.selectNone'))}</ha-button>
      </div>
      ${
        s.ids.length
          ? `<div class="hk-label-list">${rows}</div>`
          : `<ha-alert alert-type="info">${escapeHTML(t('labels.nothingListed'))}</ha-alert>`
      }
      ${
        s.kind === 'asset'
          ? `<label class="hk-label-check">
              <input type="checkbox" data-label-with-tasks${s.withTasks ? ' checked' : ''}>
              <span data-label-with-tasks-text></span>
            </label>`
          : ''
      }`);
  }
  const paperOpts = LABEL_PAPERS.map(
    (paper) =>
      `<option value="${paper}"${paper === opts.paper ? ' selected' : ''}>${escapeHTML(
        paperName(paper),
      )}</option>`,
  ).join('');
  const dpiOpts = LABEL_DPIS.map(
    (dpi) =>
      `<option value="${dpi}"${dpi === opts.dpi ? ' selected' : ''}>${escapeHTML(
        t('labels.dpiOption', { dpi, dots: Math.round(dotsPerMm(dpi)) }),
      )}</option>`,
  ).join('');
  const lineBoxes = LABEL_LINES.map(
    (line) => `
      <label class="hk-label-check">
        <input type="checkbox" data-label-line="${line}"${opts.lines.includes(line) ? ' checked' : ''}>
        <span>${escapeHTML(t(LINE_KEYS[line]))}</span>
      </label>`,
  ).join('');
  parts.push(`
    <div class="hk-label-grid">
      <label class="hk-label-field">
        <span>${escapeHTML(t('labels.sheet'))}</span>
        <select data-label-paper>${paperOpts}</select>
      </label>
      <label class="hk-label-field" data-label-skip-field>
        <span>${escapeHTML(t('labels.skip'))}</span>
        <input type="number" min="0" step="1" inputmode="numeric" data-label-skip value="${s.skip}">
      </label>
      <label class="hk-label-field" data-label-custom-field>
        <span>${escapeHTML(t('labels.width'))}</span>
        <input type="number" min="${CUSTOM_MIN_MM}" max="${CUSTOM_MAX_MM}" step="0.1"
          inputmode="decimal" data-label-custom-w value="${opts.customW}">
      </label>
      <label class="hk-label-field" data-label-custom-field>
        <span>${escapeHTML(t('labels.height'))}</span>
        <input type="number" min="${CUSTOM_MIN_MM}" max="${CUSTOM_MAX_MM}" step="0.1"
          inputmode="decimal" data-label-custom-h value="${opts.customH}">
      </label>
      ${
        oneTarget
          ? `<label class="hk-label-field">
              <span>${escapeHTML(t('labels.dpi'))}</span>
              <select data-label-dpi>${dpiOpts}</select>
            </label>`
          : ''
      }
    </div>
    <label class="hk-label-check" data-label-rotate-field>
      <input type="checkbox" data-label-rotate${opts.rotate ? ' checked' : ''}>
      <span>${escapeHTML(t('labels.rotate'))}</span>
    </label>
    <fieldset class="hk-label-lines">
      <legend class="hk-eyebrow">${escapeHTML(t('labels.lines'))}</legend>
      ${lineBoxes}
    </fieldset>
    <p class="hk-label-hint" data-label-hint></p>`);
  body.innerHTML = parts.join('');

  const print = document.createElement('ha-button');
  print.setAttribute('slot', 'primaryAction');
  print.setAttribute('data-label-print', '');
  setBtnWeight(print, 'primary');

  const sync = (): void => {
    const now = readOpts(p);
    const count = printTargets(p).length;
    print.textContent = tn('labels.print', count);
    print.toggleAttribute('disabled', count === 0);
    const roll = isRoll(now.paper);
    const skip = body.querySelector<HTMLInputElement>('[data-label-skip]');
    if (skip) skip.max = String(labelsPerPage(now.paper) - 1);
    // A roll has 1 label on each page, so nothing is used up; a sheet does not turn.
    const show = (sel: string, on: boolean): void =>
      body.querySelectorAll<HTMLElement>(sel).forEach((el) => {
        el.hidden = !on;
      });
    show('[data-label-skip-field]', !roll);
    show('[data-label-custom-field]', now.paper === 'roll_custom');
    show('[data-label-rotate-field]', roll);
    const hint = body.querySelector<HTMLElement>('[data-label-hint]');
    if (hint) hint.textContent = t(roll ? 'labels.printHintRoll' : 'labels.printHint');
    const text = body.querySelector<HTMLElement>('[data-label-text]');
    if (text && oneTarget) {
      text.innerHTML = labelLines(oneTarget.src, now.lines)
        .map((line, i) => `<div class="${i === 0 ? 'hk-label-l1' : ''}">${escapeHTML(line)}</div>`)
        .join('');
    }
    const withText = body.querySelector<HTMLElement>('[data-label-with-tasks-text]');
    if (withText) withText.textContent = tn('labels.withTasks', taskCount(p));
  };

  body.querySelectorAll<HTMLInputElement>('[data-label-pick]').forEach((box) => {
    box.addEventListener('change', () => {
      const id = box.dataset.labelPick!;
      const picked = new Set(p._labelDialog.picked);
      if (box.checked) picked.add(id);
      else picked.delete(id);
      // Kept in list order, so the sheet reads like the list.
      p._labelDialog.picked = p._labelDialog.ids.filter((x) => picked.has(x));
      sync();
    });
  });
  const setAll = (on: boolean): void => {
    p._labelDialog.picked = on ? [...p._labelDialog.ids] : [];
    body.querySelectorAll<HTMLInputElement>('[data-label-pick]').forEach((box) => {
      box.checked = on;
    });
    sync();
  };
  body.querySelector('[data-label-all]')?.addEventListener('click', () => setAll(true));
  body.querySelector('[data-label-none]')?.addEventListener('click', () => setAll(false));
  body
    .querySelector<HTMLInputElement>('[data-label-with-tasks]')
    ?.addEventListener('change', (e) => {
      p._labelDialog.withTasks = (e.target as HTMLInputElement).checked;
      sync();
    });
  body.querySelector<HTMLSelectElement>('[data-label-paper]')?.addEventListener('change', (e) => {
    const paper = (e.target as HTMLSelectElement).value as LabelOpts['paper'];
    saveOpts({ ...readOpts(p), paper });
    sync();
  });
  const customInput = (sel: string, key: 'customW' | 'customH'): void => {
    body.querySelector<HTMLInputElement>(sel)?.addEventListener('change', (e) => {
      const input = e.target as HTMLInputElement;
      const now = readOpts(p);
      const mm = clampMm(input.valueAsNumber, now[key]);
      input.value = String(mm);
      saveOpts({ ...now, [key]: mm });
      sync();
    });
  };
  customInput('[data-label-custom-w]', 'customW');
  customInput('[data-label-custom-h]', 'customH');
  body.querySelector<HTMLInputElement>('[data-label-rotate]')?.addEventListener('change', (e) => {
    saveOpts({ ...readOpts(p), rotate: (e.target as HTMLInputElement).checked });
  });
  body.querySelector<HTMLSelectElement>('[data-label-dpi]')?.addEventListener('change', (e) => {
    const dpi = Number((e.target as HTMLSelectElement).value);
    const now = readOpts(p);
    saveOpts({ ...now, dpi: LABEL_DPIS.find((d) => d === dpi) ?? now.dpi });
  });
  body.querySelector<HTMLInputElement>('[data-label-skip]')?.addEventListener('change', (e) => {
    const input = e.target as HTMLInputElement;
    p._labelDialog.skip = clampSkip(readOpts(p).paper, Number(input.value));
    input.value = String(p._labelDialog.skip);
  });
  body.querySelectorAll<HTMLInputElement>('[data-label-line]').forEach((box) => {
    box.addEventListener('change', () => {
      const on = new Set(
        [...body.querySelectorAll<HTMLInputElement>('[data-label-line]')]
          .filter((b) => b.checked)
          .map((b) => b.dataset.labelLine as LabelLine),
      );
      saveOpts({ ...readOpts(p), lines: LABEL_LINES.filter((line) => on.has(line)) });
      sync();
    });
  });
  if (oneTarget) {
    const url = targetUrl(p, oneTarget.kind, oneTarget.id);
    body.querySelector('[data-label-copy]')?.addEventListener('click', async () => {
      toast(p, t((await copyText(url)) ? 'labels.copied' : 'labels.copyFailed'));
    });
    const png = document.createElement('ha-button');
    png.setAttribute('slot', 'secondaryAction');
    png.setAttribute('data-label-png', '');
    setBtnWeight(png, 'secondary');
    png.textContent = t('labels.downloadPng');
    png.addEventListener('click', async () => {
      const now = readOpts(p);
      const label = { url, lines: labelLines(oneTarget.src, now.lines) };
      const ok = await downloadLabelPng(label, now, labelFileName(oneTarget.kind, oneTarget.src.name));
      if (!ok) toast(p, t('labels.pngFailed'));
    });
    footer.appendChild(png);
  }

  print.addEventListener('click', () => {
    const now = readOpts(p);
    const labels: PrintLabel[] = printTargets(p).map((target) => ({
      url: targetUrl(p, target.kind, target.id),
      lines: labelLines(target.src, now.lines),
    }));
    if (!labels.length) return;
    printSheet(labelPrintHtml(labels, now, p._labelDialog.skip, t('labels.title')));
  });
  footer.appendChild(print);

  const close = document.createElement('ha-button');
  close.setAttribute('slot', 'secondaryAction');
  close.setAttribute('data-label-close', '');
  setBtnWeight(close, 'tertiary');
  close.textContent = t('btn.close');
  close.addEventListener('click', () => closeLabelDialog(p));
  footer.appendChild(close);

  sync();
  mount();
  host.appendChild(dialog);
}
