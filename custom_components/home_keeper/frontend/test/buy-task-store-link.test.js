import { describe, expect, it } from 'vitest';
import { consumableLinkLabel } from '../src/panel-task-form.ts';

/** A buy reminder shows the store link of its part (#613). */

const PART = { id: 'P1', name: 'Filter', url: 'https://shop.example/filter', stock: 0, reorder_at: 1 };
const ASSET = { id: 'X', name: 'Fridge', parts: [PART] };
const host = (assets) => ({
  _assets: assets,
  _hass: { devices: {} },
  _hrefFor: () => '/home-keeper/appliances/X/parts/P1',
});

describe('consumableLinkLabel for a buy reminder', () => {
  const buy = { id: 'T', source: { buy: { asset_id: 'X', part_id: 'P1' } } };

  it('links the part name to its store page', () => {
    const html = consumableLinkLabel(host([ASSET]), buy);
    expect(html).toContain('href="https://shop.example/filter"');
    expect(html).toContain('>Filter</a>');
  });

  it('shows nothing when the part is gone', () => {
    expect(consumableLinkLabel(host([{ ...ASSET, parts: [] }]), buy)).toBe('');
  });
});
