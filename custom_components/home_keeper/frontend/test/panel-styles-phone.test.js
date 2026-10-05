import { describe, expect, it } from 'vitest';
import { STYLES } from '../src/panel-styles.ts';

/**
 * Phone rules that a desktop render cannot show. A unit test reads them from the
 * stylesheet, because jsdom has no layout to measure a tap target in.
 */

/** The bodies of every `@media (max-width: 700px)` block, joined. */
function phoneRules() {
  const out = [];
  const marker = '@media (max-width: 700px)';
  let at = STYLES.indexOf(marker);
  while (at >= 0) {
    let i = STYLES.indexOf('{', at) + 1;
    const start = i;
    let depth = 1;
    while (depth > 0 && i < STYLES.length) {
      if (STYLES[i] === '{') depth++;
      else if (STYLES[i] === '}') depth--;
      i++;
    }
    out.push(STYLES.slice(start, i - 1));
    at = STYLES.indexOf(marker, i);
  }
  return out.join('\n').replace(/\/\*[\s\S]*?\*\//g, '');
}

/** The declarations of the first rule in *css* whose selector list is *selector*. */
function rule(css, selector) {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = new RegExp(`(?:^|[}\\s])${esc}\\s*\\{([^}]*)\\}`).exec(css);
  return m ? m[1] : null;
}

describe('phone layout rules', () => {
  const phone = phoneRules();

  it('X11-7: the stock stepper buttons take the tap size', () => {
    expect(rule(phone, '.hk-stock ha-icon-button')).toContain(
      '--mdc-icon-button-size: var(--hk-tap)',
    );
    expect(rule(phone, '.hk-stock')).toContain('height: var(--hk-tap)');
  });

  it('X11-7: the stock box and the note editor use 16px text', () => {
    expect(rule(phone, '.hk-stock-input, .hk-note-input')).toContain('font-size: 16px');
  });

  it('#399: the task cover goes full width above the name', () => {
    expect(rule(phone, '.hk-head-with-cover')).toContain('flex-direction: column');
    expect(rule(phone, '.hk-task-cover')).toContain('width: 100%');
  });

  it('#399: the photo strip scrolls sideways and its buttons take the tap size', () => {
    const strip = rule(phone, '.hk-photo-strip');
    expect(strip).toContain('flex-wrap: nowrap');
    expect(strip).toContain('overflow-x: auto');
    expect(rule(phone, '.hk-photo-actions ha-icon-button')).toContain(
      '--mdc-icon-button-size: var(--hk-tap)',
    );
  });

  it('X11-4: the tree toggle has a tap-size ring', () => {
    const ring = rule(phone, '.hk-chevron::before');
    expect(ring).toContain("content: ''");
    expect(ring).toContain('inset: calc((24px - var(--hk-tap)) / 2)');
  });
});
