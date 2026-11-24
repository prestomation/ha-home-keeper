import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { HomeKeeperCard } from '../src/card.ts';

/**
 * An open form or dialog must scroll inside the card (#605). jsdom has no layout, so this
 * pins the rules that give the layout. The e2e spec `card-scroll.spec.ts` proves the
 * scroll in a real browser, by wheel and by touch.
 */

beforeAll(() => {
  for (const tag of [
    'ha-card',
    'ha-form',
    'ha-button',
    'ha-icon-button',
    'ha-assist-chip',
    'ha-alert',
    'ha-spinner',
    'ha-icon',
    'ha-dialog',
  ]) {
    if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
  }
  if (!customElements.get('home-keeper-card')) {
    customElements.define('home-keeper-card', HomeKeeperCard);
  }
});

afterEach(() => {
  document.body.innerHTML = '';
});

function mount(config) {
  const card = document.createElement('home-keeper-card');
  card.setConfig({ type: 'custom:home-keeper-card', ...config });
  document.body.appendChild(card);
  card.hass = {
    language: 'en',
    callWS: async (msg) => (msg.type === 'home_keeper/get_tasks' ? { tasks: [] } : {}),
  };
  return card;
}

/** The declaration block of the first rule for `selector` in the card's style. */
function rule(card, selector) {
  const css = card.shadowRoot.querySelector('style').textContent;
  const start = css.indexOf(`${selector} {`);
  expect(start, `no rule for ${selector}`).toBeGreaterThan(-1);
  return css.slice(start, css.indexOf('}', start));
}

describe('card form scroll', () => {
  for (const show_add of [true, false]) {
    it(`the form host shrinks to the card and scrolls, show_add ${show_add}`, async () => {
      const card = mount({ show_add });
      await new Promise((r) => setTimeout(r, 20));
      const host = rule(card, '#hk-form-host');
      expect(host).toContain('min-height: 0');
      expect(host).toContain('overflow-y: auto');
      expect(host).toContain('flex: 0 1 auto');
    });
  }

  it('keeps the list as the 1 flexible area that scrolls', async () => {
    const card = mount({ show_add: true });
    await new Promise((r) => setTimeout(r, 20));
    const body = rule(card, '.hk-body');
    expect(body).toContain('flex: 1');
    expect(body).toContain('min-height: 0');
    expect(body).toContain('overflow: auto');
  });

  it('puts the form host between the header and the list in the card', async () => {
    const card = mount({ show_add: true });
    await new Promise((r) => setTimeout(r, 20));
    const kids = Array.from(card.shadowRoot.querySelector('ha-card').children).map(
      (el) => el.id || el.className,
    );
    expect(kids).toEqual(['hk-head', 'hk-form-host', 'hk-body']);
  });
});
