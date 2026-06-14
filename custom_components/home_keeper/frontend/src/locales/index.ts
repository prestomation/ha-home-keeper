// Locale tables, statically imported so Rollup inlines them into the single
// IIFE bundle (no runtime fetch; works offline). English is the source of truth
// and the fallback; every other table is parity-checked against it in tests.
import en from './en.json';
import de from './de.json';
import fr from './fr.json';
import es from './es.json';
import it from './it.json';
import nl from './nl.json';
import pl from './pl.json';
import ptBR from './pt-BR.json';
import nb from './nb.json';
import sv from './sv.json';
import da from './da.json';
import fi from './fi.json';
import cs from './cs.json';
import ru from './ru.json';
import zhHans from './zh-Hans.json';
import ca from './ca.json';

export const DEFAULT_LOCALE = 'en';

export const LOCALES: Record<string, Record<string, string>> = {
  en,
  de,
  fr,
  es,
  it,
  nl,
  pl,
  'pt-BR': ptBR,
  nb,
  sv,
  da,
  fi,
  cs,
  ru,
  'zh-Hans': zhHans,
  ca,
};
