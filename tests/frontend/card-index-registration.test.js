import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// The card now loads as a Lovelace module resource (registered by card.py), so it
// is imported after HA boots and a plain guarded define is sufficient. This guard
// test fails loudly if anyone reintroduces the old add_extra_js_url timing hacks
// (registry-swap detection, loadCardHelpers polling, setInterval/setTimeout).
const SRC = readFileSync(
  resolve(
    process.cwd(),
    'custom_components/home_keeper/frontend/src/card-index.ts',
  ),
  'utf8',
);

describe('card-index.ts registration', () => {
  it('registers both custom elements with a guarded define', () => {
    expect(SRC).toContain("customElements.define('home-keeper-card', HomeKeeperCard)");
    expect(SRC).toContain(
      "customElements.define('home-keeper-card-editor', HomeKeeperCardEditor)",
    );
  });

  it('contains no registry-swap / readiness timing primitives', () => {
    expect(SRC).not.toMatch(/setInterval/);
    expect(SRC).not.toMatch(/setTimeout/);
    expect(SRC).not.toMatch(/addEventListener\(\s*['"]load['"]/);
    expect(SRC).not.toMatch(/loadCardHelpers/);
    expect(SRC).not.toMatch(/customElements\s*!==/);
  });

  it('still advertises the card in the picker via customCards', () => {
    expect(SRC).toContain('customCards');
    expect(SRC).toContain('ll-custom-cards-update');
  });
});
