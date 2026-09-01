import * as api from './api';
import type { AssetDocument, Hass, Part } from './types';

/**
 * Shared helpers for appliance **documents** (manuals, warranties, receipts). A
 * document is one of two kinds — an external `link` (a URL the browser opens directly)
 * or an uploaded `file` (a stored blob opened via a short-lived signed URL minted on
 * demand). Both render as the same named, clickable affordance; they differ only in
 * how the openable URL is obtained.
 *
 * Every surface that lists or opens documents (the sidebar panel and the dashboard
 * card) funnels through these so the link-vs-file branch lives in exactly one place —
 * add a kind here and both surfaces follow, instead of each re-deriving it (which is
 * how uploaded files were first missed on the card). Pair this with the discriminated
 * `AssetDocument` union in `types.ts`, which makes a forgotten kind a compile error.
 *
 * **A file is opened by a native `<a href>` tap, never by a JS `window.open`.** The
 * signed URL is minted *ahead* of the click (`SignedUrlCache` below) so the anchor is
 * already href-bearing when the user taps it: the iOS companion app's WKWebView blocks
 * a `window.open` issued after an async signing round-trip, so a "sign on click" handler
 * silently does nothing there (issue #164). A native anchor also restores the affordances
 * the JS handler threw away — hover/cursor, long-press "open in new tab", middle-click,
 * and keyboard activation.
 */

/** Exhaustiveness guard: a `default:` calling this turns a new, unhandled
 *  `AssetDocument` kind into a compile error (and throws if reached at runtime). */
export function assertNever(value: never): never {
  throw new Error(`Unexpected document kind: ${JSON.stringify(value)}`);
}

/** Whether a document carries the data needed to show + open it (a link needs a URL;
 *  a file needs its stored filename). */
export function isDisplayableDocument(doc: AssetDocument): boolean {
  switch (doc.kind) {
    case 'link':
      return Boolean(doc.url);
    case 'file':
      return Boolean(doc.filename);
    default:
      return assertNever(doc);
  }
}

/** Human label for a document — its display name, else the URL/filename it points at. */
export function documentLabel(doc: AssetDocument): string {
  switch (doc.kind) {
    case 'link':
      return doc.name || doc.url || '';
    case 'file':
      return doc.name || doc.filename || '';
    default:
      return assertNever(doc);
  }
}

/** MDI icon name for a document kind. */
export function documentIcon(doc: AssetDocument): string {
  switch (doc.kind) {
    case 'link':
      return 'mdi:link-variant';
    case 'file':
      return 'mdi:file-document-outline';
    default:
      return assertNever(doc);
  }
}

/**
 * Format a byte count as a short human size ("950 B", "1.2 MB"). Empty for a size
 * there is nothing to say about — absent, zero or negative — so the caller can join
 * the parts of a subtitle without punctuating around a gap.
 */
export function formatBytes(bytes?: number): string {
  // Stryker disable next-line EqualityOperator: equivalent — `!bytes` has already
  // returned for 0, so nothing reaching this comparison can tell `<= 0` from `< 0`.
  if (!bytes || bytes <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  // Stryker disable next-line ConditionalExpression,EqualityOperator: both equivalent —
  // a byte count is a whole number, so at `i === 0` the decimal branch rounds to the
  // same integer the whole-unit branch does; and at exactly 10 units, `Math.round(10)`
  // and `Math.round(100) / 10` are both 10, so `>= 10` and `> 10` render alike.
  const rounded = i === 0 || value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded} ${units[i]}`;
}

/** A short type badge from a MIME type ("application/pdf" → "PDF", "image/jpeg" → "JPEG"). */
export function documentTypeLabel(contentType?: string): string {
  if (!contentType) return '';
  const subtype = contentType.split('/')[1] || '';
  return subtype.split(';')[0].trim().toUpperCase();
}

// ── pre-signed file URLs ─────────────────────────────────────────────────────

/** A stored blob whose openable URL has to be signed: an uploaded asset document, or
 *  a part's single attached file. `id` is the document id / part id respectively. */
export interface SignedFileRef {
  kind: 'document' | 'part';
  assetId: string;
  id: string;
}

/** The cache key for a ref — also what a surface stamps on its anchor (`data-sign`)
 *  so the href can be filled in later without re-deriving which file it points at. */
export function signedFileKey(ref: SignedFileRef): string {
  return `${ref.kind}:${ref.assetId}:${ref.id}`;
}

/** Re-sign comfortably before the backend's 1h TTL (`_DOCUMENT_URL_TTL`) so an idle
 *  page's hrefs stay valid, while a fresh entry is reused across renders. Exported so a
 *  surface that isn't re-rendered by anything else can wake up and refresh on the same
 *  clock — an href that outlives the TTL is a 403 waiting to happen. */
export const SIGNED_URL_REFRESH_MS = 45 * 60 * 1000;
const RESIGN_AFTER_MS = SIGNED_URL_REFRESH_MS;

/**
 * Short-lived signed URLs for file documents / part files, minted *ahead of the click*
 * so every file renders as a plain `<a href>` (see the module header — a `window.open`
 * after the async sign is blocked in the iOS app's WKWebView).
 *
 * Shared by the panel and the dashboard card so the caching rules live in one place:
 * an entry is reused until it goes stale, entries for files the surface no longer shows
 * are dropped, and a failed sign keeps whatever URL was there before.
 */
export class SignedUrlCache {
  private _entries = new Map<string, { url: string; signedAt: number }>();
  // Signs currently in flight, keyed the same way. A surface can call `ensure` again
  // before an earlier call has resolved (the panel signs after *every* render), and
  // without this each overlapping call would mint its own URL for the same file.
  private _pending = new Map<string, Promise<void>>();

  /** The cached URL for a key, or undefined if it hasn't been signed yet. */
  getByKey(key: string): string | undefined {
    return this._entries.get(key)?.url;
  }

  /** The cached URL for a ref, or undefined if it hasn't been signed yet. */
  get(ref: SignedFileRef): string | undefined {
    return this.getByKey(signedFileKey(ref));
  }

  /**
   * Make sure every ref in *refs* has a fresh signed URL, dropping entries for
   * anything no longer referenced (so a long-lived panel/card doesn't accumulate
   * URLs for files it stopped showing). Call it with the complete set the surface
   * currently renders — a partial set evicts the rest.
   *
   * Overlapping calls share one round-trip per file: a key already being signed is
   * awaited rather than signed again.
   *
   * Resolves to true when at least one URL was (re-)minted, so a caller that renders
   * hrefs inline can decide whether a re-render is worth it. Best-effort: a failed
   * sign leaves that file unsigned (its anchor keeps the JS fallback) and is retried
   * on the next call.
   */
  async ensure(hass: Hass, refs: SignedFileRef[]): Promise<boolean> {
    const now = Date.now();
    const needed = new Map<string, SignedFileRef>();
    for (const ref of refs) needed.set(signedFileKey(ref), ref);
    for (const key of [...this._entries.keys()]) {
      if (!needed.has(key)) this._entries.delete(key);
    }
    let signed = false;
    await Promise.all(
      [...needed].map(async ([key, ref]) => {
        const cached = this._entries.get(key);
        if (cached && now - cached.signedAt < RESIGN_AFTER_MS) return;
        // Join an in-flight sign for this file instead of starting a second one.
        const inFlight = this._pending.get(key);
        if (inFlight) return inFlight;
        const sign = (async (): Promise<void> => {
          try {
            const url =
              ref.kind === 'document'
                ? await api.signDocumentUrl(hass, ref.assetId, ref.id)
                : await api.signPartFileUrl(hass, ref.assetId, ref.id);
            this._entries.set(key, { url, signedAt: Date.now() });
            signed = true;
          } catch {
            // Keep any prior URL; a failed sign just won't refresh it this round.
          } finally {
            this._pending.delete(key);
          }
        })();
        this._pending.set(key, sign);
        return sign;
      }),
    );
    return signed;
  }
}

/** Every file on an appliance that needs a signed URL — its uploaded documents plus
 *  any part with an attached file. The single place a surface derives "what to sign"
 *  for an appliance, so the panel's detail page and its edit form agree. */
export function assetFileRefs(asset: {
  id?: string;
  documents?: AssetDocument[];
  parts?: Part[];
}): SignedFileRef[] {
  const assetId = asset.id;
  if (!assetId) return [];
  const refs: SignedFileRef[] = [];
  for (const doc of asset.documents || []) {
    if (doc.kind === 'file' && doc.id) refs.push({ kind: 'document', assetId, id: doc.id });
  }
  for (const part of asset.parts || []) {
    if (part.file_name && part.id) refs.push({ kind: 'part', assetId, id: part.id });
  }
  return refs;
}

/**
 * Open a document in a new tab: a link goes straight to its URL; a file is signed
 * on demand (`home_keeper/sign_document_url`) so the short-lived URL is always fresh.
 * Best-effort — a missing asset/document (or a blocked popup) is simply a no-op.
 *
 * **Fallback only.** Every surface renders a pre-signed anchor (see `SignedUrlCache`);
 * this covers the brief window before the first sign resolves, and the case where
 * signing failed outright. On iOS the `window.open` may well be swallowed — which is
 * exactly why it isn't the primary path.
 */
export async function openDocument(
  hass: Hass,
  assetId: string,
  doc: AssetDocument,
): Promise<void> {
  try {
    let url: string | undefined;
    switch (doc.kind) {
      case 'link':
        url = doc.url;
        break;
      case 'file':
        url = doc.id ? await api.signDocumentUrl(hass, assetId, doc.id) : undefined;
        break;
      default:
        return assertNever(doc);
    }
    if (url) window.open(url, '_blank', 'noopener');
  } catch {
    // A deleted asset/document (or popup block) just doesn't open. A deleted file
    // *blob* still signs fine and 404s only when the new tab loads.
  }
}

/**
 * Open a part's attached file in a new tab — always the "file" branch (a part has no
 * link kind; that's the part's own `url` field), signed on demand
 * (`home_keeper/sign_part_file_url`). Best-effort, and a fallback only, same as
 * `openDocument`.
 */
export async function openPartFile(hass: Hass, assetId: string, part: Part): Promise<void> {
  try {
    if (!part.id) return;
    const url = await api.signPartFileUrl(hass, assetId, part.id);
    if (url) window.open(url, '_blank', 'noopener');
  } catch {
    // A deleted asset/part/file (or popup block) just doesn't open.
  }
}
