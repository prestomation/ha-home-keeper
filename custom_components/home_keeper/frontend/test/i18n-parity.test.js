import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { DEFAULT_LOCALE, LOCALES } from '../src/locales/index.ts';
import unusedKeysBaseline from './unused-keys-baseline.json';

// Translation quality gates: locale key/placeholder parity, untranslated leaks,
// key usage and plural completeness. The key-usage gate reads `src/*.ts` off
// disk and analyses it as text, so this file is deliberately separate from the
// behavioural `i18n.test.js` and is excluded from the mutation run — under
// Stryker it would be reading *mutated* source and scoring bogus kills. See
// `vitest.stryker.config.js`.

// --- Shared helpers for source/value-level guardrails -----------------------

// Strings identical to English by design in every language. `app.title` is the
// product name, `due.none` is an em dash, and `managed.completionHint` is the
// bare `{prompt}` placeholder (no translatable text). Keep this tiny.
const INTENTIONALLY_IDENTICAL = new Set(['app.title', 'due.none', 'managed.completionHint']);

// Per-locale cognates / loanwords whose translation is genuinely identical to
// English in that language (reviewed individually): German "Name"/"Status",
// French "Stock"/"Date", Dutch "week"/"Label", universal "Model"/"Link"/"Type".
// Locale-specific, so the guard stays strict for every other locale.
// `detail.id` is likewise "ID" everywhere except Finnish and Polish.
// `field.doc_url` is "URL" in every language (a universal token); `field.doc_name`
// is a cognate ("Name") in the languages noted below. `notify.opt.normal` is the
// urgency ladder's middle rung, and "Normal" is the word for it unchanged in the
// Romance and Scandinavian languages listed (the others inflect it: "Normale",
// "Normaal", "Normalne", "Normální", "Normaali").
const COGNATE_IDENTICAL = {
  ca: ['detail.id', 'field.cost', 'field.doc_url', 'field.model', 'field.notes', 'field.sensor_entity_id', 'meta.seed.notes', 'notify.opt.normal', 'opt.meta.text', 'section.notes', 'settings.exclusions', 'settings.general_heading', 'tab.documents'],
  cs: ['detail.id', 'field.doc_url', 'field.model', 'opt.meta.text'],
  da: ['chip.orphaned', 'detail.id', 'field.doc_url', 'field.kind', 'field.model', 'field.note', 'field.sensor_entity_id', 'field.type', 'group.integration', 'group.status', 'notify.opt.normal', 'opt.meta.link'],
  de: ['chip.orphaned', 'detail.about', 'detail.id', 'due.in_units', 'field.doc_name', 'field.doc_url', 'field.name', 'field.sensor_entity_id', 'group.integration', 'group.status', 'notify.opt.normal', 'opt.meta.link', 'opt.meta.text'],
  es: ['detail.id', 'field.doc_url', 'field.sensor_entity_id', 'notify.opt.normal', 'settings.general_heading'],
  fi: ['field.doc_url'],
  fr: ['completion.photo', 'detail.id', 'field.doc_url', 'field.kind', 'field.note', 'field.notes', 'field.stock', 'field.type', 'meta.seed.notes', 'notify.defaultName', 'notify.heading', 'notify.style', 'opt.meta.date', 'section.notes', 'settings.exclusions', 'tab.documents'],
  it: ['detail.id', 'field.area_id', 'field.doc_url', 'group.area', 'opt.meta.link'],
  nb: ['detail.id', 'field.doc_url', 'field.kind', 'field.sensor_entity_id', 'field.type', 'group.status', 'notify.opt.normal'],
  nl: ['detail.about', 'detail.id', 'field.doc_url', 'field.kind', 'field.label', 'field.model', 'field.sensor_entity_id', 'field.type', 'group.status', 'opt.meta.link', 'recurrence.unit.week.one', 'section.later'],
  pl: ['field.doc_url', 'field.model', 'group.status', 'opt.meta.link'],
  'pt-BR': ['detail.id', 'field.doc_url', 'field.sensor_entity_id', 'group.status', 'notify.opt.normal', 'opt.meta.link'],
  ru: ['detail.id', 'field.doc_url'],
  sv: ['chip.orphaned', 'detail.id', 'field.doc_url', 'field.sensor_entity_id', 'group.integration', 'group.status', 'notify.opt.normal', 'opt.meta.text'],
  'zh-Hans': ['detail.id', 'field.doc_url'],
};

// Concatenate all panel TypeScript sources once for static key analysis.
const SRC = (() => {
  // CI runs vitest from the repo root; fall back to the frontend dir if invoked
  // from there directly.
  const rel = 'custom_components/home_keeper/frontend/src';
  const dir = existsSync(resolve(process.cwd(), rel)) ? resolve(process.cwd(), rel) : resolve(process.cwd(), 'src');
  return readdirSync(dir)
    .filter((f) => f.endsWith('.ts'))
    .map((f) => readFileSync(`${dir}/${f}`, 'utf8'))
    .join('\n');
})();

// Literal keys passed to t()/tn(): `fn('key')`, `fn('key', …)` — quote then ) or ,
const literalKeys = (fn) =>
  [...SRC.matchAll(new RegExp(`\\b${fn}\\(\\s*['"]([^'"]+)['"]\\s*[),]`, 'g'))].map((m) => m[1]);
const T_KEYS = literalKeys('t');
const TN_KEYS = literalKeys('tn');

// Dynamic key prefixes: `fn('p.' + …)` concat or `fn(\`p.${…}\`)` template.
const DYN_PREFIXES = [
  ...new Set([
    ...[...SRC.matchAll(/\b(?:t|tn)\(\s*['"]([^'"]*)['"]\s*\+/g)].map((m) => m[1]),
    ...[...SRC.matchAll(/\b(?:t|tn)\(\s*`([^`$]*)\$\{/g)].map((m) => m[1]),
  ]),
].filter((p) => p.includes('.'));

// Dotted keys appearing as bare quoted literals (e.g. labelKey lookup tables).
const QUOTED_KEYS = new Set(
  [...SRC.matchAll(/['"]([a-z][\w]*(?:\.[\w]+)+)['"]/g)].map((m) => m[1]),
);

const PLURAL_SUFFIX = /^(.*)\.(one|two|few|many|zero|other)$/;

describe('locale key parity', () => {
  const enKeys = Object.keys(LOCALES[DEFAULT_LOCALE]).sort();
  for (const [lang, table] of Object.entries(LOCALES)) {
    if (lang === DEFAULT_LOCALE) continue;
    it(`${lang} contains every English key`, () => {
      const keys = new Set(Object.keys(table));
      const missing = enKeys.filter((k) => !keys.has(k));
      expect(missing).toEqual([]);
    });
    it(`${lang} preserves placeholder tokens for shared keys`, () => {
      const tokens = (s) => (s.match(/\{\w+\}/g) || []).sort();
      for (const key of enKeys) {
        if (table[key] === undefined) continue;
        expect(tokens(table[key])).toEqual(tokens(LOCALES[DEFAULT_LOCALE][key]));
      }
    });
  }
});

describe('untranslated-string guard', () => {
  // A locale value equal to its English source is almost always an untranslated
  // leak. The only escape hatch is INTENTIONALLY_IDENTICAL (identical by design).
  const en = LOCALES[DEFAULT_LOCALE];
  for (const [lang, table] of Object.entries(LOCALES)) {
    if (lang === DEFAULT_LOCALE) continue;
    it(`${lang} ships no English-identical strings`, () => {
      const allowed = new Set([...INTENTIONALLY_IDENTICAL, ...(COGNATE_IDENTICAL[lang] || [])]);
      const leaks = Object.keys(en)
        .filter((k) => table[k] === en[k] && !allowed.has(k))
        .sort();
      // Translate these, or (if identical by design) add to the allowlist above.
      expect(leaks).toEqual([]);
    });
  }
});

describe('key usage', () => {
  const enKeys = Object.keys(LOCALES[DEFAULT_LOCALE]);

  it('every literal t() key exists in the English table', () => {
    const missing = T_KEYS.filter((k) => LOCALES[DEFAULT_LOCALE][k] === undefined);
    expect(missing).toEqual([]);
  });

  it('every literal tn() base key has at least an .other category', () => {
    const missing = TN_KEYS.filter((k) => LOCALES[DEFAULT_LOCALE][`${k}.other`] === undefined);
    expect(missing).toEqual([]);
  });

  it('no new unused English keys (heuristic; baseline may only shrink)', () => {
    const tnBase = new Set(TN_KEYS);
    const isUsed = (key) => {
      if (T_KEYS.includes(key) || TN_KEYS.includes(key) || QUOTED_KEYS.has(key)) return true;
      const m = key.match(PLURAL_SUFFIX);
      if (m && (tnBase.has(m[1]) || QUOTED_KEYS.has(m[1]))) return true;
      return DYN_PREFIXES.some((p) => key.startsWith(p));
    };
    const unused = enKeys.filter((k) => !isUsed(k)).sort();
    const baseline = new Set(unusedKeysBaseline);
    const newlyUnused = unused.filter((k) => !baseline.has(k));
    const nowUsed = [...baseline].filter((k) => !unused.includes(k)).sort();
    // newlyUnused: wire the key up in the panel, or delete it from en.json.
    // nowUsed: a baselined key is referenced now — remove it from the baseline.
    expect({ newlyUnused, nowUsed }).toEqual({ newlyUnused: [], nowUsed: [] });
  });
});

describe('plural-category completeness', () => {
  // tn() falls back to `.other`, but Slavic/Romance grammar needs few/many. For
  // each locale, every plural base key must define every CLDR category the
  // locale uses.
  const en = LOCALES[DEFAULT_LOCALE];
  const pluralBases = new Set();
  for (const k of Object.keys(en)) {
    const m = k.match(PLURAL_SUFFIX);
    if (m) pluralBases.add(m[1]);
  }
  for (const [lang, table] of Object.entries(LOCALES)) {
    if (lang === DEFAULT_LOCALE) continue;
    it(`${lang} defines every plural category it uses`, () => {
      const cats = new Intl.PluralRules(lang).resolvedOptions().pluralCategories;
      const missing = [];
      for (const base of pluralBases) {
        if (en[`${base}.other`] === undefined) continue;
        for (const c of cats) if (table[`${base}.${c}`] === undefined) missing.push(`${base}.${c}`);
      }
      // Add the missing plural form(s) to the locale.
      expect(missing.sort()).toEqual([]);
    });
  }
});
