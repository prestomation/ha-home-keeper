/**
 * QR code labels: the links, the text, the code and the print sheet.
 *
 * A printed label is a contract that outlives the code that made it: the link must
 * keep pointing at the same page, and the sheet must put each label on the die-cut
 * shape of the stock sheet it names.
 */
import { describe, expect, it } from 'vitest';
import {
  LABEL_LINES,
  LAYOUTS,
  QR_BORDER,
  clampSkip,
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
    const dflt = { paper: 'a4_21', lines: [...LABEL_LINES] };
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
