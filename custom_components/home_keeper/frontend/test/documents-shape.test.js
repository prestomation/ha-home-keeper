import { describe, expect, it } from 'vitest';
import {
  assertNever,
  documentIcon,
  documentLabel,
  isDisplayableDocument,
  signedFileKey,
} from '../src/documents.ts';

// The link-vs-file branch lives in exactly one place (see the module header) so
// the panel and the card can't drift. `documents.test.js` covers SignedUrlCache;
// these are the small discriminated-union helpers around it, which nothing
// exercised — and which decide whether a manual shows up at all.

describe('isDisplayableDocument', () => {
  it('needs a URL for a link and a filename for a file', () => {
    expect(isDisplayableDocument({ kind: 'link', url: 'https://example.com' })).toBe(true);
    expect(isDisplayableDocument({ kind: 'file', filename: 'manual.pdf' })).toBe(true);
  });

  it('rejects a document missing the field its kind needs', () => {
    // The two kinds key off *different* fields; a link with only a filename (or
    // vice versa) is data that would render an un-openable affordance.
    expect(isDisplayableDocument({ kind: 'link' })).toBe(false);
    expect(isDisplayableDocument({ kind: 'link', url: '' })).toBe(false);
    expect(isDisplayableDocument({ kind: 'link', filename: 'manual.pdf' })).toBe(false);
    expect(isDisplayableDocument({ kind: 'file' })).toBe(false);
    expect(isDisplayableDocument({ kind: 'file', filename: '' })).toBe(false);
    expect(isDisplayableDocument({ kind: 'file', url: 'https://example.com' })).toBe(false);
  });
});

describe('documentLabel', () => {
  it('prefers the display name', () => {
    expect(documentLabel({ kind: 'link', name: 'Manual', url: 'https://x/y' })).toBe('Manual');
    expect(documentLabel({ kind: 'file', name: 'Manual', filename: 'm.pdf' })).toBe('Manual');
  });

  it('falls back to what the document points at', () => {
    expect(documentLabel({ kind: 'link', url: 'https://x/y' })).toBe('https://x/y');
    expect(documentLabel({ kind: 'file', filename: 'm.pdf' })).toBe('m.pdf');
    // An empty name is a fallback trigger, not a label.
    expect(documentLabel({ kind: 'link', name: '', url: 'https://x/y' })).toBe('https://x/y');
  });

  it('is an empty string, never undefined, when there is nothing to show', () => {
    // The label goes straight into the DOM; "undefined" would render literally.
    expect(documentLabel({ kind: 'link' })).toBe('');
    expect(documentLabel({ kind: 'file' })).toBe('');
  });

  it('does not use the other kind field as a fallback', () => {
    expect(documentLabel({ kind: 'link', filename: 'm.pdf' })).toBe('');
    expect(documentLabel({ kind: 'file', url: 'https://x/y' })).toBe('');
  });
});

describe('documentIcon', () => {
  it('gives each kind its own icon', () => {
    expect(documentIcon({ kind: 'link', url: 'https://x/y' })).toBe('mdi:link-variant');
    expect(documentIcon({ kind: 'file', filename: 'm.pdf' })).toBe('mdi:file-document-outline');
  });
});

describe('assertNever', () => {
  it('throws, naming the value it did not expect', () => {
    // It is the runtime half of a compile-time exhaustiveness guard: adding a
    // document kind and forgetting a `case` has to fail loudly, not return
    // undefined into a template. The message carries the offending value so the
    // report says which kind.
    expect(() => assertNever({ kind: 'sticky-note' })).toThrow(
      /Unexpected document kind: \{"kind":"sticky-note"\}/,
    );
  });

  it('is reached by every helper for an unknown kind', () => {
    const unknown = { kind: 'sticky-note' };
    expect(() => isDisplayableDocument(unknown)).toThrow(/Unexpected document kind/);
    expect(() => documentLabel(unknown)).toThrow(/Unexpected document kind/);
    expect(() => documentIcon(unknown)).toThrow(/Unexpected document kind/);
  });
});

describe('signedFileKey', () => {
  it('joins kind, asset and id in that order', () => {
    expect(signedFileKey({ kind: 'document', assetId: 'a1', id: 'd1' })).toBe(
      'document:a1:d1',
    );
    expect(signedFileKey({ kind: 'part', assetId: 'a1', id: 'p1' })).toBe('part:a1:p1');
  });

  it('separates the two namespaces', () => {
    // A document and a part can share an id; keying without the kind would make
    // one file's signed URL serve the other.
    expect(signedFileKey({ kind: 'document', assetId: 'a1', id: 'x' })).not.toBe(
      signedFileKey({ kind: 'part', assetId: 'a1', id: 'x' }),
    );
    expect(signedFileKey({ kind: 'document', assetId: 'a1', id: 'x' })).not.toBe(
      signedFileKey({ kind: 'document', assetId: 'a2', id: 'x' }),
    );
  });
});
