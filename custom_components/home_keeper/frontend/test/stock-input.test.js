import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { typedStock } from '../src/utils.ts';
import { definePanelStubs, mountPanel, waitFor } from './panel-harness.js';

/**
 * F07-3: an emptied stock box must not set the stock to 0.
 *
 * `Number('')` is 0, so a user who deleted the old count to type a new one and then
 * tapped away sent an adjust of -stock. That fires the out-of-stock event and can
 * make a buy task nobody asked for.
 */
describe('typedStock', () => {
  it('F07-3: reads no number from an empty or blank box', () => {
    expect(typedStock({ value: '' })).toBeNull();
    expect(typedStock({ value: '   ' })).toBeNull();
  });

  it('F07-3: reads no number when the browser flags bad input', () => {
    expect(typedStock({ value: '', validity: { badInput: true } })).toBeNull();
    expect(typedStock({ value: '5', validity: { badInput: true } })).toBeNull();
  });

  it('F07-3: reads no number from text that is not finite', () => {
    expect(typedStock({ value: 'abc' })).toBeNull();
    expect(typedStock({ value: 'Infinity' })).toBeNull();
  });

  it('reads a typed number, zero included', () => {
    expect(typedStock({ value: '7' })).toBe(7);
    expect(typedStock({ value: ' 2.5 ', validity: { badInput: false } })).toBe(2.5);
    expect(typedStock({ value: '0' })).toBe(0);
  });
});

describe('F07-3: the stock stepper on the appliance page', () => {
  beforeAll(() => {
    definePanelStubs();
  });

  afterEach(() => {
    document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
  });

  const ASSET = {
    id: 'a1',
    kind: 'virtual',
    name: 'Furnace',
    parts: [{ id: 'p1', name: 'Filter', type: 'consumable', stock: 12, reorder_at: 2 }],
  };

  function hassWithAsset() {
    const adjusts = [];
    const hass = {
      language: 'en',
      states: {},
      devices: {},
      callWS(msg) {
        switch (msg.type) {
          case 'home_keeper/get_tasks':
            return Promise.resolve({ tasks: [] });
          case 'home_keeper/get_assets':
            return Promise.resolve({ assets: [ASSET] });
          case 'home_keeper/get_options':
            return Promise.resolve({ options: {} });
          case 'frontend/get_user_data':
            return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
          case 'home_keeper/adjust_part_stock':
            adjusts.push(msg);
            return Promise.resolve({ asset: ASSET });
          default:
            return Promise.resolve({});
        }
      },
    };
    return { hass, adjusts };
  }

  it('puts the stored count back when the box is emptied, and sends nothing', async () => {
    const { hass, adjusts } = hassWithAsset();
    const { panel } = await mountPanel('/appliances/a1', hass);
    const input = await waitFor(() => panel.shadowRoot.querySelector('.hk-stock-input'));
    input.value = '';
    input.dispatchEvent(new Event('change'));
    await new Promise((r) => setTimeout(r, 30));
    expect(adjusts).toEqual([]);
    expect(input.value).toBe('12');
  });

  it('still saves a typed number', async () => {
    const { hass, adjusts } = hassWithAsset();
    const { panel } = await mountPanel('/appliances/a1', hass);
    const input = await waitFor(() => panel.shadowRoot.querySelector('.hk-stock-input'));
    input.value = '9';
    input.dispatchEvent(new Event('change'));
    await waitFor(() => adjusts.length);
    expect(adjusts[0].delta).toBe(-3);
  });
});
