import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { graftPartFile, updateDocument } from '../src/panel-asset-editors.ts';
import { runUpload } from '../src/panel-upload.ts';
import { definePanelStubs, makeHass, mountPanel } from './panel-harness.js';

/**
 * Low findings in the appliance editor: a part-file result applied by part id
 * (F08-4), a link edit with no URL (F08-5), and an upload that outlives its draft
 * (X12-8).
 */

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
});

/** A bare host: the fields these helpers read, and a counted render. */
function host(asset) {
  const p = new EventTarget();
  Object.assign(p, {
    _assetEdit: { open: true, asset },
    _render: vi.fn(),
  });
  return p;
}

const FILE = { file_name: 'anode.pdf', file_content_type: 'application/pdf', file_size: 10 };

describe('F08-4: a part-file result goes to the part, by id', () => {
  it('finds the part after a part above it was removed', () => {
    // The upload started on Anode at index 1. Filter was removed while it ran.
    const p = host({ id: 'A', parts: [{ id: 'p2', name: 'Anode' }] });
    graftPartFile(p, 'A', 'p2', FILE);
    expect(p._assetEdit.asset.parts).toEqual([{ id: 'p2', name: 'Anode', ...FILE }]);
    expect(p._render).toHaveBeenCalledTimes(1);
  });

  it('changes nothing for a removed part or another appliance', () => {
    const parts = [{ id: 'p1', name: 'Filter' }];
    const p = host({ id: 'A', parts });
    graftPartFile(p, 'A', 'p2', FILE);
    graftPartFile(p, 'B', 'p1', FILE);
    expect(p._assetEdit.asset.parts).toBe(parts);
    expect(p._render).not.toHaveBeenCalled();
    // A closed form has no draft: no TypeError.
    const closed = host(null);
    expect(() => graftPartFile(closed, 'A', 'p1', FILE)).not.toThrow();
  });
});

describe('F08-5: a link edit with no URL', () => {
  it('is refused next to the editor, with no call to the backend', async () => {
    const doc = { id: 'd1', kind: 'link', name: 'Manual', url: 'https://ex.com/m' };
    const p = host({ id: 'A', documents: [doc] });
    p._hass = { callWS: vi.fn() };
    for (const url of ['', '   ']) {
      await updateDocument(p, doc, { name: 'Manual', url });
      expect(p._assetEdit.uploadError).toEqual({
        key: 'doc:d1',
        message: 'Enter the URL of the link.',
        link: undefined,
      });
    }
    expect(p._hass.callWS).not.toHaveBeenCalled();
    expect(p._assetEdit.asset.documents[0].url).toBe('https://ex.com/m');
  });

  it('still saves a rename of a file, which has no URL', async () => {
    const doc = { id: 'd2', kind: 'file', name: 'Scan' };
    const p = host({ documents: [doc] });
    await updateDocument(p, doc, { name: 'Warranty' });
    expect(p._assetEdit.uploadError).toBeUndefined();
    expect(p._assetEdit.asset.documents[0].name).toBe('Warranty');
  });
});

describe('X12-8: an upload that outlives its draft', () => {
  const file = (name) => new File(['x'], name, { type: 'application/pdf' });

  it('clears only its own state when a second upload started after it', async () => {
    const p = host({ id: 'A' });
    let finishFirst;
    const first = runUpload(p, 'document', file('a.pdf'), () =>
      new Promise((resolve) => {
        finishFirst = resolve;
      }),
    );
    const firstAbort = p._uploadAbort;
    // The draft closes and a new one starts its own upload.
    p._assetEdit = { open: true, asset: { id: 'B' } };
    const second = runUpload(p, 'document', file('b.pdf'), () => new Promise(() => {}));
    const secondAbort = p._uploadAbort;
    const secondState = p._assetEdit.upload;
    expect(secondAbort).not.toBe(firstAbort);

    finishFirst({ id: 'A' });
    await first;
    expect(p._uploadAbort).toBe(secondAbort);
    expect(p._assetEdit.upload).toBe(secondState);
    expect(p._uploadShowTimer).toBeDefined();
    void second;
  });

  it('is cancelled when the panel closes or replaces the appliance form', async () => {
    const { panel } = await mountPanel('/appliances', makeHass());
    for (const replace of [
      () => panel._closeAssetForm(),
      () => panel._openCreateAsset(),
    ]) {
      const ctrl = new AbortController();
      panel._uploadAbort = ctrl;
      replace();
      expect(ctrl.signal.aborted).toBe(true);
    }
  });
});
