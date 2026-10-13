/**
 * The QR label dialog: the note on the base address of the code, the warning in a
 * Home Assistant companion app, and the text position of a roll label.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderLabelDialog, openLabelDialog } from '../src/panel-labels.ts';
import { LS_LABELS } from '../src/panel-types.ts';

const ASSET = { id: 'a1', name: 'Water heater', manufacturer: 'Rheem', model: 'XE50' };
const BROWSER_UA = navigator.userAgent;

function host(hass = {}) {
  return {
    _view: 'appliances',
    _tasks: [],
    _assets: [ASSET],
    _hass: { devices: {}, areas: {}, config: {}, ...hass },
    _hrefFor: (route) => `/home-keeper/${route.view}/${route.detail.id}`,
    _render() {},
  };
}

function render(p) {
  openLabelDialog(p, 'asset', 'a1');
  const root = document.createElement('div');
  renderLabelDialog(p, root);
  document.body.appendChild(root);
  return root;
}

function setUserAgent(ua) {
  Object.defineProperty(window.navigator, 'userAgent', { value: ua, configurable: true });
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  document.body.innerHTML = '';
  setUserAgent(BROWSER_UA);
  vi.restoreAllMocks();
});

describe('base address note', () => {
  it('names the external URL and gives no warning for HTTPS', () => {
    const root = render(host({ config: { external_url: 'https://ha.example.com' } }));
    expect(root.querySelector('[data-label-base]').dataset.labelBase).toBe('external');
    expect(root.querySelector('[data-label-base]').textContent).toContain('external URL');
    expect(root.querySelector('[data-label-not-https]')).toBeNull();
    expect(root.querySelector('[data-label-link]').value).toBe(
      'https://ha.example.com/home-keeper/appliances/a1',
    );
  });

  it('warns when the code uses an HTTP internal URL', () => {
    const root = render(host({ config: { internal_url: 'http://192.168.1.2:8123' } }));
    expect(root.querySelector('[data-label-base]').dataset.labelBase).toBe('internal');
    expect(root.querySelector('[data-label-not-https]').textContent).toContain('HTTPS');
  });
});

describe('companion app warning', () => {
  it('shows no warning in a browser', () => {
    const root = render(host());
    expect(root.querySelector('[data-label-app-warning]')).toBeNull();
  });

  it('warns before the print when hass.auth.external is set', () => {
    const root = render(host({ auth: { external: {} } }));
    const alert = root.querySelector('[data-label-app-warning]');
    expect(alert.getAttribute('alert-type')).toBe('warning');
    expect(alert.textContent).toContain('Copy link');
  });

  it('warns for the user agent of the app', () => {
    setUserAgent('Mozilla/5.0 (Linux; Android 14) Home Assistant/2025.4.1');
    const root = render(host());
    expect(root.querySelector('[data-label-app-warning]')).not.toBeNull();
  });
});

describe('text position', () => {
  it('shows the field for a roll only, and keeps the choice in this browser', () => {
    localStorage.setItem(LS_LABELS, JSON.stringify({ paper: 'a4_21' }));
    let root = render(host());
    expect(root.querySelector('[data-label-text-pos-field]').hidden).toBe(true);
    expect(root.querySelector('[data-label-preview]').dataset.fit).toBe('side');

    localStorage.setItem(
      LS_LABELS,
      JSON.stringify({ paper: 'roll_custom', customW: 24, customH: 24 }),
    );
    document.body.innerHTML = '';
    root = render(host());
    expect(root.querySelector('[data-label-text-pos-field]').hidden).toBe(false);
    expect(root.querySelector('[data-label-preview]').dataset.fit).toBe('code');

    const select = root.querySelector('[data-label-text-pos]');
    select.value = 'below';
    select.dispatchEvent(new Event('change'));
    expect(JSON.parse(localStorage.getItem(LS_LABELS)).textPos).toBe('below');
    expect(root.querySelector('[data-label-preview]').dataset.fit).toBe('below');
  });
});
