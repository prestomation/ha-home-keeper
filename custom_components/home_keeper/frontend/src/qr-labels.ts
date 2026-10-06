/**
 * QR code labels: the pure part.
 *
 * A label holds a QR code of a panel deep link (`/home-keeper/appliances/<id>` or
 * `/home-keeper/tasks/<id>`) and a few lines of text. The panel prints a sheet of them
 * through the browser's own print dialog, so this module only makes strings: the
 * link, the text lines, the QR code as SVG and the whole print document.
 * `panel-labels.ts` owns the dialog and the DOM.
 */
import { qrcodegen } from './qrcodegen';
import { escapeHTML } from './utils';

/** The text lines an admin can put on a label, in the order they print. */
export const LABEL_LINES = ['name', 'model', 'area', 'schedule'] as const;
export type LabelLine = (typeof LABEL_LINES)[number];

/** The stock label sheets the panel can print: many labels on 1 page. */
export const SHEET_PAPERS = ['letter30', 'a4_21'] as const;
export type SheetPaper = (typeof SHEET_PAPERS)[number];

/**
 * The label rolls of a label printer: 1 label on each page, at the size of the label.
 * `roll_custom` takes its size from `LabelOpts.customW` and `customH`.
 */
export const ROLL_PAPERS = [
  'roll_50x30',
  'roll_40x30',
  'roll_50x20',
  'roll_30x15',
  'roll_custom',
] as const;
export type RollPaper = (typeof ROLL_PAPERS)[number];

/** Every paper the panel can print, sheets first. */
export const LABEL_PAPERS = [...SHEET_PAPERS, ...ROLL_PAPERS] as const;
export type LabelPaper = SheetPaper | RollPaper;

/** The size of each preset roll label, in mm: the common rolls of small label printers. */
export const ROLL_SIZES: Record<Exclude<RollPaper, 'roll_custom'>, { w: number; h: number }> = {
  roll_50x30: { w: 50, h: 30 },
  roll_40x30: { w: 40, h: 30 },
  roll_50x20: { w: 50, h: 20 },
  roll_30x15: { w: 30, h: 15 },
};

/** The limits of a custom label size, in mm. */
export const CUSTOM_MIN_MM = 10;
export const CUSTOM_MAX_MM = 300;
/** The custom size before the admin types one: the most common roll. */
export const CUSTOM_DEFAULT = { w: 50, h: 30 } as const;

/** True for a label roll, false for a sheet. */
export function isRoll(paper: LabelPaper): paper is RollPaper {
  return (ROLL_PAPERS as readonly string[]).includes(paper);
}

/** A custom size in mm: rounded to 0.1 mm and kept inside the limits. */
export function clampMm(value: number, fallback: number): number {
  if (!Number.isFinite(value)) return fallback;
  const mm = Math.round(value * 10) / 10;
  return Math.min(Math.max(mm, CUSTOM_MIN_MM), CUSTOM_MAX_MM);
}

/**
 * The pixel densities of a PNG, in dots per inch. 203 dpi is 8 dots per mm, the
 * density of most small thermal label printers. 300 dpi is about 12 dots per mm.
 */
export const LABEL_DPIS = [203, 300] as const;
export type LabelDpi = (typeof LABEL_DPIS)[number];

/** The dots in 1 mm at `dpi`. */
export function dotsPerMm(dpi: LabelDpi): number {
  return dpi / 25.4;
}

/**
 * The geometry of 1 label sheet, in `unit`. The positions are those of the common
 * stock sheets: Avery 5160 (US Letter, 30 labels of 2⅝ × 1 in) and Avery L7160 (A4,
 * 21 labels of 63.5 × 38.1 mm). Other brands sell the same layouts under their own
 * numbers.
 */
export interface LabelLayout {
  unit: 'in' | 'mm';
  pageSize: string;
  pageW: number;
  pageH: number;
  cols: number;
  rows: number;
  labelW: number;
  labelH: number;
  top: number;
  left: number;
  pitchX: number;
  pitchY: number;
  pad: number;
}

export const LAYOUTS: Record<SheetPaper, LabelLayout> = {
  letter30: {
    unit: 'in',
    pageSize: 'letter',
    pageW: 8.5,
    pageH: 11,
    cols: 3,
    rows: 10,
    labelW: 2.625,
    labelH: 1,
    top: 0.5,
    left: 0.1875,
    pitchX: 2.75,
    pitchY: 1,
    pad: 0.06,
  },
  a4_21: {
    unit: 'mm',
    pageSize: 'A4',
    pageW: 210,
    pageH: 297,
    cols: 3,
    rows: 7,
    labelW: 63.5,
    labelH: 38.1,
    top: 15.15,
    left: 7.21,
    pitchX: 66.04,
    pitchY: 38.1,
    pad: 1.6,
  },
};

/** The number of labels on 1 page of `paper`. A roll has 1 label on each page. */
export function labelsPerPage(paper: LabelPaper): number {
  if (isRoll(paper)) return 1;
  const l = LAYOUTS[paper];
  return l.cols * l.rows;
}

/** Countries where Letter paper is the norm. Everywhere else gets A4 first. */
const LETTER_COUNTRIES = new Set(['US', 'CA', 'MX', 'PH']);

/** The sheet to offer first, from the Home Assistant country setting. */
export function defaultPaper(country: string | null | undefined): SheetPaper {
  return country && LETTER_COUNTRIES.has(country.toUpperCase()) ? 'letter30' : 'a4_21';
}

/**
 * The address a printed code starts with.
 *
 * A label outlives the browser tab that printed it, so the code prefers the address
 * Home Assistant is set to be reached at: the external URL, then the internal URL.
 * Only an instance with neither falls back to the address this browser uses now.
 */
export function labelBaseUrl(
  config: { external_url?: string | null; internal_url?: string | null } | undefined,
  origin: string,
): string {
  const base = config?.external_url || config?.internal_url || origin;
  return base.replace(/\/+$/, '');
}

/** The whole link in a code: the base address and the panel path (`p._hrefFor`). */
export function labelUrl(base: string, href: string): string {
  return base + (href.startsWith('/') ? href : `/${href}`);
}

/** The facts a label can show, already resolved to text by the caller. */
export interface LabelSource {
  name: string;
  model?: string;
  area?: string;
  schedule?: string;
}

/** The text lines of 1 label: the chosen lines that have a value, in print order. */
export function labelLines(src: LabelSource, chosen: readonly LabelLine[]): string[] {
  return LABEL_LINES.filter((line) => chosen.includes(line))
    .map((line) => (src[line] ?? '').trim())
    .filter((text) => text !== '');
}

/** The saved choices of the label dialog. */
export interface LabelOpts {
  paper: LabelPaper;
  lines: LabelLine[];
  /** The size of a `roll_custom` label, in mm. */
  customW: number;
  customH: number;
  /** The pixel density of Download PNG. */
  dpi: LabelDpi;
  /** Turn a roll label 90° clockwise, for a printer that feeds the roll the short way. */
  rotate: boolean;
}

/** The defaults of the label dialog, with the first paper from the HA country. */
export function defaultLabelOpts(fallbackPaper: LabelPaper): LabelOpts {
  return {
    paper: fallbackPaper,
    lines: [...LABEL_LINES],
    customW: CUSTOM_DEFAULT.w,
    customH: CUSTOM_DEFAULT.h,
    dpi: 203,
    rotate: false,
  };
}

/**
 * Read the saved choices, or the defaults. The value comes from `localStorage`, which
 * any old version or another tab can have written, so every part is checked and an
 * unknown value reads as the default.
 */
export function parseLabelOpts(raw: string | null, fallbackPaper: LabelPaper): LabelOpts {
  const dflt = defaultLabelOpts(fallbackPaper);
  if (!raw) return dflt;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return dflt;
  }
  if (!data || typeof data !== 'object') return dflt;
  const obj = data as Record<string, unknown>;
  const paper = LABEL_PAPERS.includes(obj.paper as LabelPaper)
    ? (obj.paper as LabelPaper)
    : fallbackPaper;
  const lines = Array.isArray(obj.lines)
    ? LABEL_LINES.filter((line) => (obj.lines as unknown[]).includes(line))
    : dflt.lines;
  const mm = (value: unknown, fallback: number): number =>
    typeof value === 'number' ? clampMm(value, fallback) : fallback;
  return {
    paper,
    lines,
    customW: mm(obj.customW, dflt.customW),
    customH: mm(obj.customH, dflt.customH),
    dpi: LABEL_DPIS.includes(obj.dpi as LabelDpi) ? (obj.dpi as LabelDpi) : dflt.dpi,
    rotate: obj.rotate === true,
  };
}

/**
 * The size of 1 label of `opts.paper` in mm, as the label is read (before a rotation).
 * A sheet gives the size of its die-cut label.
 */
export function labelSizeMm(opts: LabelOpts): { w: number; h: number } {
  const { paper } = opts;
  if (paper === 'roll_custom') return { w: opts.customW, h: opts.customH };
  if (isRoll(paper)) return { ...ROLL_SIZES[paper] };
  const l = LAYOUTS[paper];
  const k = l.unit === 'in' ? 25.4 : 1;
  return { w: l.labelW * k, h: l.labelH * k };
}

/**
 * The modules of the QR code for `text`, as rows of booleans (true is dark), with no
 * quiet zone. Error correction is level M, which still reads with a scuffed corner.
 */
export function qrModules(text: string): boolean[][] {
  const qr = qrcodegen.QrCode.encodeText(text, qrcodegen.QrCode.Ecc.MEDIUM);
  const rows: boolean[][] = [];
  for (let y = 0; y < qr.size; y++) {
    const row: boolean[] = [];
    for (let x = 0; x < qr.size; x++) row.push(qr.getModule(x, y));
    rows.push(row);
  }
  return rows;
}

/** The quiet zone around a code, in modules. The standard asks for 4; a label has
 *  white space around the code already, so 2 is enough and keeps the code larger. */
export const QR_BORDER = 2;

/**
 * The QR code for `text` as a standalone SVG string, 1 unit per module.
 *
 * The colors are literal black on white on purpose. A code is printed or scanned, and
 * a theme color (a dark theme's light text) would make a code no phone can read.
 */
export function qrSvg(text: string): string {
  const mods = qrModules(text);
  const n = mods.length + QR_BORDER * 2;
  let path = '';
  mods.forEach((row, y) =>
    row.forEach((dark, x) => {
      if (dark) path += `M${x + QR_BORDER} ${y + QR_BORDER}h1v1h-1z`;
    }),
  );
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${n} ${n}" ` +
    `shape-rendering="crispEdges"><rect width="${n}" height="${n}" fill="#fff"/>` +
    `<path d="${path}" fill="#000"/></svg>`
  );
}

/** 1 label to print: its link and its text lines. */
export interface PrintLabel {
  url: string;
  lines: string[];
}

/** A length for CSS: at most 4 decimals, so float noise never reaches the sheet. */
export function cssNum(value: number): string {
  return String(Math.round(value * 10000) / 10000);
}

/** Where label number `index` (counting the skipped positions) lands. */
export function labelSlot(
  paper: SheetPaper,
  index: number,
): { page: number; row: number; col: number } {
  const l = LAYOUTS[paper];
  const per = l.cols * l.rows;
  const onPage = index % per;
  return { page: Math.floor(index / per), row: Math.floor(onPage / l.cols), col: onPage % l.cols };
}

/** Clamp the "skip used labels" number to 0 … (labels per page − 1). */
export function clampSkip(paper: LabelPaper, skip: number): number {
  if (!Number.isFinite(skip)) return 0;
  return Math.min(Math.max(Math.floor(skip), 0), labelsPerPage(paper) - 1);
}

/**
 * The whole print document for `labels` on `paper`, leaving the first `skip`
 * positions of the first sheet empty for a sheet that is already part used.
 *
 * Every position is absolute, in the sheet's own unit, so the labels land on the
 * die-cut shapes when the browser prints at 100% with no margins. All label text is
 * escaped: a name is user text.
 */
export function labelSheetHtml(
  labels: PrintLabel[],
  paper: SheetPaper,
  skip: number,
  title: string,
): string {
  const l = LAYOUTS[paper];
  const u = l.unit;
  const first = clampSkip(paper, skip);
  // The code fills the label height, but never more than 45% of its width, so the text
  // keeps room for a name of a few words.
  const qr = cssNum(Math.min(l.labelH - l.pad * 2, l.labelW * 0.45));
  const pages: string[][] = [];
  labels.forEach((label, i) => {
    const slot = labelSlot(paper, first + i);
    while (pages.length <= slot.page) pages.push([]);
    const x = cssNum(l.left + slot.col * l.pitchX);
    const y = cssNum(l.top + slot.row * l.pitchY);
    const text = label.lines
      .map((line, j) => `<div class="${j === 0 ? 'l1' : 'ln'}">${escapeHTML(line)}</div>`)
      .join('');
    pages[slot.page].push(
      `<div class="label" style="left:${x}${u};top:${y}${u}">` +
        `<div class="qr">${qrSvg(label.url)}</div><div class="text">${text}</div></div>`,
    );
  });
  const body = pages.map((cells) => `<div class="page">${cells.join('')}</div>`).join('');
  const css =
    `@page{size:${l.pageSize};margin:0}` +
    `*{box-sizing:border-box}html,body{margin:0;padding:0}` +
    `body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#000;background:#fff}` +
    `.page{position:relative;width:${l.pageW}${u};height:${l.pageH}${u};overflow:hidden;` +
    `break-after:page}.page:last-child{break-after:auto}` +
    `.label{position:absolute;width:${l.labelW}${u};height:${l.labelH}${u};` +
    `padding:${l.pad}${u};display:flex;gap:${cssNum(l.pad * 1.5)}${u};align-items:center;overflow:hidden}` +
    `.qr{flex:0 0 ${qr}${u};width:${qr}${u};height:${qr}${u}}.qr svg{display:block;width:100%;height:100%}` +
    `.text{min-width:0;display:flex;flex-direction:column;gap:1pt;overflow:hidden}` +
    `.l1,.ln{display:-webkit-box;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}` +
    `.l1{font-weight:700;font-size:8.5pt;line-height:1.15;-webkit-line-clamp:3}` +
    `.ln{font-size:7pt;line-height:1.2;-webkit-line-clamp:2}`;
  return (
    `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHTML(title)}</title>` +
    `<style>${css}</style></head><body>${body}</body></html>`
  );
}

/** How a label holds its code and its text. */
export type LabelFitMode = 'side' | 'below' | 'code';

/** Where the code and the text go on 1 label, in mm from its top-left corner. */
export interface LabelFit {
  mode: LabelFitMode;
  qr: number;
  qrX: number;
  qrY: number;
  textX: number;
  textY: number;
  textW: number;
  textH: number;
}

/** The space around the content of a roll label and between the code and the text, mm. */
export const FIT_PAD = 1.5;
export const FIT_GAP = 1.5;
/** The smallest text box worth printing, and the smallest code next to text, in mm. */
export const FIT_TEXT_MIN_W = 14;
export const FIT_TEXT_MIN_H = 6;
export const FIT_QR_MIN = 8;

/**
 * Fit the code and the text on a label of `w` × `h` mm. A wide label puts the text right
 * of the code and a tall label puts it below. When the text box would be too small, or
 * the code too small next to it, or there is no text, the label holds only the code.
 */
export function fitLabel(w: number, h: number, hasText: boolean): LabelFit {
  const innerW = Math.max(w - FIT_PAD * 2, 0);
  const innerH = Math.max(h - FIT_PAD * 2, 0);
  if (hasText && w >= h) {
    const qr = Math.min(innerH, innerW - FIT_GAP - FIT_TEXT_MIN_W);
    if (qr >= FIT_QR_MIN) {
      return {
        mode: 'side',
        qr,
        qrX: FIT_PAD,
        qrY: FIT_PAD + (innerH - qr) / 2,
        textX: FIT_PAD + qr + FIT_GAP,
        textY: FIT_PAD,
        textW: innerW - qr - FIT_GAP,
        textH: innerH,
      };
    }
  }
  if (hasText && h > w) {
    const qr = Math.min(innerW, innerH - FIT_GAP - FIT_TEXT_MIN_H);
    if (qr >= FIT_QR_MIN) {
      return {
        mode: 'below',
        qr,
        qrX: FIT_PAD + (innerW - qr) / 2,
        qrY: FIT_PAD,
        textX: FIT_PAD,
        textY: FIT_PAD + qr + FIT_GAP,
        textW: innerW,
        textH: innerH - qr - FIT_GAP,
      };
    }
  }
  const qr = Math.min(innerW, innerH);
  return {
    mode: 'code',
    qr,
    qrX: (w - qr) / 2,
    qrY: (h - qr) / 2,
    textX: 0,
    textY: 0,
    textW: 0,
    textH: 0,
  };
}

/** The text sizes of a label, in pt, and the line heights, as on the sheets. */
export const TEXT_L1_PT = 8.5;
export const TEXT_LN_PT = 7;
const L1_LEADING = 1.15;
const LN_LEADING = 1.2;
const PT_MM = 25.4 / 72;
/** The most rows the first line and each other line can wrap to. */
const L1_MAX_ROWS = 3;
const LN_MAX_ROWS = 2;

/** Measure `text` in mm at a font size in mm. The canvas gives the real one. */
export type MeasureText = (text: string, bold: boolean, sizeMm: number) => number;

/**
 * Wrap `text` into at most `maxRows` rows that each pass `fits`. A word that is wider
 * than a row is cut by characters. When the text does not fit, the last row ends with
 * "…".
 */
export function wrapText(text: string, maxRows: number, fits: (row: string) => boolean): string[] {
  if (maxRows <= 0) return [];
  const rows: string[] = [];
  let row = '';
  const push = (): void => {
    rows.push(row);
    row = '';
  };
  const words = text.split(/\s+/).filter(Boolean);
  for (let i = 0; i < words.length; i++) {
    let word = words[i];
    const tryRow = row ? `${row} ${word}` : word;
    if (fits(tryRow)) {
      row = tryRow;
      continue;
    }
    if (row) push();
    while (!fits(word) && word.length > 1) {
      let cut = word.length - 1;
      while (cut > 1 && !fits(word.slice(0, cut))) cut--;
      row = word.slice(0, cut);
      push();
      word = word.slice(cut);
    }
    row = word;
  }
  if (row) push();
  if (rows.length <= maxRows) return rows;
  const kept = rows.slice(0, maxRows);
  let last = kept[maxRows - 1];
  while (last && !fits(`${last}…`)) last = last.slice(0, -1);
  kept[maxRows - 1] = `${last.trimEnd()}…`;
  return kept;
}

/** 1 row of text to draw: its top edge in mm from the top of the text box. */
export interface TextRow {
  text: string;
  bold: boolean;
  sizeMm: number;
  top: number;
}

/**
 * Lay out the text lines of a label in a box of `boxW` × `boxH` mm, as the print does:
 * the first line bold and up to 3 rows, each other line up to 2 rows. A row that does
 * not fit the box height is left out. The rows are centered in the box height.
 */
export function layoutText(
  lines: string[],
  boxW: number,
  boxH: number,
  measure: MeasureText,
): TextRow[] {
  const out: TextRow[] = [];
  let y = 0;
  const gap = PT_MM;
  lines.forEach((line, i) => {
    const bold = i === 0;
    const sizeMm = (bold ? TEXT_L1_PT : TEXT_LN_PT) * PT_MM;
    const lead = sizeMm * (bold ? L1_LEADING : LN_LEADING);
    const rows = wrapText(line, bold ? L1_MAX_ROWS : LN_MAX_ROWS, (row) =>
      measure(row, bold, sizeMm) <= boxW,
    );
    const start = i === 0 ? 0 : y + gap;
    let at = start;
    for (const text of rows) {
      if (at + lead > boxH + 1e-9) break;
      out.push({ text, bold, sizeMm, top: at });
      at += lead;
    }
    if (at > start) y = at;
  });
  const shift = Math.max((boxH - y) / 2, 0);
  return out.map((row) => ({ ...row, top: row.top + shift }));
}

/**
 * The pixels of a code in a PNG. Each module is a whole number of printer dots, so a
 * thermal printer prints every module the same size and a phone reads it. The code is
 * centered in its box of `qrMm` mm; `count` is the modules across, quiet zone included.
 */
export function qrPixelPlan(
  qrMm: number,
  count: number,
  dpmm: number,
): { module: number; size: number; offset: number } {
  const box = Math.floor(qrMm * dpmm);
  const module = Math.max(1, Math.floor(box / count));
  const size = module * count;
  return { module, size, offset: Math.floor((box - size) / 2) };
}

/** The size of a PNG in pixels: the label at `dpi`, turned when `rotate` is set. */
export function pngSize(
  size: { w: number; h: number },
  dpi: LabelDpi,
  rotate: boolean,
): { width: number; height: number } {
  const dpmm = dotsPerMm(dpi);
  const w = Math.round(size.w * dpmm);
  const h = Math.round(size.h * dpmm);
  return rotate ? { width: h, height: w } : { width: w, height: h };
}

/**
 * The print document for `labels` on a label roll: 1 page for each label, with the page
 * at the size of the label, so Save as PDF gives a file that a label printer app opens
 * page by page. With `rotate`, each page is turned 90° clockwise.
 */
export function rollSheetHtml(labels: PrintLabel[], opts: LabelOpts, title: string): string {
  const { w, h } = labelSizeMm(opts);
  const rotate = opts.rotate;
  const pageW = cssNum(rotate ? h : w);
  const pageH = cssNum(rotate ? w : h);
  const pages = labels.map((label) => {
    const fit = fitLabel(w, h, label.lines.length > 0);
    const text =
      fit.mode === 'code'
        ? ''
        : `<div class="text ${fit.mode}" style="left:${cssNum(fit.textX)}mm;top:${cssNum(
            fit.textY,
          )}mm;width:${cssNum(fit.textW)}mm;height:${cssNum(fit.textH)}mm">${label.lines
            .map((line, j) => `<div class="${j === 0 ? 'l1' : 'ln'}">${escapeHTML(line)}</div>`)
            .join('')}</div>`;
    return (
      `<div class="page"><div class="label">` +
      `<div class="qr" style="left:${cssNum(fit.qrX)}mm;top:${cssNum(fit.qrY)}mm;` +
      `width:${cssNum(fit.qr)}mm;height:${cssNum(fit.qr)}mm">${qrSvg(label.url)}</div>` +
      `${text}</div></div>`
    );
  });
  const turn = rotate ? `transform:translateX(${cssNum(h)}mm) rotate(90deg);transform-origin:0 0;` : '';
  const css =
    `@page{size:${pageW}mm ${pageH}mm;margin:0}` +
    `*{box-sizing:border-box}html,body{margin:0;padding:0}` +
    `body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#000;background:#fff}` +
    `.page{position:relative;width:${pageW}mm;height:${pageH}mm;overflow:hidden;` +
    `break-after:page}.page:last-child{break-after:auto}` +
    `.label{position:absolute;left:0;top:0;width:${cssNum(w)}mm;height:${cssNum(h)}mm;${turn}}` +
    `.qr{position:absolute}.qr svg{display:block;width:100%;height:100%}` +
    `.text{position:absolute;display:flex;flex-direction:column;justify-content:center;` +
    `gap:1pt;overflow:hidden}.text.below{text-align:center}` +
    `.l1,.ln{display:-webkit-box;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}` +
    `.l1{font-weight:700;font-size:${TEXT_L1_PT}pt;line-height:${L1_LEADING};-webkit-line-clamp:${L1_MAX_ROWS}}` +
    `.ln{font-size:${TEXT_LN_PT}pt;line-height:${LN_LEADING};-webkit-line-clamp:${LN_MAX_ROWS}}`;
  return (
    `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHTML(title)}</title>` +
    `<style>${css}</style></head><body>${pages.join('')}</body></html>`
  );
}

/** The print document for `labels` with the saved choices: a sheet or a roll. */
export function labelPrintHtml(
  labels: PrintLabel[],
  opts: LabelOpts,
  skip: number,
  title: string,
): string {
  return isRoll(opts.paper)
    ? rollSheetHtml(labels, opts, title)
    : labelSheetHtml(labels, opts.paper, skip, title);
}

/** A file name for 1 code as a PNG: `home-keeper-<kind>-<name>.png`, safe on any OS. */
export function labelFileName(kind: 'asset' | 'task', name: string): string {
  const slug = name
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60);
  return `home-keeper-${kind === 'asset' ? 'appliance' : 'task'}-${slug || 'label'}.png`;
}
