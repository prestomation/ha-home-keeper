/**
 * The task list bar (#488): the active-filter chips, the stored fold state and the
 * short total on the spend button.
 */

import { describe, expect, it } from 'vitest';
import {
  CONTROLS_FOLDED,
  CONTROLS_OPEN,
  SPEND_ICON,
  activeListChips,
  parseControlsOpen,
  spendButtonText,
} from '../src/list-bar.ts';

describe('parseControlsOpen', () => {
  it('reads only the open value as open', () => {
    expect(CONTROLS_OPEN).toBe('open');
    expect(CONTROLS_FOLDED).toBe('folded');
    expect(parseControlsOpen('open')).toBe(true);
  });

  it.each([['folded'], [null], [undefined], [''], ['true'], ['OPEN'], ['grid']])(
    '%j reads as folded',
    (raw) => {
      expect(parseControlsOpen(raw)).toBe(false);
    },
  );
});

describe('activeListChips', () => {
  const base = { filter: 'all', profileName: null, query: '' };

  it('is empty for the whole list', () => {
    expect(activeListChips(base)).toEqual([]);
  });

  it.each([
    ['overdue', 'Overdue'],
    ['soon', 'Due soon'],
    ['shopping', 'Shopping'],
    ['counted', 'Counted'],
  ])('names the %s scope pill', (filter, label) => {
    expect(activeListChips({ ...base, filter })).toEqual([{ key: 'scope', label }]);
  });

  it('names the Profile, and leaves out the scope pill that the Profile replaces', () => {
    expect(activeListChips({ ...base, filter: 'overdue', profileName: 'Chores' })).toEqual([
      { key: 'profile', label: 'Profile: Chores' },
    ]);
  });

  it('adds the search text last, trimmed', () => {
    expect(activeListChips({ ...base, filter: 'soon', query: '  filter ' })).toEqual([
      { key: 'scope', label: 'Due soon' },
      { key: 'query', label: 'Search: filter' },
    ]);
  });

  it('ignores search text that is only spaces', () => {
    expect(activeListChips({ ...base, query: '   ' })).toEqual([]);
  });

  it('gives 1 chip for each kind with a Profile and a search', () => {
    const chips = activeListChips({ filter: 'all', profileName: 'Garage', query: 'oil' });
    expect(chips.map((c) => c.key)).toEqual(['profile', 'query']);
  });

  it('keeps user text as text', () => {
    const [chip] = activeListChips({ ...base, query: '<b>x</b>' });
    expect(chip.label).toBe('Search: <b>x</b>');
  });
});

describe('spendButtonText', () => {
  it('shows a symbol icon and the whole number for dollars', () => {
    expect(spendButtonText(324.94, 'USD', 'en')).toEqual({ icon: 'mdi:currency-usd', text: '325' });
  });

  it('rounds half up and groups thousands', () => {
    expect(spendButtonText(1234.5, 'USD', 'en')).toEqual({ icon: 'mdi:currency-usd', text: '1,235' });
    expect(spendButtonText(0.4, 'USD', 'en').text).toBe('0');
  });

  it.each([
    ['EUR', 'mdi:currency-eur'],
    ['GBP', 'mdi:currency-gbp'],
    ['JPY', 'mdi:currency-jpy'],
    ['INR', 'mdi:currency-inr'],
    ['AUD', 'mdi:currency-usd'],
  ])('%s has the icon %s', (currency, icon) => {
    expect(spendButtonText(42, currency, 'en')).toEqual({ icon, text: '42' });
  });

  it('formats the number in the language of Home Assistant', () => {
    expect(spendButtonText(1234, 'EUR', 'de').text).toBe('1.234');
  });

  it('keeps the symbol of a currency with no icon', () => {
    const out = spendButtonText(500, 'SEK', 'en');
    expect(out.icon).toBe(SPEND_ICON);
    expect(SPEND_ICON).toBe('mdi:cash-multiple');
    // The symbol and the number, joined as Intl formats them.
    expect(out.text).toBe(new Intl.NumberFormat('en', {
      style: 'currency', currency: 'SEK', currencyDisplay: 'narrowSymbol', maximumFractionDigits: 0,
    }).format(500));
  });

  it('shows the number with no currency or an unknown code', () => {
    expect(spendButtonText(12.6, undefined, 'en')).toEqual({ icon: SPEND_ICON, text: '13' });
    expect(spendButtonText(12.6, '', 'en')).toEqual({ icon: SPEND_ICON, text: '13' });
    expect(spendButtonText(12.6, 'NOT A CODE', 'en')).toEqual({ icon: SPEND_ICON, text: '13' });
  });

  it('falls back to a plain number for a bad language tag', () => {
    expect(spendButtonText(1234, undefined, 'not_a_tag!')).toEqual({ icon: SPEND_ICON, text: '1234' });
  });
});
