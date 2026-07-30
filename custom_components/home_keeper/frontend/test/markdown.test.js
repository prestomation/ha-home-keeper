import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createPreview,
  ensureMarkdown,
  looksLikeMarkdown,
  markdownBlock,
  markdownReady,
  wireMarkdown,
} from '../src/markdown.ts';

// `customElements` registrations are permanent within a jsdom realm, so the two
// halves of this suite would otherwise contaminate each other. Every test that needs
// `ha-markdown` *absent* stubs `customElements` with a registry that reports it
// missing; the ones that need it present stub the opposite. That keeps each case
// explicit about which branch of `markdownBlock` it is exercising.
const REAL_CE = globalThis.customElements;

/** Stub `customElements` so `ha-markdown` looks registered (or not). */
function stubRegistry({ hasMarkdown = false, defineLater = false } = {}) {
  let defined = hasMarkdown;
  let resolveWhenDefined;
  const whenDefined = new Promise((r) => {
    resolveWhenDefined = r;
  });
  const registry = {
    get: (name) => (name === 'ha-markdown' && defined ? class {} : REAL_CE.get(name)),
    whenDefined: (name) => (name === 'ha-markdown' ? whenDefined : REAL_CE.whenDefined(name)),
    define: (...args) => REAL_CE.define(...args),
    /** Simulate HA's lazy chunk landing and registering the element. */
    register: () => {
      defined = true;
      resolveWhenDefined();
    },
  };
  if (defineLater) registry.definesLater = true;
  vi.stubGlobal('customElements', registry);
  return registry;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('markdownReady', () => {
  it('is false when HA has not registered ha-markdown', () => {
    stubRegistry({ hasMarkdown: false });
    expect(markdownReady()).toBe(false);
  });

  it('is true once ha-markdown is registered', () => {
    stubRegistry({ hasMarkdown: true });
    expect(markdownReady()).toBe(true);
  });
});

describe('markdownBlock', () => {
  it('renders nothing for empty/absent text so callers can inline it', () => {
    stubRegistry({ hasMarkdown: true });
    expect(markdownBlock('')).toBe('');
    expect(markdownBlock(null)).toBe('');
    expect(markdownBlock(undefined)).toBe('');
  });

  describe('with ha-markdown registered', () => {
    beforeEach(() => stubRegistry({ hasMarkdown: true }));

    it('emits an ha-markdown carrying the source in data-md', () => {
      const html = markdownBlock('**bold**');
      expect(html).toContain('<ha-markdown');
      expect(html).toContain('data-md="**bold**"');
      expect(html).toContain('class="hk-md"');
    });

    it('appends the extra class', () => {
      expect(markdownBlock('hi', 'hk-md-compact')).toContain('class="hk-md hk-md-compact"');
    });

    it('escapes the source so it cannot break out of the data-md attribute', () => {
      // The raw text never reaches the DOM as markup — it round-trips through an
      // escaped attribute, and ha-markdown itself sanitizes when it renders.
      const html = markdownBlock('" onload="alert(1)" x="');
      expect(html).not.toContain('onload="alert(1)"');
      expect(html).toContain('&quot; onload=&quot;alert(1)&quot;');
    });

    it('escapes raw HTML in the source', () => {
      const html = markdownBlock('<img src=x onerror=alert(1)>');
      expect(html).not.toContain('<img');
      expect(html).toContain('&lt;img');
    });
  });

  describe('fallback when ha-markdown is unavailable', () => {
    beforeEach(() => stubRegistry({ hasMarkdown: false }));

    it('emits escaped text in a pre-wrap div instead of an ha-markdown', () => {
      const html = markdownBlock('line one\nline two');
      expect(html).not.toContain('<ha-markdown');
      expect(html).toContain('hk-md-plain');
      expect(html).toContain('line one\nline two');
    });

    it('escapes markup in the fallback path', () => {
      const html = markdownBlock('<script>alert(1)</script>');
      expect(html).not.toContain('<script>');
      expect(html).toContain('&lt;script&gt;');
    });
  });
});

describe('wireMarkdown', () => {
  it('moves data-md onto the content property', () => {
    stubRegistry({ hasMarkdown: true });
    const host = document.createElement('div');
    host.innerHTML = markdownBlock('# heading');
    const el = host.querySelector('ha-markdown');
    expect(el.content).toBeUndefined();
    wireMarkdown(host);
    expect(el.content).toBe('# heading');
  });

  it('tolerates a null root and a subtree with no markdown', () => {
    stubRegistry({ hasMarkdown: true });
    expect(() => wireMarkdown(null)).not.toThrow();
    expect(() => wireMarkdown(document.createElement('div'))).not.toThrow();
  });
});

describe('ensureMarkdown', () => {
  it('short-circuits when ha-markdown is already registered', async () => {
    stubRegistry({ hasMarkdown: true });
    const load = vi.fn();
    vi.stubGlobal('loadCardHelpers', load);
    await expect(ensureMarkdown()).resolves.toBe(true);
    expect(load).not.toHaveBeenCalled();
  });

  it('registers ha-markdown by asking the card helpers for a markdown card', async () => {
    const registry = stubRegistry({ hasMarkdown: false });
    // Building a markdown card pulls in the chunk that also defines `ha-markdown`.
    const createCardElement = vi.fn(() => registry.register());
    vi.stubGlobal('loadCardHelpers', async () => ({ createCardElement }));
    await expect(ensureMarkdown()).resolves.toBe(true);
    expect(createCardElement).toHaveBeenCalledWith({ type: 'markdown', content: '' });
  });

  it('returns false when loadCardHelpers is absent (cold deep-link to the panel)', async () => {
    stubRegistry({ hasMarkdown: false });
    vi.stubGlobal('loadCardHelpers', undefined);
    await expect(ensureMarkdown()).resolves.toBe(false);
  });

  it('returns false rather than throwing when the helpers reject', async () => {
    stubRegistry({ hasMarkdown: false });
    vi.stubGlobal('loadCardHelpers', async () => {
      throw new Error('boom');
    });
    await expect(ensureMarkdown()).resolves.toBe(false);
  });

  it('gives up after the timeout when the element never registers', async () => {
    stubRegistry({ hasMarkdown: false });
    vi.stubGlobal('loadCardHelpers', async () => ({ createCardElement: () => {} }));
    await expect(ensureMarkdown(1)).resolves.toBe(false);
  });
});

describe('createPreview', () => {
  it('starts hidden and captions itself with the caller-supplied label', () => {
    stubRegistry({ hasMarkdown: true });
    const preview = createPreview('Preview');
    expect(preview.el.style.display).toBe('none');
    expect(preview.el.querySelector('.hk-md-preview-caption').textContent).toBe('Preview');
  });

  it('renders after the debounce, not on the keystroke', () => {
    vi.useFakeTimers();
    stubRegistry({ hasMarkdown: true });
    const preview = createPreview('Preview', 200);
    preview.update('**bold**');
    // Each render round-trips through ha-markdown's worker, so it must not fire
    // per keystroke.
    expect(preview.el.querySelector('ha-markdown')).toBeNull();
    vi.advanceTimersByTime(200);
    const el = preview.el.querySelector('ha-markdown');
    expect(el).not.toBeNull();
    expect(el.content).toBe('**bold**');
    expect(preview.el.style.display).toBe('');
  });

  it('coalesces rapid updates into a single render', () => {
    vi.useFakeTimers();
    stubRegistry({ hasMarkdown: true });
    const preview = createPreview('Preview', 200);
    preview.update('# a');
    vi.advanceTimersByTime(100);
    preview.update('# ab');
    vi.advanceTimersByTime(100);
    preview.update('# abc');
    vi.advanceTimersByTime(200);
    expect(preview.el.querySelector('ha-markdown').content).toBe('# abc');
  });

  it('collapses immediately when the field is emptied (no debounce lag)', () => {
    vi.useFakeTimers();
    stubRegistry({ hasMarkdown: true });
    const preview = createPreview('Preview', 200);
    preview.update('**something**');
    vi.advanceTimersByTime(200);
    expect(preview.el.style.display).toBe('');

    preview.update('');
    expect(preview.el.style.display).toBe('none');
    expect(preview.el.querySelector('ha-markdown')).toBeNull();
  });

  it('stays hidden for plain prose — a preview of it would say nothing', () => {
    vi.useFakeTimers();
    stubRegistry({ hasMarkdown: true });
    const preview = createPreview('Preview', 200);
    preview.update('Replaced cartridge; rinsed housing');
    vi.advanceTimersByTime(500);
    expect(preview.el.style.display).toBe('none');
    expect(preview.el.querySelector('ha-markdown')).toBeNull();
  });

  it('appears as soon as the prose gains markup, and hides again when it loses it', () => {
    vi.useFakeTimers();
    stubRegistry({ hasMarkdown: true });
    const preview = createPreview('Preview', 200);

    preview.update('Replaced cartridge');
    vi.advanceTimersByTime(200);
    expect(preview.el.style.display).toBe('none');

    preview.update('Replaced **cartridge**');
    vi.advanceTimersByTime(200);
    expect(preview.el.style.display).toBe('');

    preview.update('Replaced cartridge');
    expect(preview.el.style.display).toBe('none');
  });

  it('dispose is permanent — a stale reference cannot re-arm a timer', () => {
    vi.useFakeTimers();
    stubRegistry({ hasMarkdown: true });
    const preview = createPreview('Preview', 200);
    preview.dispose();

    // A handler still bound to a detached form could call update() after teardown.
    // It must be inert, or it would render against DOM nobody will clean up again.
    preview.update('**bold**');
    vi.advanceTimersByTime(500);
    expect(preview.el.querySelector('ha-markdown')).toBeNull();

    // And dispose stays safe to call again.
    expect(() => preview.dispose()).not.toThrow();
  });

  it('dispose cancels a pending render', () => {
    vi.useFakeTimers();
    stubRegistry({ hasMarkdown: true });
    const preview = createPreview('Preview', 200);
    preview.update('**bold**');
    preview.dispose();
    vi.advanceTimersByTime(500);
    expect(preview.el.querySelector('ha-markdown')).toBeNull();
  });

  it('falls back to escaped text when ha-markdown is unavailable', () => {
    vi.useFakeTimers();
    stubRegistry({ hasMarkdown: false });
    const preview = createPreview('Preview', 10);
    preview.update('`<b>x</b>`');
    vi.advanceTimersByTime(10);
    const body = preview.el.querySelector('.hk-md-preview-body');
    expect(body.querySelector('.hk-md-plain')).not.toBeNull();
    expect(body.querySelector('b')).toBeNull();
    expect(body.textContent).toBe('`<b>x</b>`');
  });
});

describe('looksLikeMarkdown', () => {
  it.each([
    ['**bold**', 'strong emphasis'],
    ['*italic*', 'emphasis'],
    ['_italic_', 'underscore emphasis'],
    ['`code`', 'inline code'],
    ['# Heading', 'ATX heading'],
    ['- item', 'bullet list'],
    ['1. item', 'ordered list'],
    ['> quote', 'blockquote'],
    ['[text](https://example.com)', 'link'],
    ['| a | b |', 'table row'],
    ['---', 'thematic break'],
    ['line one\n## Heading', 'markup on a later line'],
  ])('detects %s (%s)', (text) => {
    expect(looksLikeMarkdown(text)).toBe(true);
  });

  it.each([
    ['Replaced cartridge; rinsed housing'],
    ['20x25x1 MERV 11'],
    ['Under-sink RO filter'],
    ['2 * 3 = 6'],
    ['a plain\nmulti-line note'],
    [''],
    [null],
    [undefined],
  ])('treats %s as plain prose', (text) => {
    expect(looksLikeMarkdown(text)).toBe(false);
  });
});
