import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import * as api from '../src/api.ts';
import { MAX_DOCUMENT_BYTES } from '../src/limits.ts';
import { HomeKeeperPanel } from '../src/panel.ts';

// ---------------------------------------------------------------------------
// Fake XMLHttpRequest
// ---------------------------------------------------------------------------
// jsdom ships a real XHR, but it needs a server to talk to. These tests drive the
// transport directly so upload progress, aborts and the 413 branches are all
// deterministic. Each instance records what it was given and exposes helpers to
// synthesize the events a browser would fire.

class FakeXHR {
  static instances = [];

  constructor() {
    this.headers = {};
    this.responseText = '';
    this.status = 0;
    this.upload = new EventTarget();
    this._listeners = new EventTarget();
    this.aborted = false;
    FakeXHR.instances.push(this);
  }

  open(method, url) {
    this.method = method;
    this.url = url;
    this.opened = true;
  }

  setRequestHeader(name, value) {
    // Mirrors the browser: headers may only be set once the request is open.
    if (!this.opened) throw new Error('setRequestHeader before open()');
    this.headers[name] = value;
  }

  addEventListener(type, fn) {
    this._listeners.addEventListener(type, fn);
  }

  send(body) {
    this.body = body;
  }

  abort() {
    this.aborted = true;
    this._listeners.dispatchEvent(new Event('abort'));
  }

  // --- test helpers -------------------------------------------------------
  emitProgress(loaded, total, lengthComputable = true) {
    const e = new Event('progress');
    Object.assign(e, { loaded, total, lengthComputable });
    this.upload.dispatchEvent(e);
  }

  emitUploadDone() {
    this.upload.dispatchEvent(new Event('load'));
  }

  respond(status, responseText) {
    this.status = status;
    this.responseText = responseText;
    this._listeners.dispatchEvent(new Event('load'));
  }

  fail() {
    this._listeners.dispatchEvent(new Event('error'));
  }
}

const HASS = { auth: { data: { access_token: 'tok-123' } } };

function makeFile(name, size, type = 'application/pdf') {
  // A real File of 26 MB would be slow and pointless — only `.size` is read.
  const file = new File(['x'], name, { type });
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

let realXHR;
beforeEach(() => {
  FakeXHR.instances = [];
  realXHR = globalThis.XMLHttpRequest;
  globalThis.XMLHttpRequest = FakeXHR;
});
afterEach(() => {
  globalThis.XMLHttpRequest = realXHR;
});

const only = () => {
  expect(FakeXHR.instances).toHaveLength(1);
  return FakeXHR.instances[0];
};

describe('api upload transport', () => {
  it('POSTs multipart to the document view with the auth header set after open()', async () => {
    const p = api.uploadAssetDocument(HASS, 'asset-1', 'doc-1', makeFile('m.pdf', 1000));
    const xhr = only();
    expect(xhr.method).toBe('POST');
    expect(xhr.url).toBe('/api/home_keeper/document/asset-1/doc-1');
    expect(xhr.headers.Authorization).toBe('Bearer tok-123');
    expect(xhr.body).toBeInstanceOf(FormData);
    expect(xhr.body.get('file')).toBeTruthy();

    xhr.respond(200, JSON.stringify({ asset: { id: 'asset-1', name: 'Boiler' } }));
    await expect(p).resolves.toMatchObject({ id: 'asset-1' });
  });

  it('POSTs to the part-file view and returns just the part', async () => {
    const p = api.uploadPartFile(HASS, 'asset-1', 'part-9', makeFile('r.pdf', 10));
    const xhr = only();
    expect(xhr.url).toBe('/api/home_keeper/part_document/asset-1/part-9');
    xhr.respond(200, JSON.stringify({ part: { id: 'part-9', file_name: 'r.pdf' } }));
    await expect(p).resolves.toMatchObject({ id: 'part-9', file_name: 'r.pdf' });
  });

  it('reports byte progress, then a final sent event once the body is on the wire', async () => {
    const seen = [];
    const p = api.uploadAssetDocument(HASS, 'a', 'd', makeFile('m.pdf', 100), undefined, {
      onProgress: (x) => seen.push(x),
    });
    const xhr = only();
    xhr.emitProgress(0, 100);
    xhr.emitProgress(50, 100);
    xhr.emitUploadDone();
    xhr.respond(200, JSON.stringify({ asset: {} }));
    await p;

    expect(seen.slice(0, 2)).toEqual([
      { loaded: 0, total: 100, indeterminate: false, sent: false },
      { loaded: 50, total: 100, indeterminate: false, sent: false },
    ]);
    // The last event flips `sent` so the UI can say "saving" instead of sitting at
    // 100% while the server writes the blob.
    expect(seen.at(-1).sent).toBe(true);
  });

  it('marks progress indeterminate when the length is not computable', async () => {
    const seen = [];
    const p = api.uploadAssetDocument(HASS, 'a', 'd', makeFile('m.pdf', 100), undefined, {
      onProgress: (x) => seen.push(x),
    });
    const xhr = only();
    xhr.emitProgress(10, 0, false);
    xhr.respond(200, JSON.stringify({ asset: {} }));
    await p;
    expect(seen[0]).toMatchObject({ indeterminate: true, total: 0 });
  });

  it('surfaces a Home Keeper 413 with its JSON message (serverMessage: true)', async () => {
    const p = api.uploadAssetDocument(HASS, 'a', 'd', makeFile('big.pdf', 1));
    only().respond(413, JSON.stringify({ message: 'File exceeds the 25 MB limit.' }));
    await expect(p).rejects.toMatchObject({
      status: 413,
      serverMessage: true,
      message: 'File exceeds the 25 MB limit.',
    });
  });

  it('flags a proxy 413 (non-JSON body) as serverMessage: false', async () => {
    // Regression lock: this branch only works because the response is parsed as text
    // and JSON.parse is allowed to throw. Setting xhr.responseType = 'json' would
    // silently break the "a proxy in front of HA rejected this" guidance.
    const p = api.uploadAssetDocument(HASS, 'a', 'd', makeFile('big.pdf', 1));
    only().respond(413, '<html><body><h1>413 Request Entity Too Large</h1></body></html>');
    await expect(p).rejects.toMatchObject({ status: 413, serverMessage: false });
  });

  it('reports a transport failure with status 0 and how far the body got', async () => {
    const p = api.uploadAssetDocument(HASS, 'a', 'd', makeFile('m.pdf', 100));
    const xhr = only();
    xhr.emitProgress(40, 100);
    xhr.fail();
    await expect(p).rejects.toMatchObject({ status: 0, bytesSent: 40 });
  });

  it('rejects as aborted when the signal fires', async () => {
    const ctrl = new AbortController();
    const p = api.uploadAssetDocument(HASS, 'a', 'd', makeFile('m.pdf', 100), undefined, {
      signal: ctrl.signal,
    });
    ctrl.abort();
    expect(only().aborted).toBe(true);
    await expect(p).rejects.toMatchObject({ aborted: true });
  });
});

// ---------------------------------------------------------------------------
// Panel behaviour (issue #159)
// ---------------------------------------------------------------------------

beforeAll(() => {
  for (const tag of [
    'ha-card',
    'ha-form',
    'ha-button',
    'ha-icon-button',
    'ha-tab-group',
    'ha-tab-group-tab',
    'ha-alert',
    'ha-assist-chip',
    'ha-menu-button',
    'ha-svg-icon',
    'ha-spinner',
    'ha-icon',
  ]) {
    if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
  }
  if (!customElements.get('home-keeper-panel')) {
    customElements.define('home-keeper-panel', HomeKeeperPanel);
  }
});

const ASSET = {
  id: 'asset-1',
  name: 'Water heater',
  kind: 'virtual',
  documents: [],
  parts: [{ id: 'part-1', name: 'Anode rod' }],
};

function makeHass() {
  return {
    language: 'en',
    states: {},
    devices: {},
    auth: { data: { access_token: 'tok-123' } },
    callWS(msg) {
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks: [] });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [structuredClone(ASSET)] });
        case 'home_keeper/get_options':
          return Promise.resolve({ options: {} });
        default:
          return Promise.resolve({});
      }
    },
  };
}

async function waitFor(fn, timeout = 2000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const v = fn();
    if (v) return v;
    await new Promise((r) => setTimeout(r, 20));
  }
  return null;
}

const PREFIX = '/home-keeper';

/** Boot the panel on the saved appliance's edit form, driving the real UI.
 *
 *  The panel navigates by pushState + a bubbling `location-changed`; in HA the
 *  router catches that and feeds the new path back through `route`. Nothing does
 *  that in jsdom, so stand in for the router here. */
async function openAssetEditForm() {
  const panel = document.createElement('home-keeper-panel');
  history.replaceState(null, '', `${PREFIX}/appliances/asset-1`);
  panel.route = { prefix: PREFIX, path: '/appliances/asset-1' };
  panel.addEventListener('location-changed', () => {
    panel.route = { prefix: PREFIX, path: location.pathname.slice(PREFIX.length) || '/' };
  });
  document.body.appendChild(panel);
  panel.hass = makeHass();
  const edit = await waitFor(() => panel.shadowRoot?.querySelector('.d-edit'));
  expect(edit, 'appliance detail should offer Edit').toBeTruthy();
  edit.click();
  const form = await waitFor(() => panel.shadowRoot?.querySelector('#hk-asset-form'));
  expect(form, 'edit form should render').toBeTruthy();
  return panel;
}

/** Fire a file pick on the picker inside `container`. */
function pick(container, file) {
  const picker = container.querySelector('input[type="file"]');
  expect(picker, 'file picker should exist').toBeTruthy();
  Object.defineProperty(picker, 'files', { value: [file], configurable: true });
  picker.dispatchEvent(new Event('change'));
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('oversized file is refused before it is uploaded (issue #159)', () => {
  it('shows the error next to the Upload button and toasts it — without any request', async () => {
    const panel = await openAssetEditForm();
    const toasts = [];
    panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));

    pick(
      panel.shadowRoot.querySelector('.hk-doc-add'),
      makeFile('huge.pdf', MAX_DOCUMENT_BYTES + 1),
    );

    // The whole point: no bytes leave the browser.
    expect(FakeXHR.instances).toHaveLength(0);

    // The failure is rendered inside the documents box, next to the button that
    // caused it — not only in the form-level alert far below the fold.
    const alert = await waitFor(() =>
      panel.shadowRoot.querySelector('.hk-doc-add ha-alert[alert-type="error"]'),
    );
    expect(alert, 'error should render next to the upload control').toBeTruthy();
    expect(alert.textContent).toContain('25 MB');

    // ...and HA's snackbar fires too, so it is visible at any scroll position.
    expect(toasts).toHaveLength(1);
    expect(toasts[0]).toContain('25 MB');
  });

  it('does the same for a part file', async () => {
    const panel = await openAssetEditForm();
    const toasts = [];
    panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));

    const part = await waitFor(() => panel.shadowRoot.querySelector('.hk-part'));
    expect(part, 'parts editor should render').toBeTruthy();
    pick(part, makeFile('huge.pdf', MAX_DOCUMENT_BYTES + 1));

    expect(FakeXHR.instances).toHaveLength(0);
    const alert = await waitFor(() =>
      panel.shadowRoot.querySelector('.hk-part ha-alert[alert-type="error"]'),
    );
    expect(alert, 'error should render next to the attach control').toBeTruthy();
    expect(toasts[0]).toContain('25 MB');
  });

  it('accepts a file exactly at the limit', async () => {
    const panel = await openAssetEditForm();
    pick(panel.shadowRoot.querySelector('.hk-doc-add'), makeFile('exact.pdf', MAX_DOCUMENT_BYTES));
    const xhr = await waitFor(() => FakeXHR.instances[0]);
    expect(xhr, 'a file at exactly the limit should be uploaded').toBeTruthy();
  });
});

describe('in-flight upload feedback', () => {
  it('disables the upload and save buttons and shows progress while uploading', async () => {
    const panel = await openAssetEditForm();
    pick(panel.shadowRoot.querySelector('.hk-doc-add'), makeFile('m.pdf', 5000));

    const xhr = await waitFor(() => FakeXHR.instances[0]);
    expect(xhr).toBeTruthy();

    const disabled = await waitFor(() =>
      panel.shadowRoot.querySelector('.hk-doc-add ha-button[disabled]'),
    );
    expect(disabled, 'upload button should be disabled mid-upload').toBeTruthy();
    expect(disabled.textContent).toBe('Uploading…');
    expect(
      panel.shadowRoot.querySelector('#a-save[disabled]'),
      'save is disabled so it cannot race the upload',
    ).toBeTruthy();

    // The bar only appears once the upload has run long enough to be worth showing.
    const bar = await waitFor(() => panel.shadowRoot.querySelector('#hk-upload-bar'));
    expect(bar, 'progress bar should render').toBeTruthy();
    xhr.emitProgress(2500, 5000);
    expect(bar.getAttribute('aria-valuenow')).toBe('50');
    expect(panel.shadowRoot.querySelector('.hk-upload-fill').style.width).toBe('50%');
    expect(panel.shadowRoot.querySelector('.hk-upload-label').textContent).toContain('50%');

    // Body sent, server still storing it: no percentage to show any more.
    xhr.emitUploadDone();
    expect(bar.hasAttribute('aria-valuenow')).toBe(false);
    expect(bar.getAttribute('aria-busy')).toBe('true');

    xhr.respond(200, JSON.stringify({ asset: { ...ASSET, documents: [] } }));
    const cleared = await waitFor(() => !panel.shadowRoot.querySelector('#hk-upload'));
    expect(cleared, 'progress UI should be torn down when the upload finishes').toBeTruthy();
  });

  it('clears a stale error when the next upload succeeds', async () => {
    const panel = await openAssetEditForm();
    pick(
      panel.shadowRoot.querySelector('.hk-doc-add'),
      makeFile('huge.pdf', MAX_DOCUMENT_BYTES + 1),
    );
    expect(
      await waitFor(() => panel.shadowRoot.querySelector('.hk-doc-add ha-alert')),
      'first (failing) pick should show an error',
    ).toBeTruthy();

    pick(panel.shadowRoot.querySelector('.hk-doc-add'), makeFile('ok.pdf', 10));
    const xhr = await waitFor(() => FakeXHR.instances[0]);
    xhr.respond(200, JSON.stringify({ asset: { ...ASSET, documents: [] } }));

    const gone = await waitFor(() => !panel.shadowRoot.querySelector('.hk-doc-add ha-alert'));
    expect(gone, 'a successful upload should clear the previous failure').toBeTruthy();
  });

  it('reports a proxy 413 with a Learn more link', async () => {
    const panel = await openAssetEditForm();
    pick(panel.shadowRoot.querySelector('.hk-doc-add'), makeFile('m.pdf', 10));
    const xhr = await waitFor(() => FakeXHR.instances[0]);
    xhr.respond(413, '<html>413 Request Entity Too Large</html>');

    const alert = await waitFor(() =>
      panel.shadowRoot.querySelector('.hk-doc-add ha-alert[alert-type="error"]'),
    );
    expect(alert.textContent).toContain('reverse proxy');
    expect(alert.querySelector('a')?.getAttribute('href')).toContain('large-uploads-413');
  });

  it('says nothing when the user cancels', async () => {
    const panel = await openAssetEditForm();
    const toasts = [];
    panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));
    pick(panel.shadowRoot.querySelector('.hk-doc-add'), makeFile('m.pdf', 5000));

    const xhr = await waitFor(() => FakeXHR.instances[0]);
    await waitFor(() => panel.shadowRoot.querySelector('#hk-upload'));
    const cancel = [...panel.shadowRoot.querySelectorAll('.hk-upload ha-button')].at(-1);
    expect(cancel.textContent).toBe('Cancel upload');
    cancel.click();
    expect(xhr.aborted).toBe(true);

    const cleared = await waitFor(() => !panel.shadowRoot.querySelector('#hk-upload'));
    expect(cleared, 'cancelling should tear down the progress UI').toBeTruthy();
    expect(panel.shadowRoot.querySelector('.hk-doc-add ha-alert')).toBeNull();
    expect(toasts, 'a cancellation is not an error').toEqual([]);
  });
});
