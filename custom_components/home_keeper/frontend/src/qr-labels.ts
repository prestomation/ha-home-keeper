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

/** The label sheets the panel can print. */
export const LABEL_PAPERS = ['letter30', 'a4_21'] as const;
export type LabelPaper = (typeof LABEL_PAPERS)[number];

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

export const LAYOUTS: Record<LabelPaper, LabelLayout> = {
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

/** The number of labels on 1 sheet of `paper`. */
export function labelsPerPage(paper: LabelPaper): number {
  const l = LAYOUTS[paper];
  return l.cols * l.rows;
}

/** Countries where Letter paper is the norm. Everywhere else gets A4 first. */
const LETTER_COUNTRIES = new Set(['US', 'CA', 'MX', 'PH']);

/** The sheet to offer first, from the Home Assistant country setting. */
export function defaultPaper(country: string | null | undefined): LabelPaper {
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
}

/**
 * Read the saved choices, or the defaults. The value comes from `localStorage`, which
 * any old version or another tab can have written, so every part is checked and an
 * unknown value reads as the default.
 */
export function parseLabelOpts(raw: string | null, fallbackPaper: LabelPaper): LabelOpts {
  const dflt: LabelOpts = { paper: fallbackPaper, lines: [...LABEL_LINES] };
  if (!raw) return dflt;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return dflt;
  }
  if (!data || typeof data !== 'object') return dflt;
  const obj = data as { paper?: unknown; lines?: unknown };
  const paper = LABEL_PAPERS.includes(obj.paper as LabelPaper)
    ? (obj.paper as LabelPaper)
    : fallbackPaper;
  const lines = Array.isArray(obj.lines)
    ? LABEL_LINES.filter((line) => (obj.lines as unknown[]).includes(line))
    : dflt.lines;
  return { paper, lines };
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
  paper: LabelPaper,
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
  paper: LabelPaper,
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
