/**
 * Markdown rendering for user-authored free text (task/appliance/part notes and
 * per-completion notes).
 *
 * We deliberately render through Home Assistant's own `<ha-markdown>` rather than
 * bundling a parser. `ha-markdown` wraps `ha-markdown-element`, which parses with
 * `marked` (GFM) and sanitizes with DOMPurify **inside a Web Worker**, rewrites
 * off-host anchors to `target="_blank" rel="noreferrer noopener"`, and ships
 * theme-aware styles for links/code/`pre`/headings. Re-implementing that would mean
 * maintaining sanitizer-adjacent code — exactly the class of thing that grows CVEs —
 * and bundling `marked`+DOMPurify would add ~70 KB and two supply-chain deps to a
 * frontend that currently ships none.
 *
 * The catch is that `ha-markdown` is **lazily loaded**: it is absent from HA's eager
 * entrypoints (`app`/`core`/`custom-panel`) and only registers when a chunk that
 * imports it loads. One such chunk also carries `hui-markdown-card`, so asking the
 * card helpers to build a markdown card is a reliable one-hop nudge to register it —
 * see `ensureMarkdown`. When even that is unavailable (a cold deep-link straight to
 * `/home-keeper`, where the Lovelace chunk that installs `window.loadCardHelpers` has
 * never loaded), we fall back to escaped text with `white-space: pre-wrap`, which is
 * still an improvement on the previous rendering.
 */

import { escapeHTML } from './utils';

/** The `content` property `ha-markdown` renders (set as a property, not an attribute). */
interface HaMarkdownElement extends HTMLElement {
  content?: string;
}

/** HA installs this on `window` from the Lovelace panel chunk. */
interface CardHelpers {
  createCardElement?: (config: { type: string; [key: string]: unknown }) => unknown;
}

/** In-flight registration attempt, so concurrent callers share one. Cleared when settled. */
let pending: Promise<boolean> | undefined;

/** True once `ha-markdown` is registered — checked synchronously on every render. */
export function markdownReady(): boolean {
  return Boolean(customElements.get('ha-markdown'));
}

/**
 * Best-effort registration of `<ha-markdown>`.
 *
 * Concurrent callers share one in-flight attempt; nothing is cached once it settles.
 * That matters for the negative case: `window.loadCardHelpers` only exists after HA's
 * Lovelace chunk has loaded, so a panel opened by cold deep-link can start without it
 * and gain it later (the user visits a dashboard, comes back). Re-attempting on a
 * later render lets the panel upgrade from the plain fallback to rendered Markdown.
 * Once the element *is* registered, `markdownReady()` short-circuits every call.
 */
export async function ensureMarkdown(timeoutMs = 4000): Promise<boolean> {
  if (markdownReady()) return true;
  if (pending) return pending;
  pending = (async (): Promise<boolean> => {
    try {
      const load = (window as { loadCardHelpers?: () => Promise<CardHelpers> })
        .loadCardHelpers;
      if (!load) return false;
      const helpers = await load();
      // Building a markdown card pulls in the chunk that also defines `ha-markdown`.
      // The element itself is discarded — we only want the side effect of the import.
      helpers?.createCardElement?.({ type: 'markdown', content: '' });
      await Promise.race([
        customElements.whenDefined('ha-markdown'),
        new Promise((resolve) => setTimeout(resolve, timeoutMs)),
      ]);
      return markdownReady();
    } catch {
      return false;
    }
  })();
  try {
    return await pending;
  } finally {
    pending = undefined;
  }
}

/**
 * An HTML string that renders *text* as Markdown, for embedding in an `innerHTML`
 * template. The text is carried in `data-md` (escaped) and moved onto the element's
 * `content` property by `wireMarkdown` after insertion — `content` is a property, so
 * it cannot be set through the markup alone.
 *
 * Returns `''` for empty text so callers can use it directly in a conditional.
 */
export function markdownBlock(text: unknown, extraClass = ''): string {
  const value = String(text ?? '');
  if (!value) return '';
  const cls = `hk-md${extraClass ? ` ${extraClass}` : ''}`;
  if (!markdownReady()) {
    // Fallback: escaped text, with `pre-wrap` (see the stylesheet) so at least the
    // author's own line breaks and indentation survive.
    return `<div class="${cls} hk-md-plain">${escapeHTML(value)}</div>`;
  }
  return `<ha-markdown class="${cls}" data-md="${escapeHTML(value)}"></ha-markdown>`;
}

/** Move `data-md` onto each `ha-markdown`'s `content` property. Run after every render. */
export function wireMarkdown(root: ParentNode | null | undefined): void {
  root?.querySelectorAll<HaMarkdownElement>('ha-markdown[data-md]').forEach((el) => {
    el.content = el.dataset.md ?? '';
  });
}

/**
 * Markup patterns that make a preview worth showing: emphasis, inline code or a fence,
 * an ATX heading, a bullet/ordered list item, a blockquote, a link/image, a table row,
 * or a thematic break. Deliberately conservative — plain prose renders identically to
 * what the user already typed, so previewing it is just noise in the form.
 */
const MARKDOWN_HINT =
  /(\*\*?[^*\s][^*]*\*)|(__?[^_\s][^_]*_)|(`)|(^\s{0,3}#{1,6}\s)|(^\s*([-*+]|\d+\.)\s)|(^\s*>\s?)|(\[[^\]]*\]\([^)]*\))|(^\s*\|.*\|)|(^\s{0,3}(-{3,}|\*{3,}|_{3,})\s*$)/m;

/** True when *text* contains Markdown worth previewing (see `MARKDOWN_HINT`). */
export function looksLikeMarkdown(text: unknown): boolean {
  return MARKDOWN_HINT.test(String(text ?? ''));
}

/** A live preview attached to a notes editor, updated as the user types. */
export interface MarkdownPreview {
  /** The block to append next to the textarea/field. */
  el: HTMLElement;
  /** Re-render with *text* (debounced). Hides the block entirely when text is empty. */
  update: (text: string) => void;
  /** Cancel a pending debounced update (call when tearing the editor down). */
  dispose: () => void;
}

/**
 * Build a live Markdown preview for an authoring surface.
 *
 * Updates are **debounced**: every render round-trips through `ha-markdown`'s Web
 * Worker, so firing per keystroke would queue needless work. The caller passes its own
 * localized *caption* so this module stays i18n-free and usable from both bundles.
 *
 * The block stays hidden until the text actually contains Markdown — a preview that
 * echoes plain prose back at the author tells them nothing and just crowds the form.
 */
export function createPreview(caption: string, debounceMs = 200): MarkdownPreview {
  const el = document.createElement('div');
  el.className = 'hk-md-preview';
  el.style.display = 'none';

  const label = document.createElement('div');
  label.className = 'hk-md-preview-caption';
  label.textContent = caption;
  el.appendChild(label);

  const body = document.createElement('div');
  body.className = 'hk-md-preview-body';
  el.appendChild(body);

  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;

  const paint = (text: string): void => {
    if (!text) {
      el.style.display = 'none';
      body.innerHTML = '';
      return;
    }
    el.style.display = '';
    body.innerHTML = markdownBlock(text);
    wireMarkdown(body);
  };

  return {
    el,
    update(text: string): void {
      // Disposal is permanent: once the owner has torn this preview down, a stale
      // reference (an event handler still bound to a detached form, say) must not be
      // able to arm a fresh timer against DOM nobody will clean up again.
      if (disposed) return;
      if (timer) clearTimeout(timer);
      const value = String(text ?? '');
      // Collapse immediately when there's nothing to preview — waiting out the
      // debounce to hide the block reads as lag.
      if (!looksLikeMarkdown(value)) {
        paint('');
        return;
      }
      timer = setTimeout(() => paint(value), debounceMs);
    },
    /** Cancel any pending render and permanently deactivate this preview. Idempotent. */
    dispose(): void {
      disposed = true;
      if (timer) clearTimeout(timer);
      timer = undefined;
    },
  };
}
