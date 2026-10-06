/**
 * QR code labels: the links, the text, the code and the print sheet.
 *
 * A printed label is a contract that outlives the code that made it: the link must
 * keep pointing at the same page, and the sheet must put each label on the die-cut
 * shape of the stock sheet it names.
 */
import { describe, expect, it } from 'vitest';
import {
  CUSTOM_MAX_MM,
  CUSTOM_MIN_MM,
  FIT_PAD,
  LABEL_LINES,
  LABEL_PAPERS,
  LAYOUTS,
  QR_BORDER,
  ROLL_PAPERS,
  SHEET_PAPERS,
  clampMm,
  clampSkip,
  defaultLabelOpts,
  dotsPerMm,
  fitLabel,
  isRoll,
  labelPrintHtml,
  labelSizeMm,
  layoutText,
  pngSize,
  qrPixelPlan,
  rollSheetHtml,
  wrapText,
  cssNum,
  defaultPaper,
  labelBaseUrl,
  labelFileName,
  labelLines,
  labelSheetHtml,
  labelSlot,
  labelUrl,
  labelsPerPage,
  parseLabelOpts,
  qrModules,
  qrSvg,
} from '../src/qr-labels.ts';
import { buildPath } from '../src/utils.ts';

const URL_A = 'https://ha.example.com/home-keeper/appliances/0f1e2d3c';

describe('labelBaseUrl', () => {
  it('prefers the external URL', () => {
    expect(
      labelBaseUrl(
        { external_url: 'https://ext.example.com', internal_url: 'http://192.168.1.2:8123' },
        'http://localhost:8123',
      ),
    ).toBe('https://ext.example.com');
  });

  it('uses the internal URL when there is no external URL', () => {
    expect(
      labelBaseUrl({ external_url: null, internal_url: 'http://ha.local:8123' }, 'http://x'),
    ).toBe('http://ha.local:8123');
  });

  it('falls back to the browser address', () => {
    expect(labelBaseUrl({}, 'http://localhost:8123')).toBe('http://localhost:8123');
    expect(labelBaseUrl(undefined, 'http://localhost:8123')).toBe('http://localhost:8123');
    expect(labelBaseUrl({ external_url: '', internal_url: '' }, 'http://b')).toBe('http://b');
  });

  it('removes every trailing slash, and only those', () => {
    expect(labelBaseUrl({ external_url: 'https://e.example.com//' }, 'x')).toBe(
      'https://e.example.com',
    );
    expect(labelBaseUrl({ external_url: 'https://e.example.com/ha/' }, 'x')).toBe(
      'https://e.example.com/ha',
    );
  });
});

describe('labelUrl', () => {
  it('joins the base and the panel path of an appliance and a task', () => {
    const asset = '/home-keeper' + buildPath({ view: 'appliances', detail: { kind: 'asset', id: 'a1' } });
    const task = '/home-keeper' + buildPath({ view: 'tasks', detail: { kind: 'task', id: 't1' } });
    expect(labelUrl('https://h.example.com', asset)).toBe(
      'https://h.example.com/home-keeper/appliances/a1',
    );
    expect(labelUrl('https://h.example.com', task)).toBe('https://h.example.com/home-keeper/tasks/t1');
  });

  it('adds the slash a relative path lacks', () => {
    expect(labelUrl('https://h.example.com', 'my-panel/tasks/t1')).toBe(
      'https://h.example.com/my-panel/tasks/t1',
    );
  });
});

describe('labelLines', () => {
  const src = { name: 'Water heater', model: 'Rheem XE50', area: 'Garage', schedule: 'Every month' };

  it('prints the chosen lines in the fixed order', () => {
    expect(labelLines(src, ['schedule', 'name'])).toEqual(['Water heater', 'Every month']);
    expect(labelLines(src, [...LABEL_LINES])).toEqual([
      'Water heater',
      'Rheem XE50',
      'Garage',
      'Every month',
    ]);
  });

  it('drops a line with no value and trims the rest', () => {
    expect(labelLines({ name: '  Filter  ', model: '', area: '   ' }, [...LABEL_LINES])).toEqual([
      'Filter',
    ]);
  });

  it('gives no lines when none is chosen', () => {
    expect(labelLines(src, [])).toEqual([]);
  });
});

describe('papers', () => {
  it('counts the labels on each sheet', () => {
    expect(labelsPerPage('letter30')).toBe(30);
    expect(labelsPerPage('a4_21')).toBe(21);
  });

  it('offers Letter first in North America and the Philippines, A4 elsewhere', () => {
    for (const c of ['US', 'ca', 'MX', 'PH']) expect(defaultPaper(c)).toBe('letter30');
    for (const c of ['GB', 'DE', 'AU', '', null, undefined]) expect(defaultPaper(c)).toBe('a4_21');
  });

  it('keeps the stock sheet geometry', () => {
    // Avery 5160 and L7160. A changed number moves every label off its die-cut shape.
    expect(LAYOUTS.letter30).toMatchObject({
      unit: 'in', pageSize: 'letter', cols: 3, rows: 10, labelW: 2.625, labelH: 1,
      top: 0.5, left: 0.1875, pitchX: 2.75, pitchY: 1,
    });
    expect(LAYOUTS.a4_21).toMatchObject({
      unit: 'mm', pageSize: 'A4', cols: 3, rows: 7, labelW: 63.5, labelH: 38.1,
      top: 15.15, left: 7.21, pitchX: 66.04, pitchY: 38.1,
    });
  });
});

describe('labelSlot and clampSkip', () => {
  it('fills a sheet row by row, then starts the next sheet', () => {
    expect(labelSlot('letter30', 0)).toEqual({ page: 0, row: 0, col: 0 });
    expect(labelSlot('letter30', 2)).toEqual({ page: 0, row: 0, col: 2 });
    expect(labelSlot('letter30', 3)).toEqual({ page: 0, row: 1, col: 0 });
    expect(labelSlot('letter30', 29)).toEqual({ page: 0, row: 9, col: 2 });
    expect(labelSlot('letter30', 30)).toEqual({ page: 1, row: 0, col: 0 });
    expect(labelSlot('a4_21', 21)).toEqual({ page: 1, row: 0, col: 0 });
    expect(labelSlot('a4_21', 20)).toEqual({ page: 0, row: 6, col: 2 });
  });

  it('keeps the skip inside the first sheet', () => {
    expect(clampSkip('letter30', 5)).toBe(5);
    expect(clampSkip('letter30', 5.7)).toBe(5);
    expect(clampSkip('letter30', -3)).toBe(0);
    expect(clampSkip('letter30', 29)).toBe(29);
    expect(clampSkip('letter30', 30)).toBe(29);
    expect(clampSkip('a4_21', 99)).toBe(20);
    expect(clampSkip('a4_21', Number.NaN)).toBe(0);
    expect(clampSkip('a4_21', Number.POSITIVE_INFINITY)).toBe(0);
  });
});

describe('cssNum', () => {
  it('rounds float noise to 4 decimals', () => {
    expect(cssNum(0.06 * 1.5)).toBe('0.09');
    expect(cssNum(7.21 + 2 * 66.04)).toBe('139.29');
    expect(cssNum(2)).toBe('2');
    expect(cssNum(1.23456)).toBe('1.2346');
    expect(cssNum(0.1875)).toBe('0.1875');
  });
});

describe('parseLabelOpts', () => {
  it('gives the defaults for nothing, bad JSON or a non-object', () => {
    const dflt = {
      paper: 'a4_21',
      lines: [...LABEL_LINES],
      customW: 50,
      customH: 30,
      dpi: 203,
      rotate: false,
    };
    expect(parseLabelOpts(null, 'a4_21')).toEqual(dflt);
    expect(parseLabelOpts('', 'a4_21')).toEqual(dflt);
    expect(parseLabelOpts('{nope', 'a4_21')).toEqual(dflt);
    expect(parseLabelOpts('42', 'a4_21')).toEqual(dflt);
    expect(parseLabelOpts('null', 'a4_21')).toEqual(dflt);
  });

  it('keeps a known paper and reads an unknown one as the fallback', () => {
    expect(parseLabelOpts('{"paper":"letter30"}', 'a4_21').paper).toBe('letter30');
    expect(parseLabelOpts('{"paper":"a5"}', 'letter30').paper).toBe('letter30');
  });

  it('keeps a roll paper, the custom size, the density and the rotation', () => {
    const opts = parseLabelOpts(
      '{"paper":"roll_custom","customW":62,"customH":29.04,"dpi":300,"rotate":true}',
      'a4_21',
    );
    expect(opts).toEqual({
      paper: 'roll_custom',
      lines: [...LABEL_LINES],
      customW: 62,
      customH: 29,
      dpi: 300,
      rotate: true,
    });
  });

  it('reads a bad size, density or rotation as the default, and clamps a size', () => {
    const opts = parseLabelOpts(
      '{"customW":"62","customH":5000,"dpi":600,"rotate":"yes"}',
      'letter30',
    );
    expect(opts.customW).toBe(50);
    expect(opts.customH).toBe(CUSTOM_MAX_MM);
    expect(opts.dpi).toBe(203);
    expect(opts.rotate).toBe(false);
    expect(parseLabelOpts('{"customW":1}', 'a4_21').customW).toBe(CUSTOM_MIN_MM);
    expect(parseLabelOpts('{"customW":null}', 'a4_21').customW).toBe(50);
  });

  it('keeps only known lines, in print order, and keeps an empty choice', () => {
    expect(parseLabelOpts('{"lines":["area","bogus","name"]}', 'a4_21').lines).toEqual([
      'name',
      'area',
    ]);
    expect(parseLabelOpts('{"lines":[]}', 'a4_21').lines).toEqual([]);
    expect(parseLabelOpts('{"lines":"name"}', 'a4_21').lines).toEqual([...LABEL_LINES]);
  });
});

describe('qrModules and qrSvg', () => {
  const finder = (mods, top, left) => {
    for (let y = 0; y < 7; y++) {
      for (let x = 0; x < 7; x++) {
        const ring = y === 0 || y === 6 || x === 0 || x === 6;
        const eye = y >= 2 && y <= 4 && x >= 2 && x <= 4;
        expect(mods[top + y][left + x]).toBe(ring || eye);
      }
    }
  };

  it('makes a square code with the 3 finder patterns', () => {
    const mods = qrModules(URL_A);
    const n = mods.length;
    expect(n).toBeGreaterThanOrEqual(21);
    expect((n - 17) % 4).toBe(0);
    for (const row of mods) expect(row).toHaveLength(n);
    finder(mods, 0, 0);
    finder(mods, 0, n - 7);
    finder(mods, n - 7, 0);
  });

  it('uses error level M: a short text fits version 1', () => {
    // 14 bytes fit version 1 at level M (limit 14) but not at Q (limit 11).
    expect(qrModules('ABCDEFGHIJKLMN'.toLowerCase())).toHaveLength(21);
    expect(qrModules('abcdefghijklmno')).toHaveLength(25);
  });

  it('draws 1 unit square per dark module, inside a quiet zone, black on white', () => {
    const mods = qrModules(URL_A);
    const n = mods.length + QR_BORDER * 2;
    const svg = qrSvg(URL_A);
    expect(QR_BORDER).toBe(2);
    expect(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg"')).toBe(true);
    expect(svg).toContain(`viewBox="0 0 ${n} ${n}"`);
    expect(svg).toContain(`<rect width="${n}" height="${n}" fill="#fff"/>`);
    expect(svg).toContain('fill="#000"');
    expect(svg).toContain('shape-rendering="crispEdges"');
    const squares = [...svg.matchAll(/M(\d+) (\d+)h1v1h-1z/g)];
    const dark = mods.flat().filter(Boolean).length;
    expect(squares).toHaveLength(dark);
    // The first dark module is the top-left finder corner, offset by the border.
    expect(squares[0][1]).toBe(String(QR_BORDER));
    expect(squares[0][2]).toBe(String(QR_BORDER));
    for (const [, x, y] of squares) {
      expect(mods[Number(y) - QR_BORDER][Number(x) - QR_BORDER]).toBe(true);
    }
  });

  it('gives a different code for a different link', () => {
    expect(qrSvg(URL_A)).not.toBe(qrSvg(`${URL_A}x`));
  });
});

describe('labelSheetHtml', () => {
  const label = (n) => ({ url: `${URL_A}${n}`, lines: [`Item ${n}`, 'Garage'] });
  const pages = (html) => html.match(/<div class="page">/g)?.length ?? 0;
  const lefts = (html) => [...html.matchAll(/class="label" style="left:([\d.]+)(in|mm);top:([\d.]+)\2"/g)];

  it('is a whole document with the sheet size and no page margin', () => {
    const html = labelSheetHtml([label(1)], 'letter30', 0, 'QR labels');
    expect(html.startsWith('<!doctype html><html><head><meta charset="utf-8"><title>QR labels</title>')).toBe(true);
    expect(html).toContain('@page{size:letter;margin:0}');
    expect(html).toContain('.page{position:relative;width:8.5in;height:11in;');
    expect(html).toContain('.label{position:absolute;width:2.625in;height:1in;padding:0.06in;');
    expect(html).toContain('gap:0.09in;');
    expect(html).toContain('.qr{flex:0 0 0.88in;width:0.88in;height:0.88in}');
    expect(html.endsWith('</body></html>')).toBe(true);
    const a4 = labelSheetHtml([label(1)], 'a4_21', 0, 'x');
    expect(a4).toContain('@page{size:A4;margin:0}');
    expect(a4).toContain('width:210mm;height:297mm;');
    // 45% of the width is less than the height here, so the width sets the code size.
    expect(a4).toContain('.qr{flex:0 0 28.575mm;');
  });

  it('puts each label on its stock position', () => {
    const html = labelSheetHtml([1, 2, 3, 4].map(label), 'letter30', 0, 't');
    const pos = lefts(html).map((m) => [m[1], m[3]]);
    expect(pos).toEqual([
      ['0.1875', '0.5'],
      ['2.9375', '0.5'],
      ['5.6875', '0.5'],
      ['0.1875', '1.5'],
    ]);
    const a4 = labelSheetHtml([1, 2, 3, 4].map(label), 'a4_21', 0, 't');
    expect(lefts(a4).map((m) => [m[1], m[3]])).toEqual([
      ['7.21', '15.15'],
      ['73.25', '15.15'],
      ['139.29', '15.15'],
      ['7.21', '53.25'],
    ]);
  });

  it('skips used positions, and starts a new sheet when one is full', () => {
    const html = labelSheetHtml([1, 2].map(label), 'letter30', 29, 't');
    expect(pages(html)).toBe(2);
    expect(lefts(html).map((m) => [m[1], m[3]])).toEqual([
      ['5.6875', '9.5'],
      ['0.1875', '0.5'],
    ]);
    expect(pages(labelSheetHtml(Array.from({ length: 30 }, (_, i) => label(i)), 'letter30', 0, 't'))).toBe(1);
    expect(pages(labelSheetHtml(Array.from({ length: 31 }, (_, i) => label(i)), 'letter30', 0, 't'))).toBe(2);
    expect(pages(labelSheetHtml(Array.from({ length: 22 }, (_, i) => label(i)), 'a4_21', 0, 't'))).toBe(2);
  });

  it('clamps the skip so the first label is never lost', () => {
    const html = labelSheetHtml([label(1)], 'a4_21', 500, 't');
    expect(pages(html)).toBe(1);
    expect(lefts(html).map((m) => [m[1], m[3]])).toEqual([['139.29', '243.75']]);
  });

  it('holds the code of each link and the text lines, the first one bold', () => {
    const html = labelSheetHtml([label(1)], 'letter30', 0, 't');
    expect(html).toContain(`<div class="qr">${qrSvg(`${URL_A}1`)}</div>`);
    expect(html).toContain('<div class="text"><div class="l1">Item 1</div><div class="ln">Garage</div></div>');
    expect(html).toContain('.l1{font-weight:700;font-size:8.5pt;line-height:1.15;-webkit-line-clamp:3}');
    expect(html).toContain('.ln{font-size:7pt;line-height:1.2;-webkit-line-clamp:2}');
  });

  it('escapes user text in the lines and the title', () => {
    const html = labelSheetHtml(
      [{ url: URL_A, lines: ['<script>alert(1)</script>', 'A & B'] }],
      'letter30',
      0,
      '<b>t</b>',
    );
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(html).toContain('A &amp; B');
    expect(html).toContain('<title>&lt;b&gt;t&lt;/b&gt;</title>');
  });

  it('gives an empty sheet list for no labels', () => {
    expect(pages(labelSheetHtml([], 'letter30', 0, 't'))).toBe(0);
  });
});

describe('labelFileName', () => {
  it('names the kind and a safe slug of the name', () => {
    expect(labelFileName('asset', 'Garage Water Heater')).toBe(
      'home-keeper-appliance-garage-water-heater.png',
    );
    expect(labelFileName('task', 'Replace filter (monthly)!')).toBe(
      'home-keeper-task-replace-filter-monthly.png',
    );
  });

  it('removes accents and falls back for a name with no letters', () => {
    expect(labelFileName('asset', 'Lave-vaisselle à côté')).toBe(
      'home-keeper-appliance-lave-vaisselle-a-cote.png',
    );
    expect(labelFileName('task', '洗碗机')).toBe('home-keeper-task-label.png');
    expect(labelFileName('task', '---')).toBe('home-keeper-task-label.png');
  });

  it('keeps the slug to 60 characters', () => {
    const name = 'a'.repeat(80);
    expect(labelFileName('asset', name)).toBe(`home-keeper-appliance-${'a'.repeat(60)}.png`);
  });
});

describe('rolls', () => {
  it('lists the sheets first, then the rolls', () => {
    expect(LABEL_PAPERS).toEqual([...SHEET_PAPERS, ...ROLL_PAPERS]);
    expect(SHEET_PAPERS.map(isRoll)).toEqual([false, false]);
    expect(ROLL_PAPERS.every(isRoll)).toBe(true);
  });

  it('puts 1 label on each page of a roll', () => {
    for (const paper of ROLL_PAPERS) expect(labelsPerPage(paper)).toBe(1);
    expect(clampSkip('roll_50x30', 5)).toBe(0);
  });

  it('gives the label size in mm for a roll, a custom roll and a sheet', () => {
    const base = defaultLabelOpts('a4_21');
    expect(labelSizeMm({ ...base, paper: 'roll_50x30' })).toEqual({ w: 50, h: 30 });
    expect(labelSizeMm({ ...base, paper: 'roll_40x30' })).toEqual({ w: 40, h: 30 });
    expect(labelSizeMm({ ...base, paper: 'roll_50x20' })).toEqual({ w: 50, h: 20 });
    expect(labelSizeMm({ ...base, paper: 'roll_30x15' })).toEqual({ w: 30, h: 15 });
    expect(labelSizeMm({ ...base, paper: 'roll_custom', customW: 62, customH: 29 })).toEqual({
      w: 62,
      h: 29,
    });
    expect(labelSizeMm(base)).toEqual({ w: 63.5, h: 38.1 });
    const letter = labelSizeMm({ ...base, paper: 'letter30' });
    expect(letter.w).toBeCloseTo(66.675, 6);
    expect(letter.h).toBeCloseTo(25.4, 6);
  });

  it('clamps a custom size to the limits and rounds it to 0.1 mm', () => {
    expect(clampMm(49.96, 1)).toBe(50);
    expect(clampMm(49.94, 1)).toBe(49.9);
    expect(clampMm(9.9, 1)).toBe(CUSTOM_MIN_MM);
    expect(clampMm(CUSTOM_MIN_MM, 1)).toBe(CUSTOM_MIN_MM);
    expect(clampMm(CUSTOM_MAX_MM, 1)).toBe(CUSTOM_MAX_MM);
    expect(clampMm(300.1, 1)).toBe(CUSTOM_MAX_MM);
    expect(clampMm(Number.NaN, 42)).toBe(42);
    expect(clampMm(Infinity, 42)).toBe(42);
  });
});

describe('fitLabel', () => {
  it('puts the text right of the code on a wide label', () => {
    const fit = fitLabel(50, 30, true);
    expect(fit.mode).toBe('side');
    expect(fit.qr).toBe(27);
    expect(fit.qrX).toBe(FIT_PAD);
    expect(fit.qrY).toBe(FIT_PAD);
    expect(fit.textX).toBe(30);
    expect(fit.textY).toBe(FIT_PAD);
    expect(fit.textW).toBe(18.5);
    expect(fit.textH).toBe(27);
  });

  it('makes the code smaller to keep room for the text', () => {
    // 40 × 30: a full-height code leaves 9.5 mm, less than the 14 mm text minimum.
    const fit = fitLabel(40, 30, true);
    expect(fit.mode).toBe('side');
    expect(fit.qr).toBe(21.5);
    expect(fit.textW).toBe(14);
    expect(fit.qrY).toBe(FIT_PAD + (27 - 21.5) / 2);
  });

  it('puts the text below the code on a tall label', () => {
    const fit = fitLabel(30, 50, true);
    expect(fit.mode).toBe('below');
    expect(fit.qr).toBe(27);
    expect(fit.qrX).toBe(FIT_PAD);
    expect(fit.qrY).toBe(FIT_PAD);
    expect(fit.textX).toBe(FIT_PAD);
    expect(fit.textY).toBe(30);
    expect(fit.textW).toBe(27);
    expect(fit.textH).toBe(18.5);
  });

  it('shrinks the code on a tall label to keep room for the text', () => {
    const fit = fitLabel(30, 36, true);
    expect(fit.mode).toBe('below');
    expect(fit.qr).toBe(25.5);
    expect(fit.qrX).toBe(FIT_PAD + (27 - 25.5) / 2);
    expect(fit.textH).toBe(6);
  });

  it('prints only the code when the text has no room, or there is no text', () => {
    const tiny = fitLabel(20, 12, true);
    expect(tiny.mode).toBe('code');
    expect(tiny.qr).toBe(9);
    expect(tiny.qrX).toBe(5.5);
    expect(tiny.qrY).toBe(FIT_PAD);
    expect(tiny.textW).toBe(0);
    expect(fitLabel(10, 30, true).mode).toBe('code');
    const none = fitLabel(50, 30, false);
    expect(none.mode).toBe('code');
    expect(none.qr).toBe(27);
    expect(none.qrX).toBe(11.5);
  });

  it('keeps the smallest code that still fits next to text', () => {
    // 50 × 11: the inner height is exactly the 8 mm minimum.
    expect(fitLabel(50, 11, true).mode).toBe('side');
    expect(fitLabel(50, 10.9, true).mode).toBe('code');
    // 26.5 × 20: the inner width leaves 23.5 − 1.5 − 14 = 8 mm for the code.
    expect(fitLabel(26.5, 20, true).mode).toBe('side');
    expect(fitLabel(26.4, 20, true).mode).toBe('code');
    // 11 × 30: the inner width is the 8 mm minimum, and the inner height has room.
    expect(fitLabel(11, 30, true).mode).toBe('below');
    expect(fitLabel(10.9, 30, true).mode).toBe('code');
  });

  it('keeps the code inside the label and away from the text at every size', () => {
    for (const [w, h] of [
      [50, 30],
      [40, 30],
      [50, 20],
      [30, 15],
      [10, 10],
      [62, 29],
      [30, 50],
      [300, 10],
    ]) {
      for (const text of [true, false]) {
        const fit = fitLabel(w, h, text);
        expect(fit.qrX).toBeGreaterThanOrEqual(0);
        expect(fit.qrY).toBeGreaterThanOrEqual(0);
        expect(fit.qrX + fit.qr).toBeLessThanOrEqual(w + 1e-9);
        expect(fit.qrY + fit.qr).toBeLessThanOrEqual(h + 1e-9);
        if (fit.mode === 'side') expect(fit.textX).toBeGreaterThan(fit.qrX + fit.qr);
        if (fit.mode === 'below') expect(fit.textY).toBeGreaterThan(fit.qrY + fit.qr);
        if (fit.mode !== 'code') {
          expect(fit.textX + fit.textW).toBeLessThanOrEqual(w - FIT_PAD + 1e-9);
          expect(fit.textY + fit.textH).toBeLessThanOrEqual(h - FIT_PAD + 1e-9);
        }
      }
    }
  });
});

/** 1 mm for each character: a measure that is easy to reason about. */
const mono = (text) => text.length;

describe('wrapText', () => {
  const fits = (max) => (row) => mono(row) <= max;

  it('keeps a short text on 1 row', () => {
    expect(wrapText('Water heater', 3, fits(20))).toEqual(['Water heater']);
  });

  it('wraps at spaces and joins words while they fit', () => {
    expect(wrapText('Garage  water heater tank', 3, fits(12))).toEqual([
      'Garage water',
      'heater tank',
    ]);
  });

  it('cuts a word that is wider than a row', () => {
    expect(wrapText('XE50T10HS45U0', 4, fits(5))).toEqual(['XE50T', '10HS4', '5U0']);
    expect(wrapText('ab XE50T10HS4', 4, fits(5))).toEqual(['ab', 'XE50T', '10HS4']);
  });

  it('ends the last row with an ellipsis when the text is too long', () => {
    expect(wrapText('one two three four', 2, fits(6))).toEqual(['one', 'two…']);
    expect(wrapText('aaaaaa bbbbbb cc', 2, fits(6))).toEqual(['aaaaaa', 'bbbbb…']);
  });

  it('gives no rows for an empty text or no room', () => {
    expect(wrapText('   ', 2, fits(10))).toEqual([]);
    expect(wrapText('abc', 0, fits(10))).toEqual([]);
  });
});

describe('layoutText', () => {
  const ptMm = 25.4 / 72;
  const l1 = 8.5 * ptMm;
  const ln = 7 * ptMm;

  it('sets the first line bold and larger, the other lines smaller', () => {
    const rows = layoutText(['Heater', 'Garage'], 40, 40, mono);
    expect(rows.map((r) => [r.text, r.bold])).toEqual([
      ['Heater', true],
      ['Garage', false],
    ]);
    expect(rows[0].sizeMm).toBeCloseTo(l1, 9);
    expect(rows[1].sizeMm).toBeCloseTo(ln, 9);
  });

  it('stacks the rows with the line height and a gap, centered in the box', () => {
    const rows = layoutText(['Heater', 'Garage'], 40, 20, mono);
    const used = l1 * 1.15 + ptMm + ln * 1.2;
    const shift = (20 - used) / 2;
    expect(rows[0].top).toBeCloseTo(shift, 9);
    expect(rows[1].top).toBeCloseTo(shift + l1 * 1.15 + ptMm, 9);
  });

  it('wraps the first line to 3 rows and the others to 2', () => {
    const rows = layoutText(['a b c d e', 'f g h i'], 1, 100, mono);
    expect(rows.filter((r) => r.bold).map((r) => r.text)).toEqual(['a', 'b', '…']);
    expect(rows.filter((r) => !r.bold).map((r) => r.text)).toEqual(['f', '…']);
  });

  it('leaves out the rows that do not fit the box height', () => {
    const rows = layoutText(['Heater', 'Garage', 'Bosch'], 40, l1 * 1.15 + ptMm + ln * 1.2, mono);
    expect(rows.map((r) => r.text)).toEqual(['Heater', 'Garage']);
    expect(rows[0].top).toBeCloseTo(0, 9);
    expect(layoutText(['Heater'], 40, l1, mono)).toEqual([]);
  });

  it('does not count the gap of a line that left no rows', () => {
    const rows = layoutText(['Heater', '', 'Garage'], 40, 40, mono);
    expect(rows.map((r) => r.text)).toEqual(['Heater', 'Garage']);
    expect(rows[1].top - rows[0].top).toBeCloseTo(l1 * 1.15 + ptMm, 9);
  });
});

describe('PNG geometry', () => {
  it('uses 8 dots per mm at 203 dpi and about 12 at 300 dpi', () => {
    expect(dotsPerMm(203)).toBeCloseTo(7.992, 3);
    expect(dotsPerMm(300)).toBeCloseTo(11.811, 3);
  });

  it('sizes the image as the label at the density, turned on request', () => {
    expect(pngSize({ w: 50, h: 30 }, 203, false)).toEqual({ width: 400, height: 240 });
    expect(pngSize({ w: 50, h: 30 }, 203, true)).toEqual({ width: 240, height: 400 });
    expect(pngSize({ w: 50, h: 30 }, 300, false)).toEqual({ width: 591, height: 354 });
  });

  it('makes each module a whole number of dots and centers the code in its box', () => {
    // 27 mm at 8 dots/mm is 215 dots; 25 modules + 4 quiet = 29, so 7 dots each.
    const plan = qrPixelPlan(27, 29, dotsPerMm(203));
    expect(plan).toEqual({ module: 7, size: 203, offset: 6 });
  });

  it('never makes a module smaller than 1 dot', () => {
    expect(qrPixelPlan(2, 29, 8)).toEqual({ module: 1, size: 29, offset: -7 });
  });
});

describe('rollSheetHtml', () => {
  const labels = [
    { url: URL_A, lines: ['Water <heater>', 'Garage'] },
    { url: URL_A.replace('appliances', 'tasks'), lines: [] },
  ];
  const opts = { ...defaultLabelOpts('a4_21'), paper: 'roll_50x30' };

  it('makes 1 page at the label size for each label', () => {
    const html = rollSheetHtml(labels, opts, 'QR labels');
    expect(html).toContain('@page{size:50mm 30mm;margin:0}');
    expect(html).toContain('.page{position:relative;width:50mm;height:30mm;');
    expect(html.match(/class="page"/g)).toHaveLength(2);
    expect(html).toContain('.page:last-child{break-after:auto}');
    expect(html).not.toContain('transform');
  });

  it('places the code and the text as fitLabel says', () => {
    const html = rollSheetHtml(labels, opts, 'QR labels');
    expect(html).toContain('<div class="qr" style="left:1.5mm;top:1.5mm;width:27mm;height:27mm">');
    expect(html).toContain(
      '<div class="text side" style="left:30mm;top:1.5mm;width:18.5mm;height:27mm">',
    );
    // A label with no text lines is only its code, in the middle.
    expect(html).toContain('<div class="qr" style="left:11.5mm;top:1.5mm;width:27mm;height:27mm">');
    expect(html.match(/class="text/g)).toHaveLength(1);
  });

  it('centers the text below the code on a tall label', () => {
    const html = rollSheetHtml(labels.slice(0, 1), { ...opts, paper: 'roll_custom', customW: 30, customH: 50 }, 'x');
    expect(html).toContain('<div class="text below"');
    expect(html).toContain('.text.below{text-align:center}');
  });

  it('turns the page and the label 90° on request', () => {
    const html = rollSheetHtml(labels, { ...opts, rotate: true }, 'QR labels');
    expect(html).toContain('@page{size:30mm 50mm;margin:0}');
    expect(html).toContain('.page{position:relative;width:30mm;height:50mm;');
    expect(html).toContain(
      '.label{position:absolute;left:0;top:0;width:50mm;height:30mm;' +
        'transform:translateX(30mm) rotate(90deg);transform-origin:0 0;}',
    );
  });

  it('holds the code of each link and escapes the text and the title', () => {
    const html = rollSheetHtml(labels, opts, 'A <b> title');
    expect(html).toContain(qrSvg(URL_A));
    expect(html).toContain('<div class="l1">Water &lt;heater&gt;</div><div class="ln">Garage</div>');
    expect(html).not.toContain('<heater>');
    expect(html).toContain('<title>A &lt;b&gt; title</title>');
  });

  it('uses the custom size for a custom roll', () => {
    const html = rollSheetHtml(labels, { ...opts, paper: 'roll_custom', customW: 62, customH: 29 }, 'x');
    expect(html).toContain('@page{size:62mm 29mm;margin:0}');
  });
});

describe('labelPrintHtml', () => {
  const labels = [{ url: URL_A, lines: ['Heater'] }];

  it('prints a sheet for a sheet paper, with the skip', () => {
    const opts = defaultLabelOpts('a4_21');
    expect(labelPrintHtml(labels, opts, 2, 'T')).toBe(labelSheetHtml(labels, 'a4_21', 2, 'T'));
  });

  it('prints a roll for a roll paper, and ignores the skip', () => {
    const opts = { ...defaultLabelOpts('a4_21'), paper: 'roll_40x30' };
    expect(labelPrintHtml(labels, opts, 2, 'T')).toBe(rollSheetHtml(labels, opts, 'T'));
  });
});
