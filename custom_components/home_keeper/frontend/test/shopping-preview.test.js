import { afterEach, describe, expect, it } from 'vitest';
import { setLanguage } from '../src/i18n';
import {
  SET_DESCRIPTION_ON_ITEM,
  lineFor,
  normalizeLineStyle,
  previewLines,
  restockLabel,
  supportsDescription,
} from '../src/shopping-preview.ts';

// The panel's copy of shopping.buy_tasks_by_part / shopping.line_for. These cases
// mirror tests/unit/test_shopping.py, so the preview reads as the list will.

const buyTask = (over = {}) => ({
  id: 't1',
  name: 'Buy Anode rod',
  recurrence_type: 'one-off',
  next_due: '2026-06-13T10:00:00-04:00',
  last_completed: null,
  source: { buy: { asset_id: 'a1', part_id: 'p1' } },
  ...over,
});

const assets = (part = {}) => [
  {
    id: 'a1',
    name: 'Water heater',
    parts: [{ id: 'p1', name: 'Anode rod', type: 'consumable', ...part }],
  },
];

afterEach(() => setLanguage('en'));

describe('supportsDescription', () => {
  it('reads the SET_DESCRIPTION_ON_ITEM bit', () => {
    expect(SET_DESCRIPTION_ON_ITEM).toBe(64);
    expect(supportsDescription(64)).toBe(true);
    expect(supportsDescription(15 | 64)).toBe(true);
    expect(supportsDescription(15)).toBe(false);
    expect(supportsDescription(undefined)).toBe(false);
    expect(supportsDescription('79')).toBe(true);
  });
});

describe('normalizeLineStyle', () => {
  it('keeps product_only and reads anything else as with_verb', () => {
    expect(normalizeLineStyle('product_only')).toBe('product_only');
    expect(normalizeLineStyle('with_verb')).toBe('with_verb');
    expect(normalizeLineStyle(undefined)).toBe('with_verb');
    expect(normalizeLineStyle('verb')).toBe('with_verb');
  });
});

describe('restockLabel', () => {
  it('reads a measured part with its unit', () => {
    expect(restockLabel({ stock_unit: 'ml', restock_quantity: 500 }, 'en')).toBe('500 ml');
    expect(restockLabel({ stock_unit: ' ml ', restock_quantity: 500 }, 'en')).toBe('500 ml');
  });

  it('reads several spares as a multiplier', () => {
    expect(restockLabel({ restock_quantity: 3 }, 'en')).toBe('×3');
    expect(restockLabel({ restock_quantity: 2.5 }, 'de')).toBe('×2,5');
  });

  it('reads one plain spare as nothing', () => {
    expect(restockLabel({ restock_quantity: 1 }, 'en')).toBe('');
    expect(restockLabel({}, 'en')).toBe('');
  });

  it('treats a missing or unusable quantity as one spare', () => {
    expect(restockLabel({ stock_unit: 'kg' }, 'en')).toBe('1 kg');
    expect(restockLabel({ stock_unit: 'kg', restock_quantity: 0 }, 'en')).toBe('1 kg');
    expect(restockLabel({ stock_unit: 'kg', restock_quantity: -2 }, 'en')).toBe('1 kg');
    expect(restockLabel({ stock_unit: 'kg', restock_quantity: null }, 'en')).toBe('1 kg');
  });
});

describe('lineFor', () => {
  it('puts the amount in the description when the list can hold one', () => {
    expect(lineFor('Anode rod', '500 ml', true)).toEqual({
      title: 'Anode rod',
      description: '500 ml',
    });
  });

  it('suffixes the amount otherwise', () => {
    expect(lineFor('Anode rod', '500 ml', false)).toEqual({
      title: 'Anode rod (500 ml)',
      description: '',
    });
    expect(lineFor('Anode rod', '', false)).toEqual({ title: 'Anode rod', description: '' });
  });
});

describe('previewLines', () => {
  it('shows an open reminder with its verb by default', () => {
    const lines = previewLines([buyTask()], assets({ restock_quantity: 2 }), 'with_verb', false, 'en');
    expect(lines).toEqual([{ title: 'Buy Anode rod (×2)', description: '' }]);
  });

  it('shows only the part name with product_only', () => {
    const lines = previewLines(
      [buyTask({ name: 'Anodenstab kaufen' })],
      assets({ name: '  Anode rod  ', stock_unit: 'ml', restock_quantity: 500 }),
      'product_only',
      true,
      'en',
    );
    expect(lines).toEqual([{ title: 'Anode rod', description: '500 ml' }]);
  });

  it('falls back to the reminder name when the part is gone or unnamed', () => {
    expect(previewLines([buyTask()], [], 'product_only', false, 'en')).toEqual([
      { title: 'Buy Anode rod', description: '' },
    ]);
    expect(previewLines([buyTask()], assets({ name: ' ' }), 'product_only', false, 'en')).toEqual([
      { title: 'Buy Anode rod', description: '' },
    ]);
  });

  it('leaves out other tasks, completed reminders and nameless ones', () => {
    const tasks = [
      { id: 'x', name: 'Vacuum', recurrence_type: 'interval', next_due: null },
      buyTask({ id: 'done', next_due: null, last_completed: '2026-06-14T09:00:00Z' }),
      buyTask({ id: 'blank', name: '  ' }),
    ];
    const lines = previewLines(tasks, assets(), 'with_verb', false, 'en');
    // Nothing real to show, so the example stands in.
    expect(lines.map((l) => l.title)).toEqual(['Buy Water filter (×2)', 'Buy Dishwasher salt (1.5 kg)']);
  });

  it('keeps a completed-looking task that is still due', () => {
    const task = buyTask({ last_completed: '2026-06-14T09:00:00Z' });
    expect(previewLines([task], assets(), 'with_verb', false, 'en')).toEqual([
      { title: 'Buy Anode rod', description: '' },
    ]);
  });

  it('sorts the lines by title', () => {
    const tasks = [
      buyTask({ id: 'b', name: 'Buy Zinc' }),
      buyTask({ id: 'a', name: 'Buy Anode rod' }),
    ];
    expect(previewLines(tasks, [], 'with_verb', false, 'en').map((l) => l.title)).toEqual([
      'Buy Anode rod',
      'Buy Zinc',
    ]);
  });

  it('builds the example in the panel language and the chosen style', () => {
    setLanguage('de');
    expect(previewLines([], [], 'with_verb', true, 'de')).toEqual([
      { title: 'Wasserfilter kaufen', description: '×2' },
      { title: 'Spülmaschinensalz kaufen', description: '1,5 kg' },
    ]);
    expect(previewLines([], [], 'product_only', false, 'de')).toEqual([
      { title: 'Wasserfilter (×2)', description: '' },
      { title: 'Spülmaschinensalz (1,5 kg)', description: '' },
    ]);
  });
});
