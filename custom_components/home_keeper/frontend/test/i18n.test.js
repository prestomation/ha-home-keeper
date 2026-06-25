import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { getLanguage, setLanguage, t, tn } from '../src/i18n.ts';
import { DEFAULT_LOCALE, LOCALES } from '../src/locales/index.ts';
import unusedKeysBaseline from './unused-keys-baseline.json';

// The i18n module holds global state; reset to the default after every test.
afterEach(() => setLanguage(DEFAULT_LOCALE));

// --- Shared helpers for source/value-level guardrails -----------------------

// Strings identical to English by design in every language. `app.title` is the
// product name, `due.none` is an em dash, and `managed.completionHint` is the
// bare `{prompt}` placeholder (no translatable text). Keep this tiny.
const INTENTIONALLY_IDENTICAL = new Set(['app.title', 'due.none', 'managed.completionHint']);

// Per-locale cognates / loanwords whose translation is genuinely identical to
// English in that language (reviewed individually): German "Name"/"Status",
// French "Stock"/"Date", Dutch "week"/"Label", universal "Model"/"Link"/"Type".
// Locale-specific, so the guard stays strict for every other locale.
// `field.doc_url` is "URL" in every language (a universal token); `field.doc_name`
// is a cognate ("Name") in the languages noted below.
const COGNATE_IDENTICAL = {
  ca: ['field.cost', 'field.doc_url', 'field.model', 'field.notes', 'field.sensor_entity_id', 'meta.seed.notes', 'opt.meta.text', 'settings.general_heading'],
  cs: ['field.doc_url', 'field.model', 'opt.meta.text'],
  da: ['chip.orphaned', 'field.doc_url', 'field.kind', 'field.model', 'field.note', 'field.sensor_entity_id', 'field.type', 'group.integration', 'group.status', 'opt.meta.link'],
  de: ['chip.orphaned', 'detail.about', 'field.doc_name', 'field.doc_url', 'field.name', 'field.sensor_entity_id', 'group.integration', 'group.status', 'opt.meta.link', 'opt.meta.text'],
  es: ['field.doc_url', 'field.sensor_entity_id', 'settings.general_heading'],
  fi: ['field.doc_url'],
  fr: ['completion.photo', 'field.doc_url', 'field.kind', 'field.note', 'field.notes', 'field.stock', 'field.type', 'meta.seed.notes', 'notify.heading', 'notify.style', 'opt.meta.date'],
  it: ['field.area_id', 'field.doc_url', 'group.area', 'opt.meta.link'],
  nb: ['field.doc_url', 'field.kind', 'field.sensor_entity_id', 'field.type', 'group.status'],
  nl: ['detail.about', 'field.doc_url', 'field.kind', 'field.label', 'field.model', 'field.sensor_entity_id', 'field.type', 'group.status', 'opt.meta.link', 'recurrence.unit.week.one', 'section.later'],
  pl: ['field.doc_url', 'field.model', 'group.status', 'opt.meta.link'],
  'pt-BR': ['field.doc_url', 'field.sensor_entity_id', 'group.status', 'opt.meta.link'],
  ru: ['field.doc_url'],
  sv: ['chip.orphaned', 'field.doc_url', 'field.sensor_entity_id', 'group.integration', 'group.status', 'opt.meta.text'],
  'zh-Hans': ['field.doc_url'],
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

describe('t()', () => {
  it('looks up a key in the active locale', () => {
    setLanguage('en');
    expect(t('tab.tasks')).toBe('Tasks');
    setLanguage('de');
    expect(t('tab.tasks')).toBe(LOCALES.de['tab.tasks']);
  });

  it('interpolates {param} tokens', () => {
    setLanguage('en');
    expect(t('asset.warrantyTo', { date: '2030-01-01' })).toBe('warranty to 2030-01-01');
  });

  it('leaves unknown placeholders intact', () => {
    setLanguage('en');
    expect(t('asset.warrantyTo', {})).toBe('warranty to {date}');
  });

  it('falls back to English, then to the raw key', () => {
    // A key only present in English falls back when another locale lacks it.
    // Use a guaranteed-missing key to prove the raw-key fallback.
    expect(t('totally.missing.key')).toBe('totally.missing.key');
  });
});

describe('tn() pluralization', () => {
  it('selects one/other for English', () => {
    setLanguage('en');
    expect(tn('asset.parts', 1)).toBe('1 part');
    expect(tn('asset.parts', 3)).toBe('3 parts');
  });

  it('uses CLDR categories for Polish (few/many)', () => {
    setLanguage('pl');
    const few = new Intl.PluralRules('pl').select(3); // 'few'
    const many = new Intl.PluralRules('pl').select(5); // 'many'
    expect(few).toBe('few');
    expect(many).toBe('many');
    // pl provides .few/.many; tn should pick the matching category key and
    // interpolate {n}.
    expect(tn('asset.parts', 3)).toBe(LOCALES.pl['asset.parts.few'].replace('{n}', '3'));
    expect(tn('asset.parts', 5)).toBe(LOCALES.pl['asset.parts.many'].replace('{n}', '5'));
  });

  it('falls back to .other when a category key is absent', () => {
    // Russian selects 'many' for 11; even if a niche key were missing the
    // template must never be undefined.
    setLanguage('ru');
    expect(typeof tn('asset.parts', 11)).toBe('string');
    expect(tn('asset.parts', 11)).not.toContain('undefined');
  });
});

describe('setLanguage() locale resolution', () => {
  it('matches an exact tag, including region forms', () => {
    setLanguage('pt-BR');
    expect(getLanguage()).toBe('pt-BR');
    setLanguage('zh-Hans');
    expect(getLanguage()).toBe('zh-Hans');
  });

  it('matches case-insensitively and by base language', () => {
    setLanguage('EN-GB');
    expect(getLanguage()).toBe('en');
    setLanguage('de-AT');
    expect(getLanguage()).toBe('de');
  });

  it('falls back to the default for unknown or empty languages', () => {
    setLanguage('xx');
    expect(getLanguage()).toBe(DEFAULT_LOCALE);
    setLanguage(undefined);
    expect(getLanguage()).toBe(DEFAULT_LOCALE);
  });
});

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
