import { DEFAULT_LOCALE, LOCALES } from './locales';

/**
 * Tiny dependency-free i18n for the panel. Locale tables are bundled into the
 * IIFE at build time (see `locales/index.ts`), so there is no runtime fetch and
 * the panel works offline. Lookups fall back per-key to English and finally to
 * the raw key, so a missing translation never renders `undefined`.
 */

type Table = Record<string, string>;

const fallback: Table = LOCALES[DEFAULT_LOCALE];
let current: Table = fallback;
let currentLang: string = DEFAULT_LOCALE;
let plural: Intl.PluralRules = new Intl.PluralRules(DEFAULT_LOCALE);
// `Intl.ListFormat` needs the ES2021 lib, which is why `tsconfig.json` asks for it
// while `target` stays ES2020: `lib` only says what the runtime is known to have,
// and a built-in method is never downlevelled. That file is strict JSON, not JSONC
// — hassfest parses it and a `//` comment fails the `test` job — so the reason
// lives here.
//
// No options object: "long"/"conjunction" are already the defaults, so passing
// them would add a literal that mutates to `{}` with identical behaviour — an
// equivalent mutant no assertion can kill.
let list: Intl.ListFormat = new Intl.ListFormat(DEFAULT_LOCALE);

/** Resolve an HA language code (e.g. "en-GB", "pt-BR", "zh-Hans") to a table. */
function resolve(lang: string): { table: Table; tag: string } {
  const lc = lang.toLowerCase();
  // exact match (handles "pt-br", "zh-hans")
  for (const key of Object.keys(LOCALES)) {
    if (key.toLowerCase() === lc) return { table: LOCALES[key], tag: key };
  }
  // base language ("en-gb" -> "en")
  const base = lc.split('-')[0];
  for (const key of Object.keys(LOCALES)) {
    if (key.toLowerCase() === base) return { table: LOCALES[key], tag: key };
  }
  return { table: fallback, tag: DEFAULT_LOCALE };
}

/** Point the module at a locale; safe to call on every `hass` update. */
export function setLanguage(lang?: string): void {
  const { table, tag } = resolve(lang || DEFAULT_LOCALE);
  current = table;
  currentLang = tag;
  try {
    plural = new Intl.PluralRules(tag);
    list = new Intl.ListFormat(tag);
  } catch {
    plural = new Intl.PluralRules(DEFAULT_LOCALE);
    list = new Intl.ListFormat(DEFAULT_LOCALE);
  }
}

/** The active locale tag (mainly for tests/diagnostics). */
export function getLanguage(): string {
  return currentLang;
}

function interpolate(tmpl: string, params?: Record<string, string | number>): string {
  if (!params) return tmpl;
  return tmpl.replace(/\{(\w+)\}/g, (_m, name: string) =>
    params[name] != null ? String(params[name]) : `{${name}}`,
  );
}

/** Translate a key, interpolating `{param}` tokens. */
export function t(key: string, params?: Record<string, string | number>): string {
  const tmpl = current[key] ?? fallback[key] ?? key;
  return interpolate(tmpl, params);
}

/**
 * Join *items* as prose in the active language: "a", "a and b", "a, b and c".
 *
 * For a sentence that names a variable set of things, where enumerating every
 * outcome as its own string does not scale — three switches would need eight.
 * `Intl.ListFormat` knows each language's separator and conjunction, which a
 * hand-rolled join does not. It answers '' for an empty list on its own, so
 * there is no guard clause here to add a mutant nothing would kill.
 */
export function tlist(items: string[]): string {
  return list.format(items);
}

/**
 * Plural-aware translate. Picks `"<key>.<category>"` via the locale's CLDR
 * plural rules (one/few/many/other/…), falling back to `"<key>.other"`. The
 * count is available to the template as `{n}` unless overridden in `params`.
 */
export function tn(
  key: string,
  n: number,
  params?: Record<string, string | number>,
): string {
  const cat = plural.select(n);
  const candidate = `${key}.${cat}`;
  const otherKey = `${key}.other`;
  const tmpl =
    current[candidate] ??
    current[otherKey] ??
    fallback[candidate] ??
    fallback[otherKey] ??
    key;
  return interpolate(tmpl, { n, ...params });
}
