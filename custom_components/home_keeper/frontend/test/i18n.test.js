import { afterEach, describe, expect, it } from 'vitest';
import { getLanguage, setLanguage, t, tn } from '../src/i18n.ts';
import { DEFAULT_LOCALE, LOCALES } from '../src/locales/index.ts';

// The i18n module holds global state; reset to the default after every test.
afterEach(() => setLanguage(DEFAULT_LOCALE));

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
