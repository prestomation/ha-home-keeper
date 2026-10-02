// Measure a running page's DOM/CSSOM and report hard facts a vision model
// can't reliably eyeball: exact font sizes, near-duplicate colors, contrast
// ratios, and pixel-level alignment near-misses. The reviewing model reads
// the markdown report and judges it; this tool only measures.
//
// Usage: node style-inventory.mjs <url-or-scenario.json> [outFile.md]
//   - If the first arg ends in .json, it's a shoot.mjs-style scenario: run
//     its steps (goto/click/fill/selectOption/press/wait — shot/shotEl steps
//     are ignored, we only care about the state they'd have screenshotted)
//     then audit the final page. Uses the scenario's baseUrl/viewport.
//   - Otherwise it's a URL, audited directly at 1280x900.
//   - Report goes to outFile if given, else stdout.
//
// Notes:
//   - Contrast is computed against the "effective background": walk up from
//     the text element until a fully-opaque background-color is found.
//     Elements behind a gradient/image/semi-transparent background are
//     skipped and counted (can't determine effective background from the
//     DOM alone) rather than guessed at.
//   - Alignment near-misses only fire when a "dominant" edge is established
//     (a majority of a sibling/component/gridline group already agrees on a
//     value) — a single outlier among otherwise-scattered elements is not
//     flagged. Deltas of 0-1px are treated as equal (rounding); >10px is
//     treated as intentionally different. Only the 2-10px band is flagged.
//
// Requires playwright-core (and a browser): `npm i -D playwright-core`
import { readFileSync, writeFileSync, readdirSync, existsSync } from 'fs';
import { chromium } from 'playwright-core';

const inputArg = process.argv[2];
const outArg = process.argv[3];
if (!inputArg) {
  console.error('usage: node style-inventory.mjs <url-or-scenario.json> [outFile.md]');
  process.exit(1);
}

// ---------------------------------------------------------------------
// Browser launch: the pinned playwright-core version may expect a newer
// chromium build than what's cached locally. Fall back to whatever
// chromium-<rev> build actually exists under PLAYWRIGHT_BROWSERS_PATH.
// ---------------------------------------------------------------------
async function launchBrowser() {
  try {
    return await chromium.launch();
  } catch (err) {
    const base = process.env.PLAYWRIGHT_BROWSERS_PATH || '/opt/pw-browsers';
    let dirs = [];
    try { dirs = readdirSync(base); } catch { /* fall through to rethrow */ }
    const candidate = dirs.filter((d) => /^chromium-\d+$/.test(d)).sort().reverse()[0];
    const exe = candidate ? `${base}/${candidate}/chrome-linux/chrome` : null;
    if (!exe || !existsSync(exe)) throw err;
    return await chromium.launch({ executablePath: exe });
  }
}

async function runSteps(page, baseUrl, steps) {
  for (const step of steps) {
    try {
      if (step.goto !== undefined) {
        await page.goto(baseUrl + step.goto, { waitUntil: 'networkidle' });
        await page.waitForTimeout(1500);
      } else if (step.click !== undefined) {
        await page.click(step.click, { timeout: 8000 });
        await page.waitForTimeout(800);
      } else if (step.fill !== undefined) {
        await page.fill(step.fill[0], step.fill[1], { timeout: 8000 });
        await page.waitForTimeout(800);
      } else if (step.selectOption !== undefined) {
        await page.selectOption(step.selectOption[0], step.selectOption[1], { timeout: 8000 });
        await page.waitForTimeout(800);
      } else if (step.press !== undefined) {
        await page.keyboard.press(step.press);
        await page.waitForTimeout(800);
      } else if (step.wait !== undefined) {
        await page.waitForTimeout(step.wait);
      }
      // shot / shotEl: ignored, we only need the state they'd capture
    } catch (err) {
      console.error(`step failed (${JSON.stringify(step)}): ${err.message}`);
    }
  }
}

// ---------------------------------------------------------------------
// In-page collection. Runs inside the browser via page.evaluate. Keep this
// self-contained (no closures over outer scope) — Playwright serializes it
// by stringifying the function.
// ---------------------------------------------------------------------
function collectStyleData() {
  const scrollX = window.scrollX;
  const scrollY = window.scrollY;

  function isVisible(el, cs) {
    if (cs.display === 'none') return false;
    if (cs.visibility === 'hidden' || cs.visibility === 'collapse') return false;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    return true;
  }

  function selectorFor(el) {
    const tag = el.tagName.toLowerCase();
    if (el.id) return '#' + el.id;
    const cls = Array.from(el.classList).slice(0, 3).join('.');
    return cls ? tag + '.' + cls : tag;
  }

  function ownText(el) {
    let t = '';
    for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent;
    t = t.replace(/\s+/g, ' ').trim();
    if (!t) {
      if (el.tagName === 'SELECT') {
        const opt = el.options[el.selectedIndex];
        t = opt ? opt.textContent.trim() : '';
      } else if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        t = el.value || el.getAttribute('placeholder') || '';
      }
    }
    return t;
  }

  function rgbToHex(r, g, b) {
    return '#' + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
  }

  function effectiveBg(el, selectorForFn) {
    let node = el;
    while (node) {
      const cs = getComputedStyle(node);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') {
        return { hex: null, indeterminate: true, reason: 'background-image on ' + selectorForFn(node) };
      }
      const m = cs.backgroundColor.match(/rgba?\(([^)]+)\)/);
      if (m) {
        const parts = m[1].split(',').map((s) => parseFloat(s.trim()));
        const a = parts.length > 3 ? parts[3] : 1;
        if (a >= 0.999) {
          return { hex: rgbToHex(parts[0], parts[1], parts[2]), indeterminate: false, reason: null };
        } else if (a > 0.001) {
          return { hex: null, indeterminate: true, reason: 'semi-transparent background on ' + selectorForFn(node) };
        }
      }
      node = node.parentElement;
    }
    return { hex: '#ffffff', indeterminate: false, reason: null };
  }

  const all = [document.body, ...document.body.querySelectorAll('*')];
  const idOf = new Map();
  const visible = [];
  let nextId = 0;
  for (const el of all) {
    const cs = getComputedStyle(el);
    if (isVisible(el, cs)) {
      idOf.set(el, nextId);
      visible.push({ el, id: nextId, cs });
      nextId++;
    }
  }

  function nearestVisibleAncestorId(el) {
    let p = el.parentElement;
    while (p) {
      if (idOf.has(p)) return idOf.get(p);
      p = p.parentElement;
    }
    return null;
  }

  const results = [];
  for (const { el, id, cs } of visible) {
    const rect = el.getBoundingClientRect();
    const text = ownText(el);
    const hasOwnText = text.length > 0;
    const rec = {
      id,
      parentId: nearestVisibleAncestorId(el),
      tag: el.tagName.toLowerCase(),
      idAttr: el.id || null,
      classes: Array.from(el.classList),
      selector: selectorFor(el),
      text: text.slice(0, 40),
      hasOwnText,
      rect: {
        x: +(rect.left + scrollX).toFixed(1),
        y: +(rect.top + scrollY).toFixed(1),
        width: +rect.width.toFixed(1),
        height: +rect.height.toFixed(1),
      },
      style: {
        fontFamily: cs.fontFamily,
        fontSize: cs.fontSize,
        fontWeight: cs.fontWeight,
        lineHeight: cs.lineHeight,
        color: cs.color,
        fill: cs.fill,
        backgroundColor: cs.backgroundColor,
        backgroundImage: cs.backgroundImage,
        borderTopLeftRadius: cs.borderTopLeftRadius,
        borderTopRightRadius: cs.borderTopRightRadius,
        borderBottomRightRadius: cs.borderBottomRightRadius,
        borderBottomLeftRadius: cs.borderBottomLeftRadius,
        boxShadow: cs.boxShadow,
        marginTop: cs.marginTop,
        marginRight: cs.marginRight,
        marginBottom: cs.marginBottom,
        marginLeft: cs.marginLeft,
        paddingTop: cs.paddingTop,
        paddingRight: cs.paddingRight,
        paddingBottom: cs.paddingBottom,
        paddingLeft: cs.paddingLeft,
        display: cs.display,
        position: cs.position,
        overflowX: cs.overflowX,
        overflowY: cs.overflowY,
        borderTopWidth: cs.borderTopWidth,
        borderRightWidth: cs.borderRightWidth,
        borderBottomWidth: cs.borderBottomWidth,
        borderLeftWidth: cs.borderLeftWidth,
      },
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    };
    if (hasOwnText) rec.effectiveBg = effectiveBg(el, selectorFor);
    results.push(rec);
  }

  return {
    url: location.href,
    title: document.title,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    docSize: { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight },
    elements: results,
  };
}

// ---------------------------------------------------------------------
// Host-side helpers (color math, clustering, formatting)
// ---------------------------------------------------------------------
function parseColor(str) {
  if (!str) return { r: 0, g: 0, b: 0, a: 0 };
  const m = str.match(/rgba?\(([^)]+)\)/);
  if (!m) return { r: 0, g: 0, b: 0, a: 0 };
  const parts = m[1].split(',').map((s) => parseFloat(s.trim()));
  return { r: parts[0] || 0, g: parts[1] || 0, b: parts[2] || 0, a: parts.length > 3 ? parts[3] : 1 };
}
function toHex({ r, g, b }) {
  return '#' + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
}
function colorDistance(a, b) {
  return Math.sqrt((a.r - b.r) ** 2 + (a.g - b.g) ** 2 + (a.b - b.b) ** 2);
}
function relLuminance({ r, g, b }) {
  const f = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function contrastRatio(a, b) {
  const l1 = relLuminance(a);
  const l2 = relLuminance(b);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}
function isLargeText(fontSizePx, fontWeight) {
  return fontSizePx >= 24 || (fontSizePx >= 18.5 && fontWeight >= 700);
}
// Greedy 1D clustering: values within `tol` of a cluster's running mean join it.
function clusterValues(values, tol) {
  const order = values.map((v, i) => ({ v, i })).sort((a, b) => a.v - b.v);
  const clusters = [];
  for (const { v, i } of order) {
    let placed = null;
    for (const c of clusters) {
      if (Math.abs(v - c.repSum / c.indices.length) <= tol) { placed = c; break; }
    }
    if (placed) { placed.indices.push(i); placed.repSum += v; }
    else clusters.push({ indices: [i], repSum: v });
  }
  return clusters.map((c) => ({ rep: c.repSum / c.indices.length, indices: c.indices }));
}
function dominantCluster(clusters, totalCount, minSize = 2, minShare = 0.5) {
  const sorted = [...clusters].sort((a, b) => b.indices.length - a.indices.length);
  const top = sorted[0];
  if (!top) return null;
  if (top.indices.length < minSize) return null;
  if (top.indices.length / totalCount < minShare) return null;
  return top;
}
function fmt(n) {
  return Math.abs(n - Math.round(n)) < 0.05 ? String(Math.round(n)) : n.toFixed(1);
}
function esc(s) {
  return (s || '').replace(/\|/g, '\\|').replace(/\n/g, ' ');
}
function short(s, n = 40) {
  if (!s) return '';
  return s.length > n ? s.slice(0, n) + '…' : s;
}
function label(rec) {
  const snippet = rec.text ? ` "${short(rec.text)}"` : '';
  return `\`${rec.selector}\`${snippet}`;
}

// ---------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------
let browser;
let raw;
let targetLabel;
try {
  browser = await launchBrowser();
  if (inputArg.endsWith('.json')) {
    const s = JSON.parse(readFileSync(inputArg, 'utf8'));
    const baseUrl = s.baseUrl || 'http://localhost:5173';
    const page = await browser.newPage({ viewport: s.viewport || { width: 1280, height: 900 } });
    page.setDefaultTimeout(8000);
    await runSteps(page, baseUrl, s.steps || []);
    raw = await page.evaluate(collectStyleData);
    targetLabel = `${inputArg} (final state after ${(s.steps || []).length} steps, baseUrl ${baseUrl})`;
  } else {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.setDefaultTimeout(8000);
    await page.goto(inputArg, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    raw = await page.evaluate(collectStyleData);
    targetLabel = inputArg;
  }
} finally {
  if (browser) await browser.close();
}

// ---------------------------------------------------------------------
// Normalize records
// ---------------------------------------------------------------------
// Border-radius can compute to a "%" string (e.g. a 50% circle) rather than
// px in some engines — resolve against the box size instead of assuming px.
function radiusPx(str, boxSize) {
  if (!str) return 0;
  if (str.endsWith('%')) return (parseFloat(str) / 100) * boxSize;
  return parseFloat(str) || 0;
}

const byId = new Map();
const records = raw.elements.map((e) => {
  // SVG <text> is painted via `fill`, not `color` — `color` on an SVG text
  // node is usually just the inherited CSS default and not what's on screen.
  const isSvgText = e.tag === 'text';
  const colorSrc = isSvgText && e.style.fill && e.style.fill !== 'none' ? e.style.fill : e.style.color;
  const color = parseColor(colorSrc);
  const bg = parseColor(e.style.backgroundColor);
  const radii = [
    radiusPx(e.style.borderTopLeftRadius, e.rect.width),
    radiusPx(e.style.borderTopRightRadius, e.rect.width),
    radiusPx(e.style.borderBottomRightRadius, e.rect.width),
    radiusPx(e.style.borderBottomLeftRadius, e.rect.width),
  ];
  const uniformRadius = radii.every((r) => Math.abs(r - radii[0]) < 0.5);
  const radiusLabel = uniformRadius ? `${fmt(radii[0])}px` : radii.map(fmt).join('/') + 'px';
  const border = {
    top: parseFloat(e.style.borderTopWidth) || 0,
    right: parseFloat(e.style.borderRightWidth) || 0,
    bottom: parseFloat(e.style.borderBottomWidth) || 0,
    left: parseFloat(e.style.borderLeftWidth) || 0,
  };
  const hasBorder = border.top > 0 || border.right > 0 || border.bottom > 0 || border.left > 0;
  const margin = {
    top: parseFloat(e.style.marginTop) || 0,
    right: parseFloat(e.style.marginRight) || 0,
    bottom: parseFloat(e.style.marginBottom) || 0,
    left: parseFloat(e.style.marginLeft) || 0,
  };
  const padding = {
    top: parseFloat(e.style.paddingTop) || 0,
    right: parseFloat(e.style.paddingRight) || 0,
    bottom: parseFloat(e.style.paddingBottom) || 0,
    left: parseFloat(e.style.paddingLeft) || 0,
  };
  const boxShadow = e.style.boxShadow && e.style.boxShadow !== 'none' ? e.style.boxShadow : null;
  const isBox = bg.a > 0.01 || hasBorder || !!boxShadow || radii.some((r) => r > 0.5);
  const blockish = /block|flex|grid|list-item|table/.test(e.style.display);
  const rec = {
    ...e,
    fontSizePx: parseFloat(e.style.fontSize) || 0,
    fontWeightNum: parseFloat(e.style.fontWeight) || 400,
    fontFamilyShort: e.style.fontFamily.split(',')[0].replace(/["']/g, '').trim(),
    color,
    colorHex: color.a > 0.5 ? toHex(color) : null,
    bg,
    bgHex: bg.a > 0.99 ? toHex(bg) : null,
    radii,
    radiusLabel,
    boxShadow,
    border,
    hasBorder,
    margin,
    padding,
    isBox,
    blockish,
  };
  byId.set(rec.id, rec);
  return rec;
});

const textRecs = records.filter((r) => r.hasOwnText);

// =======================================================================
// Section 1: Type census
// =======================================================================
function sectionTypeCensus() {
  const groups = new Map();
  for (const r of textRecs) {
    const key = `${r.fontFamilyShort}|${fmt(r.fontSizePx)}|${r.fontWeightNum}`;
    if (!groups.has(key)) groups.set(key, { family: r.fontFamilyShort, size: r.fontSizePx, weight: r.fontWeightNum, members: [] });
    groups.get(key).members.push(r);
  }
  const sorted = [...groups.values()].sort((a, b) => b.members.length - a.members.length);

  let out = '## 1. Type census\n\n';
  out += '_How to read this: each row is a distinct (font, size, weight) combination in use. A coherent UI typically has ~4-7 distinct sizes total; more suggests an eroding type scale._\n\n';
  out += `Distinct (family, size, weight) combos: **${sorted.length}**\n\n`;
  out += '| Font | Size | Weight | Count | Examples |\n|---|---|---|---|---|\n';
  for (const g of sorted) {
    const examples = g.members.slice(0, 2).map(label).join('; ');
    out += `| ${esc(g.family)} | ${fmt(g.size)}px | ${g.weight} | ${g.members.length} | ${examples} |\n`;
  }

  const sizes = [...new Set(textRecs.map((r) => fmt(r.fontSizePx)))].map(Number).sort((a, b) => a - b);
  out += `\n**Distinct font sizes in use:** ${sizes.length} (${sizes.map((s) => s + 'px').join(', ')})`;
  out += sizes.length > 7 ? ' — more than the ~4-7 a coherent scale usually needs.\n' : ' — within a typical coherent range.\n';

  const tiny = textRecs.filter((r) => r.fontSizePx > 0 && r.fontSizePx < 12);
  out += `\n**Sub-12px text (legibility risk):** ${tiny.length}\n`;
  if (tiny.length) {
    for (const r of tiny.slice(0, 20)) out += `- ${label(r)} — ${fmt(r.fontSizePx)}px\n`;
  }

  // Near-duplicate sizes: chain-cluster sizes that are ≤2px from their
  // neighbor (both used ≥3x) into a single band, rather than reporting every
  // pairwise combination inside a dense run (11, 11.5, 12, 12.5... would
  // otherwise produce a combinatorial explosion of near-identical flags).
  const sizeCounts = new Map();
  for (const r of textRecs) {
    const s = fmt(r.fontSizePx);
    sizeCounts.set(s, (sizeCounts.get(s) || 0) + 1);
  }
  const usedSizes = [...sizeCounts.entries()].filter(([, c]) => c >= 3).map(([s]) => Number(s)).sort((a, b) => a - b);
  const chains = [];
  for (const sz of usedSizes) {
    const last = chains[chains.length - 1];
    if (last && sz - last[last.length - 1] <= 2) last.push(sz);
    else chains.push([sz]);
  }
  const dupChains = chains.filter((c) => c.length >= 2);
  out += `\n**Near-duplicate size bands (sizes ≤2px apart, each used ≥3x — type-scale smell):** ${dupChains.length}\n`;
  for (const c of dupChains) {
    const span = (c[c.length - 1] - c[0]).toFixed(1);
    const parts = c.map((sz) => `${sz}px (×${sizeCounts.get(String(sz))})`).join(', ');
    out += `- ${parts} — ${c.length} sizes packed into a ${span}px band\n`;
  }

  return { md: out, stats: { distinctSizes: sizes.length, tiny: tiny.length, dupPairs: dupChains.length } };
}

// =======================================================================
// Section 2: Color & surface census
// =======================================================================
function sectionColorCensus() {
  let out = '## 2. Color & surface census\n\n';
  out += '_How to read this: distinct colors/radii/shadows in use, with usage counts. Near-duplicates (colors a few RGB units apart, each used repeatedly) usually mean an accidental variant rather than an intentional one._\n\n';

  function census(list, keyFn) {
    const m = new Map();
    for (const item of list) {
      const k = keyFn(item);
      if (k == null) continue;
      m.set(k, (m.get(k) || 0) + 1);
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }

  const textColors = census(textRecs, (r) => r.colorHex);
  out += `**Text colors:** ${textColors.length} distinct\n\n`;
  out += '| Color | Count |\n|---|---|\n';
  for (const [hex, count] of textColors) out += `| ${hex} | ${count} |\n`;

  const bgBoxes = records.filter((r) => r.bgHex);
  const bgColors = census(bgBoxes, (r) => r.bgHex);
  out += `\n**Background colors:** ${bgColors.length} distinct\n\n`;
  out += '| Color | Count |\n|---|---|\n';
  for (const [hex, count] of bgColors) out += `| ${hex} | ${count} |\n`;

  function nearDup(colorList) {
    const entries = colorList.map(([hex, count]) => ({ hex, count, rgb: { r: parseInt(hex.slice(1, 3), 16), g: parseInt(hex.slice(3, 5), 16), b: parseInt(hex.slice(5, 7), 16) } }));
    const flags = [];
    for (let i = 0; i < entries.length; i++) {
      for (let j = i + 1; j < entries.length; j++) {
        if (entries[i].count < 3 || entries[j].count < 3) continue;
        const d = colorDistance(entries[i].rgb, entries[j].rgb);
        if (d > 0 && d <= 12) flags.push([entries[i], entries[j], d]);
      }
    }
    return flags;
  }
  const textDups = nearDup(textColors);
  const bgDups = nearDup(bgColors);
  out += `\n**Near-duplicate text colors (each used ≥3x, RGB distance ≤12):** ${textDups.length}\n`;
  for (const [a, b, d] of textDups) out += `- ${a.hex} (×${a.count}) vs ${b.hex} (×${b.count}) — distance ${d.toFixed(1)}\n`;
  out += `\n**Near-duplicate background colors (each used ≥3x, RGB distance ≤12):** ${bgDups.length}\n`;
  for (const [a, b, d] of bgDups) out += `- ${a.hex} (×${a.count}) vs ${b.hex} (×${b.count}) — distance ${d.toFixed(1)}\n`;

  const boxes = records.filter((r) => r.isBox);
  const radii = census(boxes, (r) => r.radiusLabel);
  out += `\n**Border-radius values on visible boxes:** ${radii.length} distinct\n\n`;
  out += '| Radius | Count |\n|---|---|\n';
  for (const [rad, count] of radii) out += `| ${rad} | ${count} |\n`;

  const shadows = census(boxes.filter((r) => r.boxShadow), (r) => r.boxShadow);
  out += `\n**Box-shadow values:** ${shadows.length} distinct\n\n`;
  out += '| Shadow | Count |\n|---|---|\n';
  for (const [sh, count] of shadows) out += `| \`${esc(short(sh, 60))}\` | ${count} |\n`;

  return { md: out, stats: { textColors: textColors.length, bgColors: bgColors.length, textDups: textDups.length, bgDups: bgDups.length, radii: radii.length } };
}

// =======================================================================
// Section 3: Contrast
// =======================================================================
function sectionContrast() {
  let out = '## 3. Contrast\n\n';
  out += '_How to read this: WCAG contrast ratio between each text element and its effective background (nearest solid ancestor background). Failing = below 4.5:1 for normal text, 3:1 for large text (≥24px, or ≥18.5px bold). Elements behind a gradient/image/semi-transparent layer are skipped (can\'t be computed from the DOM) and counted separately._\n\n';

  const evaluable = textRecs.filter((r) => r.effectiveBg && !r.effectiveBg.indeterminate && r.colorHex);
  const skipped = textRecs.filter((r) => !r.effectiveBg || r.effectiveBg.indeterminate);

  const failures = [];
  for (const r of evaluable) {
    const fg = r.color;
    const bg = { r: parseInt(r.effectiveBg.hex.slice(1, 3), 16), g: parseInt(r.effectiveBg.hex.slice(3, 5), 16), b: parseInt(r.effectiveBg.hex.slice(5, 7), 16) };
    const ratio = contrastRatio(fg, bg);
    const large = isLargeText(r.fontSizePx, r.fontWeightNum);
    const threshold = large ? 3 : 4.5;
    if (ratio < threshold) failures.push({ r, ratio, threshold, large, bgHex: r.effectiveBg.hex });
  }
  failures.sort((a, b) => a.ratio - b.ratio);

  // Group identical (color, bg, size, weight) combos — the same badge/label
  // repeated N times is one design decision, not N separate findings.
  const failGroups = new Map();
  for (const f of failures) {
    const key = `${f.r.colorHex}|${f.bgHex}|${fmt(f.r.fontSizePx)}|${f.r.fontWeightNum}`;
    if (!failGroups.has(key)) failGroups.set(key, { ...f, members: [] });
    failGroups.get(key).members.push(f.r);
  }
  const groupedFailures = [...failGroups.values()].sort((a, b) => a.ratio - b.ratio);

  out += `Text elements checked: ${evaluable.length}. Skipped (indeterminate background): ${skipped.length}.\n\n`;
  out += `**Contrast failures:** ${failures.length} instances across ${groupedFailures.length} distinct color/size combos\n\n`;
  if (groupedFailures.length) {
    out += '| Elements | Text color | Effective bg | Size/weight | Ratio | Needs |\n|---|---|---|---|---|---|\n';
    for (const f of groupedFailures) {
      const examples = f.members.slice(0, 2).map(label).join('; ');
      const countNote = f.members.length > 2 ? ` (×${f.members.length})` : '';
      out += `| ${examples}${countNote} | ${f.r.colorHex} | ${f.bgHex} | ${fmt(f.r.fontSizePx)}px/${f.r.fontWeightNum} | ${f.ratio.toFixed(2)}:1 | ${f.threshold}:1 (${f.large ? 'large' : 'normal'}) |\n`;
    }
  }
  if (skipped.length) {
    out += `\n<details><summary>${skipped.length} elements skipped (indeterminate background)</summary>\n\n`;
    for (const r of skipped.slice(0, 15)) out += `- ${label(r)} — ${r.effectiveBg ? r.effectiveBg.reason : 'no effective background found'}\n`;
    out += '\n</details>\n';
  }

  return { md: out, stats: { failures: failures.length, skipped: skipped.length } };
}

// =======================================================================
// Section 4: Spacing
// =======================================================================
function sectionSpacing() {
  let out = '## 4. Spacing\n\n';
  out += '_How to read this: census of nonzero margin/padding values across block-level containers. A consistent spacing scale (e.g. multiples of 4) reads as crafted; scattered off-scale values read as accidental._\n\n';

  const containers = records.filter((r) => r.blockish);
  const counts = new Map();
  for (const r of containers) {
    for (const v of [r.margin.top, r.margin.right, r.margin.bottom, r.margin.left, r.padding.top, r.padding.right, r.padding.bottom, r.padding.left]) {
      if (v <= 0) continue;
      const k = fmt(v);
      counts.set(k, (counts.get(k) || 0) + 1);
    }
  }
  const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);

  // Detect the actual base grid instead of assuming 4px: gcd of all repeated
  // (count>=2) values. A design built on a 2px or 8px grid is just as
  // coherent as a 4px one; only flag values that don't fit *any* consistent
  // multiple-base found in this page.
  function gcd(a, b) { return b === 0 ? a : gcd(b, a % b); }
  const repeatedValues = sorted.filter(([, c]) => c >= 2).map(([v]) => Math.round(Number(v)));
  let base = repeatedValues.length ? repeatedValues.reduce((a, b) => gcd(a, b)) : 1;
  if (base < 1) base = 1;

  out += `Distinct nonzero spacing values: ${sorted.length}\n\n`;
  out += `Detected base scale: **${base}px** (largest value that evenly divides all repeated spacing values)\n\n`;
  out += `| Value (px) | Count | On ${base}px scale? |\n|---|---|---|\n`;
  for (const [v, c] of sorted.slice(0, 25)) {
    const onScale = Number(v) % base === 0;
    out += `| ${v} | ${c} | ${onScale ? 'yes' : 'no'} |\n`;
  }

  const offScale = sorted.filter(([v, c]) => Number(v) % base !== 0 && c >= 3);
  out += `\n**Off-scale values used ≥3 times:** ${offScale.length}\n`;
  for (const [v, c] of offScale) out += `- ${v}px (×${c})\n`;

  return { md: out, stats: { distinctValues: sorted.length, offScale: offScale.length, base } };
}

// =======================================================================
// Section 5: Alignment near-misses
// =======================================================================
function sectionAlignment() {
  let out = '## 5. Alignment near-misses\n\n';
  out += '_How to read this: elements that look like they should line up but are 2-10px off. 0-1px differences are rounding, not a finding. >10px off is treated as an intentional difference. Every flag names the elements and the exact pixel delta so you can check it against a screenshot._\n\n';

  const flags = [];

  // -- 5a. Sibling groups: cluster left edges and top edges among children
  // sharing a (nearest-visible) parent.
  const byParent = new Map();
  for (const r of records) {
    if (r.parentId == null) continue;
    if (!byParent.has(r.parentId)) byParent.set(r.parentId, []);
    byParent.get(r.parentId).push(r);
  }
  for (const [, members] of byParent) {
    if (members.length < 3) continue;
    for (const [axisName, axisKey] of [['left edge', 'x'], ['top edge', 'y']]) {
      const values = members.map((m) => m.rect[axisKey]);
      const clusters = clusterValues(values, 1);
      const dom = dominantCluster(clusters, members.length);
      if (!dom) continue;
      for (let i = 0; i < members.length; i++) {
        if (dom.indices.includes(i)) continue;
        const delta = values[i] - dom.rep;
        const abs = Math.abs(delta);
        if (abs >= 2 && abs <= 10) {
          flags.push({
            kind: 'sibling',
            text: `Sibling group (parent ${label(byId.get(members[0].parentId) || { selector: 'root', text: '' })}): ${label(members[i])} ${axisName} is ${delta > 0 ? '+' : ''}${fmt(delta)}px off the group's dominant ${axisName} (${fmt(dom.rep)}px, shared by ${dom.indices.length}/${members.length}).`,
          });
        }
      }
    }
  }

  // -- 5b. Repeated components: same primary class, >=3 instances.
  const byClass = new Map();
  for (const r of records) {
    if (!r.classes.length) continue;
    const key = r.classes[0];
    if (!byClass.has(key)) byClass.set(key, []);
    byClass.get(key).push(r);
  }
  // A nested repeated-component's row-offset is usually a side effect of an
  // *outer* repeated component (e.g. a taller "hero" card pushes every one of
  // its own internal rows down) — walk up to the outermost ancestor that is
  // itself a repeated-component instance, so those cascading rows get merged
  // into one flag instead of N.
  function topRepeatedAncestor(rec) {
    let p = rec.parentId != null ? byId.get(rec.parentId) : null;
    let found = null;
    while (p) {
      if (p.classes.length && byClass.has(p.classes[0]) && byClass.get(p.classes[0]).length >= 3) found = p;
      p = p.parentId != null ? byId.get(p.parentId) : null;
    }
    return found;
  }

  const componentRowRaw = [];
  for (const [cls, members] of byClass) {
    if (members.length < 3) continue;
    // Free-form text (SVG <text> tick labels, etc.) naturally varies in
    // rendered width with its content ("$9.3K" vs "May 24") — that's not a
    // component-sizing bug, so skip the width check for text-node groups.
    const autoWidthText = members.every((m) => m.tag === 'text');
    for (const [dim, dimLabel] of [['width', 'width'], ['height', 'height']]) {
      if (dim === 'width' && autoWidthText) continue;
      const values = members.map((m) => m.rect[dim]);
      const clusters = clusterValues(values, 1);
      const dom = dominantCluster(clusters, members.length);
      if (!dom) continue;
      for (let i = 0; i < members.length; i++) {
        if (dom.indices.includes(i)) continue;
        const delta = values[i] - dom.rep;
        const abs = Math.abs(delta);
        if (abs >= 2 && abs <= 10) {
          flags.push({
            kind: 'component',
            text: `Repeated component \`.${cls}\` (${members.length} instances): ${label(members[i])} ${dimLabel} is ${delta > 0 ? '+' : ''}${fmt(delta)}px off the common ${dimLabel} (${fmt(dom.rep)}px, shared by ${dom.indices.length}/${members.length}).`,
          });
        }
      }
    }
    // top-alignment within a visual row: coarse-cluster tops (tol 20px) to find rows,
    // then flag exact near-misses within any row of >=3.
    const tops = members.map((m) => m.rect.y);
    const rowClusters = clusterValues(tops, 20);
    for (const rc of rowClusters) {
      if (rc.indices.length < 3) continue;
      const rowMembers = rc.indices.map((i) => members[i]);
      const rowTops = rowMembers.map((m) => m.rect.y);
      const fine = clusterValues(rowTops, 1);
      const dom = dominantCluster(fine, rowMembers.length);
      if (!dom) continue;
      for (let i = 0; i < rowMembers.length; i++) {
        if (dom.indices.includes(i)) continue;
        const delta = rowTops[i] - dom.rep;
        const abs = Math.abs(delta);
        if (abs >= 2 && abs <= 10) {
          componentRowRaw.push({ cls, rec: rowMembers[i], delta, domRep: dom.rep, domShare: `${dom.indices.length}/${rowMembers.length}` });
        }
      }
    }
  }
  // Merge cascading component-row flags that share the same outer ancestor
  // instance and the same (rounded) delta — one root cause, one flag.
  const rowGroups = new Map();
  for (const f of componentRowRaw) {
    const ancestor = topRepeatedAncestor(f.rec);
    const key = ancestor ? `anc:${ancestor.id}|${Math.round(f.delta)}` : `solo:${f.rec.id}|${f.cls}`;
    if (!rowGroups.has(key)) rowGroups.set(key, { ancestor, delta: f.delta, items: [] });
    rowGroups.get(key).items.push(f);
  }
  for (const g of rowGroups.values()) {
    const delta = g.delta;
    if (g.ancestor && g.items.length > 1) {
      const parts = g.items.map((f) => `\`.${f.cls}\``).join(', ');
      flags.push({
        kind: 'component-row',
        text: `Repeated component instance ${label(g.ancestor)}: ${g.items.length} nested rows (${parts}) are all ${delta > 0 ? '+' : ''}${fmt(delta)}px off their siblings' dominant top (${fmt(g.items[0].domRep)}px, shared by ${g.items[0].domShare}) — likely one cascading cause (this instance is taller/shorter than its siblings), not ${g.items.length} separate issues.`,
      });
    } else {
      for (const f of g.items) {
        flags.push({
          kind: 'component-row',
          text: `Repeated component \`.${f.cls}\` row: ${label(f.rec)} top is ${delta > 0 ? '+' : ''}${fmt(delta)}px off the row's dominant top (${fmt(f.domRep)}px, shared by ${f.domShare}).`,
        });
      }
    }
  }

  // -- 5c. Page gridlines: left edges of large containers (width > 300px).
  const large = records.filter((r) => r.rect.width > 300);
  if (large.length >= 3) {
    const values = large.map((r) => r.rect.x);
    const clusters = clusterValues(values, 1);
    const dom = dominantCluster(clusters, large.length, 3, 0);
    if (dom) {
      for (let i = 0; i < large.length; i++) {
        if (dom.indices.includes(i)) continue;
        const delta = values[i] - dom.rep;
        const abs = Math.abs(delta);
        if (abs >= 2 && abs <= 10) {
          flags.push({
            kind: 'gridline',
            text: `Page gridline: ${label(large[i])} left edge is ${delta > 0 ? '+' : ''}${fmt(delta)}px off the dominant left gridline at ${fmt(dom.rep)}px (shared by ${dom.indices.length}/${large.length} large containers).`,
          });
        }
      }
    }
  }

  out += `**Flags:** ${flags.length}\n\n`;
  if (flags.length) {
    for (const f of flags) out += `- ${f.text}\n`;
  } else {
    out += '_None found._\n';
  }

  return { md: out, stats: { flags: flags.length } };
}

// =======================================================================
// Section 6: Overflow & clipping
// =======================================================================
function sectionOverflow() {
  let out = '## 6. Overflow & clipping\n\n';
  out += "_How to read this: text truncated by a clipped container (may be intentional ellipsis, or may be a layout bug hiding content), and static-positioned siblings whose boxes overlap — usually a sign two elements weren't meant to occupy the same space._\n\n";

  // Exclude the "visually-hidden" a11y pattern (clientWidth ~1px on purpose,
  // used to keep text screen-reader-only) — it's not a truncation bug.
  const truncated = records.filter(
    (r) =>
      r.hasOwnText &&
      (r.style.overflowX === 'hidden' || r.style.overflowX === 'clip') &&
      r.scrollWidth > r.clientWidth + 1 &&
      r.clientWidth > 2
  );
  out += `**Truncated text (scrollWidth > clientWidth, overflow-x hidden/clip):** ${truncated.length}\n`;
  for (const r of truncated) {
    out += `- ${label(r)} — scrollWidth ${r.scrollWidth}px vs clientWidth ${r.clientWidth}px\n`;
  }

  // SVG shape primitives (chart fills, lines, dots) are routinely layered on
  // purpose — e.g. an area-fill polygon sits directly under its own line by
  // design — so exclude them from the overlap check; text and HTML boxes are
  // where an overlap is actually suspicious.
  const svgShapeTags = new Set(['path', 'polygon', 'polyline', 'circle', 'rect', 'line', 'ellipse']);
  const overlaps = [];
  const byParent = new Map();
  for (const r of records) {
    if (r.parentId == null) continue;
    if (r.style.position !== 'static') continue;
    if (svgShapeTags.has(r.tag)) continue;
    if (!byParent.has(r.parentId)) byParent.set(r.parentId, []);
    byParent.get(r.parentId).push(r);
  }
  for (const [, members] of byParent) {
    for (let i = 0; i < members.length; i++) {
      for (let j = i + 1; j < members.length; j++) {
        const a = members[i], b = members[j];
        const ix = Math.min(a.rect.x + a.rect.width, b.rect.x + b.rect.width) - Math.max(a.rect.x, b.rect.x);
        const iy = Math.min(a.rect.y + a.rect.height, b.rect.y + b.rect.height) - Math.max(a.rect.y, b.rect.y);
        if (ix > 4 && iy > 4) {
          overlaps.push(`${label(a)} overlaps ${label(b)} by ${fmt(ix)}x${fmt(iy)}px`);
        }
      }
    }
  }
  out += `\n**Overlapping static siblings (>4px both axes):** ${overlaps.length}\n`;
  for (const o of overlaps) out += `- ${o}\n`;

  return { md: out, stats: { truncated: truncated.length, overlaps: overlaps.length } };
}

// =======================================================================
// Assemble report
// =======================================================================
const s1 = sectionTypeCensus();
const s2 = sectionColorCensus();
const s3 = sectionContrast();
const s4 = sectionSpacing();
const s5 = sectionAlignment();
const s6 = sectionOverflow();

let report = `# Style inventory\n\n`;
report += `Target: ${targetLabel}\n`;
report += `Page: ${raw.title} (${raw.url})\n`;
report += `Viewport: ${raw.viewport.width}x${raw.viewport.height}, document ${raw.docSize.width}x${raw.docSize.height}\n`;
report += `Visible elements audited: ${records.length} (${textRecs.length} text-bearing)\n\n`;
report += '---\n\n';
report += s1.md + '\n---\n\n';
report += s2.md + '\n---\n\n';
report += s3.md + '\n---\n\n';
report += s4.md + '\n---\n\n';
report += s5.md + '\n---\n\n';
report += s6.md + '\n---\n\n';

report += '## Summary\n\n';
report += `- ${s1.stats.distinctSizes} distinct font sizes; ${s1.stats.tiny} sub-12px text elements; ${s1.stats.dupPairs} near-duplicate size pairs\n`;
report += `- ${s2.stats.textColors} distinct text colors, ${s2.stats.bgColors} distinct backgrounds; ${s2.stats.textDups} near-duplicate text colors, ${s2.stats.bgDups} near-duplicate backgrounds; ${s2.stats.radii} distinct border-radius values\n`;
report += `- ${s3.stats.failures} contrast failures (${s3.stats.skipped} elements skipped as indeterminate)\n`;
report += `- ${s4.stats.distinctValues} distinct spacing values (base scale ${s4.stats.base}px); ${s4.stats.offScale} off-scale values used ≥3 times\n`;
report += `- ${s5.stats.flags} alignment near-misses\n`;
report += `- ${s6.stats.truncated} truncated-text elements; ${s6.stats.overlaps} overlapping sibling pairs\n`;

if (outArg) {
  writeFileSync(outArg, report);
  console.log(`wrote ${outArg}`);
} else {
  console.log(report);
}
