import { readFileSync, readdirSync } from 'fs';
import { join } from 'path';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { HomeKeeperCard } from '../src/card.ts';

/**
 * `ha-button` reads only `appearance`, `variant` and `size`. `raised` is a Material
 * attribute that it never reads, so a button with it looks like any other. Each button
 * gets its weight from `setBtnWeight` or `btnAttrs`.
 */

const SRC = join(__dirname, '..', 'src');

describe('button weights in the source', () => {
  it('sets no raised or destructive attribute on a button', () => {
    for (const file of readdirSync(SRC).filter((f) => f.endsWith('.ts'))) {
      const text = readFileSync(join(SRC, file), 'utf8');
      expect(text, file).not.toMatch(/setAttribute\(\s*['"](raised|destructive)['"]/);
      expect(text, file).not.toMatch(/<ha-button[^>]*\s(raised|destructive)[\s>=]/);
    }
  });
});

describe('the card form buttons', () => {
  beforeAll(() => {
    for (const tag of ['ha-card', 'ha-form', 'ha-button', 'ha-icon-button', 'ha-assist-chip', 'ha-alert', 'ha-spinner', 'ha-icon']) {
      if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
    }
    if (!customElements.get('home-keeper-card')) customElements.define('home-keeper-card', HomeKeeperCard);
  });
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('draws Create as the primary button and Cancel as tertiary', async () => {
    const card = document.createElement('home-keeper-card');
    card.setConfig({ type: 'custom:home-keeper-card' });
    document.body.appendChild(card);
    card.hass = { language: 'en', callWS: async () => ({ tasks: [] }) };
    const end = Date.now() + 2000;
    while (!card.shadowRoot?.querySelector('#hk-add') && Date.now() < end) {
      await new Promise((r) => setTimeout(r, 20));
    }
    card.shadowRoot.querySelector('#hk-add').click();
    const create = card.shadowRoot.querySelector('#hk-create');
    const cancel = [...card.shadowRoot.querySelectorAll('.hk-form-actions ha-button')].find(
      (b) => b !== create,
    );
    expect(create.getAttribute('data-hk-weight')).toBe('primary');
    expect(create.hasAttribute('raised')).toBe(false);
    expect(cancel.getAttribute('data-hk-weight')).toBe('tertiary');
    expect(cancel.getAttribute('appearance')).toBe('plain');
  });
});
