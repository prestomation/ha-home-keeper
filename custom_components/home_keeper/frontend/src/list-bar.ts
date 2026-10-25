/**
 * The pure parts of the task list bar (#488): which filters are on, the stored fold
 * state of the filter controls, and the text of the spend button.
 *
 * The bar itself is drawn by `panel-controls.ts` and `panel-spend.ts`. What is here
 * takes no `PanelHost`, so the vitest suite and the mutation run test it directly.
 */

import { t } from './i18n';
import type { TaskFilter } from './panel-types';

/** The value stored under `LS_CONTROLS` when the filter controls are open. */
export const CONTROLS_OPEN = 'open';
/** The value stored under `LS_CONTROLS` when the filter controls are folded. */
export const CONTROLS_FOLDED = 'folded';

/**
 * Read the stored fold state. Folded is the default: a missing value, a value from a
 * later release and a value that a user typed all read as folded.
 */
export function parseControlsOpen(raw: string | null | undefined): boolean {
  return raw === CONTROLS_OPEN;
}

/** One active filter, as a chip with a clear button. */
export interface ListChip {
  /** Which filter the chip clears. */
  key: 'scope' | 'profile' | 'query';
  /** The visible text of the chip. */
  label: string;
}

/** The list state that the chips describe. */
export interface ListFilterState {
  filter: TaskFilter;
  /** The name of the active saved Profile, or null when no Profile is active. */
  profileName: string | null;
  query: string;
}

/**
 * The active filters, in the order of the controls: the Profile or the scope pill,
 * then the search text. A Profile replaces the scope pill, so the 2 never show
 * together. Group by and Layout arrange the list and are not filters.
 */
export function activeListChips(state: ListFilterState): ListChip[] {
  const chips: ListChip[] = [];
  if (state.profileName) {
    chips.push({ key: 'profile', label: chipText(t('filter.profile'), state.profileName) });
  } else if (state.filter !== 'all') {
    chips.push({ key: 'scope', label: t(`filter.${state.filter}`) });
  }
  const query = state.query.trim();
  if (query) chips.push({ key: 'query', label: chipText(t('filter.search'), query) });
  return chips;
}

function chipText(label: string, value: string): string {
  return t('filter.chip', { label, value });
}

/** The amount and the icon on the spend button. */
export interface SpendButtonText {
  icon: string;
  text: string;
}

/** Currency symbols that have an icon of their own. The button then shows only the number. */
const SYMBOL_ICONS: Record<string, string> = {
  $: 'mdi:currency-usd',
  '€': 'mdi:currency-eur',
  '£': 'mdi:currency-gbp',
  '¥': 'mdi:currency-jpy',
  '₹': 'mdi:currency-inr',
};

/** The fallback icon for a currency with no symbol icon. */
export const SPEND_ICON = 'mdi:cash-multiple';

/**
 * The short total on the spend button: whole units, with the currency symbol as the
 * icon when one exists. Another currency keeps its symbol in the text and gets a
 * generic icon. With no currency, or an unknown code, the button shows the number.
 */
export function spendButtonText(
  amount: number,
  currency: string | undefined,
  lang: string | undefined,
): SpendButtonText {
  const whole = Math.round(amount);
  const number = formatWhole(whole, lang);
  // Stryker disable next-line ConditionalExpression: equivalent. With no currency,
  // `Intl.NumberFormat` with `style: 'currency'` throws, and the catch below returns
  // the same value.
  if (!currency) return { icon: SPEND_ICON, text: number };
  let parts: Intl.NumberFormatPart[];
  try {
    parts = new Intl.NumberFormat(lang, {
      style: 'currency',
      currency,
      currencyDisplay: 'narrowSymbol',
      maximumFractionDigits: 0,
      minimumFractionDigits: 0,
    }).formatToParts(whole);
  } catch {
    return { icon: SPEND_ICON, text: number };
  }
  // Stryker disable next-line OptionalChaining,StringLiteral: equivalent. A currency
  // format always has a currency part, and any symbol with no icon reads the same.
  const symbol = parts.find((part) => part.type === 'currency')?.value ?? '';
  const icon = SYMBOL_ICONS[symbol];
  if (icon) return { icon, text: number };
  return { icon: SPEND_ICON, text: parts.map((part) => part.value).join('') };
}

function formatWhole(value: number, lang: string | undefined): string {
  try {
    // Stryker disable next-line ObjectLiteral: equivalent. The value is a whole
    // number already, so the default fraction digits give the same text.
    return new Intl.NumberFormat(lang, { maximumFractionDigits: 0 }).format(value);
  } catch {
    return String(value);
  }
}
