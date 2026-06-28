import * as api from './api';
import type { AssetDocument, Hass } from './types';

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
 * Open a document in a new tab: a link goes straight to its URL; a file is signed
 * on demand (`home_keeper/sign_document_url`) so the short-lived URL is always fresh.
 * Best-effort — a missing asset/document (or a blocked popup) is simply a no-op.
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
