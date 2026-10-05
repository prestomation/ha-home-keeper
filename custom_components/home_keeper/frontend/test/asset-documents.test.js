import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { definePanelStubs, emitChange, mountPanel, waitFor } from './panel-harness.js';

/**
 * The appliance drawer's documents and part files.
 *
 * F08-1: a failed document add, edit or remove, or part-file removal, showed its error
 * only in the banner at the foot of the drawer, and the re-render cleared the link the
 * user had typed. The error now shows next to the control, with a toast, and the typed
 * values stay.
 *
 * F08-3: the trash icon on a document and Remove on a part file deleted the stored
 * file at once. They now ask first.
 */

beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
  document.querySelectorAll('.hk-confirm-scrim').forEach((el) => el.remove());
  vi.restoreAllMocks();
});

const DOC = { id: 'd1', kind: 'link', name: 'Manual', url: 'https://acme.example/m.pdf' };
const FILE_DOC = { id: 'd2', kind: 'file', name: 'Warranty', filename: 'w.pdf' };

function asset() {
  return {
    id: 'a1',
    kind: 'virtual',
    name: 'Water heater',
    documents: [structuredClone(DOC), structuredClone(FILE_DOC)],
    parts: [{ id: 'p1', name: 'Anode rod', file_name: 'anode.pdf' }],
  };
}

/** A hass that refuses the listed write types with *message*, and records every call. */
function makeHass({ fail = [], message = 'document url must be an http(s) URL' } = {}) {
  const calls = [];
  const hass = {
    language: 'en',
    states: {},
    devices: {},
    callWS(msg) {
      calls.push(msg);
      if (fail.includes(msg.type)) return Promise.reject(new Error(message));
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks: [] });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [asset()] });
        case 'home_keeper/get_options':
          return Promise.resolve({ options: {} });
        case 'frontend/get_user_data':
          return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
        case 'home_keeper/add_asset_document':
        case 'home_keeper/update_asset_document':
        case 'home_keeper/remove_asset_document':
          return Promise.resolve({ asset: asset() });
        default:
          return Promise.resolve({});
      }
    },
  };
  return { hass, calls };
}

async function openDrawer(opts) {
  const { hass, calls } = makeHass(opts);
  const { panel } = await mountPanel('/appliances/a1', hass);
  const edit = await waitFor(() => panel.shadowRoot.querySelector('.d-edit'));
  edit.click();
  await waitFor(() => panel.shadowRoot.querySelector('#hk-asset-form .hk-doc-add'));
  const toasts = [];
  panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));
  return { panel, calls, toasts };
}

const sent = (calls, type) => calls.filter((c) => c.type === type);
const $ = (panel, sel) => panel.shadowRoot.querySelector(sel);
const iconButton = (panel, root, label) =>
  [...panel.shadowRoot.querySelectorAll(`${root} ha-icon-button`)].find(
    (b) => b.getAttribute('label') === label,
  );
const scrim = () => document.querySelector('.hk-confirm-scrim');
const confirmButton = (text) =>
  [...(scrim()?.querySelectorAll('ha-button') || [])].find((b) => b.textContent === text);

describe('F08-1: a failed document change shows next to the control', () => {
  it('keeps the typed link and shows the error beside Add link', async () => {
    const { panel, calls, toasts } = await openDrawer({
      fail: ['home_keeper/add_asset_document'],
    });
    emitChange($(panel, '.hk-doc-add ha-form'), {
      doc_name: 'Manual',
      doc_url: 'www.acme.com/manual.pdf',
    });
    $(panel, '.hk-doc-add .hk-meta-seeds ha-button').click();

    const alert = await waitFor(() => $(panel, '.hk-doc-add ha-alert[alert-type="error"]'));
    expect(alert, 'the error shows in the add area').toBeTruthy();
    expect(alert.textContent).toContain('http(s)');
    expect(toasts).toEqual(['document url must be an http(s) URL']);
    expect(sent(calls, 'home_keeper/add_asset_document')).toHaveLength(1);
    // The drawer re-rendered, and the form still holds what the user typed.
    expect($(panel, '.hk-doc-add ha-form').data).toEqual({
      doc_name: 'Manual',
      doc_url: 'www.acme.com/manual.pdf',
    });
    expect(panel._assetEdit.error, 'not the banner at the foot of the drawer').toBeFalsy();
  });

  it('keeps a typed link across an unrelated render', async () => {
    const { panel } = await openDrawer();
    emitChange($(panel, '.hk-doc-add ha-form'), { doc_name: 'Guide', doc_url: 'https://x.example' });
    panel._render();
    expect($(panel, '.hk-doc-add ha-form').data.doc_url).toBe('https://x.example');
  });

  it('clears the typed link once it is added', async () => {
    const { panel, calls } = await openDrawer();
    emitChange($(panel, '.hk-doc-add ha-form'), { doc_name: 'Guide', doc_url: 'https://x.example' });
    $(panel, '.hk-doc-add .hk-meta-seeds ha-button').click();
    await waitFor(() => sent(calls, 'home_keeper/add_asset_document').length);
    await waitFor(() => $(panel, '.hk-doc-add ha-form')?.data.doc_url === '');
    expect($(panel, '.hk-doc-add ha-form').data).toEqual({ doc_name: '', doc_url: '' });
  });

  it('keeps the correction in the inline editor when Save fails', async () => {
    const { panel, toasts } = await openDrawer({ fail: ['home_keeper/update_asset_document'] });
    iconButton(panel, '.hk-doc-actions', 'Edit').click();
    const form = await waitFor(() => $(panel, '.hk-doc-edit ha-form'));
    emitChange(form, { doc_url: 'acme.example/new.pdf' });
    $(panel, '.hk-doc-edit-actions ha-button').click();

    const alert = await waitFor(() => $(panel, '.hk-doc-edit ha-alert[alert-type="error"]'));
    expect(alert, 'the error shows in the editor').toBeTruthy();
    expect(toasts).toHaveLength(1);
    expect($(panel, '.hk-doc-edit ha-form').data.doc_url).toBe('acme.example/new.pdf');
  });
});

describe('F08-3: removing a document or a part file asks first', () => {
  it('does not remove a document until Delete is pressed', async () => {
    const { panel, calls } = await openDrawer();
    iconButton(panel, '.hk-doc-actions', 'Remove document').click();
    expect(scrim(), 'a confirmation opens').toBeTruthy();
    expect(scrim().querySelector('h2').textContent).toBe('Remove "Manual"?');
    expect(sent(calls, 'home_keeper/remove_asset_document')).toHaveLength(0);

    confirmButton('Cancel').click();
    expect(scrim()).toBeNull();
    expect(sent(calls, 'home_keeper/remove_asset_document')).toHaveLength(0);

    iconButton(panel, '.hk-doc-actions', 'Remove document').click();
    confirmButton('Delete').click();
    await waitFor(() => sent(calls, 'home_keeper/remove_asset_document').length);
    expect(sent(calls, 'home_keeper/remove_asset_document')[0].document_id).toBe('d1');
  });

  it('does not remove a part file until Delete is pressed, and shows a failure beside it', async () => {
    const { panel, calls, toasts } = await openDrawer({
      fail: ['home_keeper/remove_part_file'],
      message: 'storage error',
    });
    const remove = await waitFor(() => iconButton(panel, '.hk-part', 'Remove file'));
    remove.click();
    expect(scrim().querySelector('h2').textContent).toBe('Remove "anode.pdf"?');
    expect(sent(calls, 'home_keeper/remove_part_file')).toHaveLength(0);
    confirmButton('Delete').click();

    const alert = await waitFor(() => $(panel, '.hk-part ha-alert[alert-type="error"]'));
    expect(alert, 'F08-1: the error shows beside the part file').toBeTruthy();
    expect(alert.textContent).toBe('storage error');
    expect(toasts).toEqual(['storage error']);
    expect(panel._assetEdit.error).toBeFalsy();
  });
});

describe('X11-1: the confirmation is a real modal dialog', () => {
  async function openConfirm() {
    const env = await openDrawer();
    const opener = iconButton(env.panel, '.hk-doc-actions', 'Remove document');
    opener.tabIndex = 0;
    opener.focus();
    const focused = [];
    vi.spyOn(HTMLElement.prototype, 'focus').mockImplementation(function focus() {
      focused.push(this);
    });
    opener.click();
    return { ...env, opener, focused };
  }

  it('says it is a modal dialog and names itself from its heading', async () => {
    await openConfirm();
    const modal = scrim().querySelector('[role="dialog"]');
    expect(modal).toBeTruthy();
    expect(modal.getAttribute('aria-modal')).toBe('true');
    const title = document.getElementById(modal.getAttribute('aria-labelledby'));
    expect(title.textContent).toBe('Remove "Manual"?');
    const body = document.getElementById(modal.getAttribute('aria-describedby'));
    expect(body.textContent).toBe('This cannot be undone.');
    expect(modal.style.boxSizing).toBe('border-box');
  });

  it('gives the keyboard to Cancel when it opens', async () => {
    const { focused } = await openConfirm();
    expect(focused.at(-1)).toBe(confirmButton('Cancel'));
  });

  it('keeps Tab inside the dialog', async () => {
    const { focused } = await openConfirm();
    const cancel = confirmButton('Cancel');
    const del = confirmButton('Delete');
    vi.restoreAllMocks();
    cancel.tabIndex = 0;
    del.tabIndex = 0;
    cancel.focus();
    const tab = (shiftKey = false) => {
      const e = new KeyboardEvent('keydown', { key: 'Tab', shiftKey, cancelable: true });
      document.dispatchEvent(e);
      return e;
    };
    expect(tab().defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(del);
    tab();
    expect(document.activeElement, 'Tab wraps to the first button').toBe(cancel);
    tab(true);
    expect(document.activeElement, 'Shift+Tab wraps to the last button').toBe(del);
    tab(true);
    expect(document.activeElement).toBe(cancel);
    expect(focused.length).toBeGreaterThan(0);
  });

  it('takes Tab back from the page behind it', async () => {
    const { opener } = await openConfirm();
    vi.restoreAllMocks();
    const cancel = confirmButton('Cancel');
    const del = confirmButton('Delete');
    cancel.tabIndex = 0;
    del.tabIndex = 0;
    opener.focus();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', cancelable: true }));
    expect(document.activeElement).toBe(cancel);
    opener.focus();
    document.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, cancelable: true }),
    );
    expect(document.activeElement).toBe(del);
  });

  it('closes on Escape and gives the keyboard back to the opener', async () => {
    const { opener, focused } = await openConfirm();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(scrim()).toBeNull();
    expect(focused.at(-1)).toBe(opener);
  });

  it('lets other keys through', async () => {
    await openConfirm();
    const e = new KeyboardEvent('keydown', { key: 'a', cancelable: true });
    document.dispatchEvent(e);
    expect(e.defaultPrevented).toBe(false);
    expect(scrim()).toBeTruthy();
  });
});
