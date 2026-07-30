import { describe, expect, it, vi } from 'vitest';
import { SignedUrlCache, assetFileRefs, signedFileKey } from '../src/documents.ts';

// A hass stub that mints a distinct URL per call so a re-sign is observable, and
// records how many times each signing command was invoked.
function makeHass(fail = false) {
  const calls = { document: 0, part: 0 };
  const hass = {
    callWS(msg) {
      if (msg.type === 'home_keeper/sign_document_url') {
        calls.document++;
        if (fail) return Promise.reject(new Error('sign failed'));
        return Promise.resolve({ url: `/doc/${msg.document_id}?sig=${calls.document}` });
      }
      if (msg.type === 'home_keeper/sign_part_file_url') {
        calls.part++;
        if (fail) return Promise.reject(new Error('sign failed'));
        return Promise.resolve({ url: `/part/${msg.part_id}?sig=${calls.part}` });
      }
      return Promise.resolve({});
    },
  };
  return { hass, calls };
}

const DOC = { kind: 'document', assetId: 'a1', id: 'd1' };
const PART = { kind: 'part', assetId: 'a1', id: 'p1' };

describe('SignedUrlCache', () => {
  it('signs each file once and reuses the URL across renders', async () => {
    const { hass, calls } = makeHass();
    const cache = new SignedUrlCache();

    expect(cache.get(DOC), 'nothing is signed up front').toBeUndefined();
    await cache.ensure(hass, [DOC, PART]);
    expect(cache.get(DOC)).toBe('/doc/d1?sig=1');
    expect(cache.get(PART)).toBe('/part/p1?sig=1');

    // A re-render passing the same refs must not spend another round-trip: a
    // dashboard/panel re-renders constantly and would otherwise spam the command.
    await cache.ensure(hass, [DOC, PART]);
    expect(calls).toEqual({ document: 1, part: 1 });
  });

  it('re-signs once the URL approaches the backend TTL', async () => {
    const { hass, calls } = makeHass();
    const cache = new SignedUrlCache();
    await cache.ensure(hass, [DOC]);
    expect(cache.get(DOC)).toBe('/doc/d1?sig=1');

    // The backend's signed URLs live 1h; the cache re-mints at 45min so an idle page's
    // hrefs never go stale under the user.
    const realNow = Date.now;
    Date.now = () => realNow() + 46 * 60 * 1000;
    try {
      await cache.ensure(hass, [DOC]);
    } finally {
      Date.now = realNow;
    }
    expect(calls.document).toBe(2);
    expect(cache.get(DOC)).toBe('/doc/d1?sig=2');
  });

  it('drops URLs for files the surface no longer shows', async () => {
    const { hass } = makeHass();
    const cache = new SignedUrlCache();
    await cache.ensure(hass, [DOC, PART]);

    // Navigating to another appliance passes a different (here: empty) ref set, so the
    // previous screen's URLs are evicted rather than accumulating for the session.
    await cache.ensure(hass, []);
    expect(cache.get(DOC)).toBeUndefined();
    expect(cache.get(PART)).toBeUndefined();
  });

  it('keeps the previous URL when a re-sign fails', async () => {
    const { hass } = makeHass();
    const cache = new SignedUrlCache();
    await cache.ensure(hass, [DOC]);

    const { hass: broken } = makeHass(true);
    const realNow = Date.now;
    Date.now = () => realNow() + 46 * 60 * 1000;
    try {
      await expect(cache.ensure(broken, [DOC])).resolves.toBe(false);
    } finally {
      Date.now = realNow;
    }
    // A transient websocket failure must not blank an href that still has ~15min left.
    expect(cache.get(DOC)).toBe('/doc/d1?sig=1');
  });

  it('reports whether anything was minted, so a caller can skip a needless re-render', async () => {
    const { hass } = makeHass();
    const cache = new SignedUrlCache();
    await expect(cache.ensure(hass, [DOC])).resolves.toBe(true);
    await expect(cache.ensure(hass, [DOC])).resolves.toBe(false);
    await expect(cache.ensure(hass, [])).resolves.toBe(false);
  });

  it('never signs anything for an empty ref set', async () => {
    const { hass, calls } = makeHass();
    const spy = vi.spyOn(hass, 'callWS');
    await new SignedUrlCache().ensure(hass, []);
    expect(spy).not.toHaveBeenCalled();
    expect(calls).toEqual({ document: 0, part: 0 });
  });
});

describe('signedFileKey / assetFileRefs', () => {
  it('keys documents and parts into separate namespaces', () => {
    // Both ids are server-minted and could collide across the two kinds; the kind
    // prefix is what keeps a part file from serving a document's URL.
    expect(signedFileKey({ kind: 'document', assetId: 'a1', id: 'x' })).toBe('document:a1:x');
    expect(signedFileKey({ kind: 'part', assetId: 'a1', id: 'x' })).toBe('part:a1:x');
  });

  it('collects exactly the appliance files that need signing', () => {
    const refs = assetFileRefs({
      id: 'a1',
      documents: [
        { id: 'd1', kind: 'link', url: 'https://example.com' }, // a link carries its own URL
        { id: 'd2', kind: 'file', filename: 'guide.pdf' },
        { kind: 'file', filename: 'no-id.pdf' }, // unsaved: nothing to sign against
      ],
      parts: [
        { id: 'p1', name: 'Anode rod', file_name: 'receipt.pdf' },
        { id: 'p2', name: 'Valve' }, // no attachment
      ],
    });
    expect(refs).toEqual([
      { kind: 'document', assetId: 'a1', id: 'd2' },
      { kind: 'part', assetId: 'a1', id: 'p1' },
    ]);
  });

  it('has nothing to sign for an appliance that has not been saved yet', () => {
    // A brand-new appliance has no id, so no stored blob can exist to sign.
    expect(
      assetFileRefs({ documents: [{ id: 'd1', kind: 'file', filename: 'g.pdf' }] }),
    ).toEqual([]);
    expect(assetFileRefs({})).toEqual([]);
  });
});
