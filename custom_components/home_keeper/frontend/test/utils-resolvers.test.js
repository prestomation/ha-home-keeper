import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  areaName,
  brandLogoUrl,
  deviceDomain,
  groupableDeviceId,
  deviceName,
  isArmedTriggered,
  isHttpUrl,
  isSafeImageUrl,
  labelName,
  randomId,
  round1,
  safeHref,
} from '../src/utils.ts';

// `utils.test.js` covers the summary/label formatters. These are the small
// resolvers and URL guards underneath the panel: the registry lookups that turn
// ids into names, and the scheme checks standing between caller-supplied strings
// and an `href`/`src`.

describe('isHttpUrl / safeHref', () => {
  it('accepts http and https, case-insensitively', () => {
    for (const url of ['http://x/y', 'https://x/y', 'HTTPS://X/Y', 'HtTp://x']) {
      expect(isHttpUrl(url)).toBe(true);
    }
  });

  it('rejects every other scheme and non-strings', () => {
    // `home_keeper.complete_task` takes a caller-supplied photo URL, so these
    // reach the DOM from outside the panel.
    for (const url of [
      'javascript:alert(1)',
      'JAVASCRIPT:alert(1)',
      'data:text/html,<script>alert(1)</script>',
      'vbscript:msgbox(1)',
      'file:///etc/passwd',
      '//evil.example.com/x',
      '/relative/path',
      'ftp://x/y',
      'not a url',
      '',
      null,
      undefined,
      42,
      { href: 'https://x' },
    ]) {
      expect(isHttpUrl(url), String(url)).toBe(false);
    }
  });

  it('must anchor at the start, not match a scheme anywhere', () => {
    expect(isHttpUrl('javascript:void(0)#https://x')).toBe(false);
    expect(isHttpUrl(' https://x')).toBe(false);
  });

  it('safeHref escapes an accepted URL and blanks a rejected one', () => {
    expect(safeHref('https://x/y?a=1&b=2')).toBe('https://x/y?a=1&amp;b=2');
    expect(safeHref('https://x/"onmouseover="alert(1)')).toBe(
      'https://x/&quot;onmouseover=&quot;alert(1)',
    );
    // Inert rather than dangerous: an empty href, not the original string.
    expect(safeHref('javascript:alert(1)')).toBe('');
    expect(safeHref(null)).toBe('');
  });
});

describe('isSafeImageUrl', () => {
  it('accepts http(s) and site-relative paths', () => {
    expect(isSafeImageUrl('https://x/y.png')).toBe(true);
    expect(isSafeImageUrl('/api/image/serve/abc/original')).toBe(true);
  });

  it('rejects protocol-relative URLs', () => {
    // `//evil.example.com/x` inherits the page scheme and loads off-site — the
    // reason the relative branch requires a non-slash second character.
    expect(isSafeImageUrl('//evil.example.com/x.png')).toBe(false);
    expect(isSafeImageUrl('///evil.example.com/x.png')).toBe(false);
  });

  it('rejects dangerous schemes, bare paths and non-strings', () => {
    for (const url of [
      'javascript:alert(1)',
      'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=',
      'vbscript:msgbox(1)',
      'relative/no/leading/slash.png',
      '/',
      '',
      null,
      undefined,
      7,
    ]) {
      expect(isSafeImageUrl(url), String(url)).toBe(false);
    }
  });
});

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('randomId', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('returns a well-formed v4 UUID', () => {
    expect(randomId()).toMatch(UUID_V4);
  });

  it('does not repeat', () => {
    const ids = new Set(Array.from({ length: 50 }, () => randomId()));
    expect(ids.size).toBe(50);
  });

  it('still works without crypto.randomUUID (plain-HTTP LAN)', () => {
    // `crypto.randomUUID` is secure-context only, so it is undefined over
    // http://192.168.x.x:8123 — calling it there throws and silently breaks
    // file uploads and link-adds for anyone reaching HA by LAN address.
    const getRandomValues = globalThis.crypto.getRandomValues.bind(globalThis.crypto);
    vi.stubGlobal('crypto', { getRandomValues });
    expect(randomId()).toMatch(UUID_V4);
  });

  it('still works with no crypto at all', () => {
    vi.stubGlobal('crypto', undefined);
    expect(randomId()).toMatch(UUID_V4);
  });

  it('sets the version and variant bits even on the fallback path', () => {
    // The fallback hand-builds the UUID, so the RFC 4122 bits are ours to get
    // right; a plain hex dump would pass a laxer regex but not this one.
    vi.stubGlobal('crypto', undefined);
    for (let i = 0; i < 20; i += 1) {
      const id = randomId();
      expect(id[14]).toBe('4');
      expect('89ab').toContain(id[19]);
    }
  });
});

describe('isArmedTriggered', () => {
  it('is true only for a triggered task with a due date', () => {
    expect(isArmedTriggered({ recurrence_type: 'triggered', next_due: '2026-01-01' })).toBe(
      true,
    );
    expect(isArmedTriggered({ recurrence_type: 'triggered', next_due: null })).toBe(false);
    expect(isArmedTriggered({ recurrence_type: 'triggered' })).toBe(false);
    // A due date on a non-triggered task is the normal case, not "armed".
    expect(isArmedTriggered({ recurrence_type: 'floating', next_due: '2026-01-01' })).toBe(
      false,
    );
  });
});

describe('round1', () => {
  it('keeps at most one decimal', () => {
    expect(round1(661.4166666)).toBe(661.4);
    expect(round1(661.45)).toBe(661.5);
    expect(round1(661)).toBe(661);
    expect(round1(0)).toBe(0);
  });

  it('rounds at one decimal, not zero or two', () => {
    // 661.44 -> 661.4 distinguishes 1dp from both 0dp (661) and 2dp (661.44).
    expect(round1(661.44)).toBe(661.4);
    expect(round1(-3.26)).toBe(-3.3);
  });
});

describe('registry resolvers', () => {
  it('deviceName prefers the user name, then the name', () => {
    const devices = {
      d1: { name: 'Fridge', name_by_user: 'Kitchen fridge' },
      d2: { name: 'Fridge', name_by_user: null },
    };
    expect(deviceName(devices, 'd1')).toBe('Kitchen fridge');
    expect(deviceName(devices, 'd2')).toBe('Fridge');
  });

  // #262: the id used to be the fallback, which put a raw
  // "5ff1f1bb41a19a763aa4ab750cd37c97" on screen as a chip label whenever a task
  // outlived the device it pointed at. An id is not a name in any language.
  it('deviceName is empty when there is no name to show, never the id', () => {
    const devices = { d1: { name: 'Fridge' }, d3: {} };
    expect(deviceName(devices, 'd3')).toBe('');
    expect(deviceName(devices, 'gone')).toBe('');
    expect(deviceName(undefined, 'd1')).toBe('');
    expect(deviceName({}, 'd1')).toBe('');
  });

  it('groupableDeviceId groups only by a device that can be named', () => {
    const devices = { d1: { name: 'Fridge' }, d3: {} };
    expect(groupableDeviceId(devices, 'd1')).toBe('d1');
    // Registry presence is NOT the test. A device that is present but nameless
    // resolves to '', which would head its section with nothing at all — so it goes
    // to the "No device" bucket like one that has left the registry entirely.
    expect(groupableDeviceId(devices, 'd3')).toBeUndefined();
    expect(groupableDeviceId(devices, 'gone')).toBeUndefined();
    expect(groupableDeviceId(undefined, 'd1')).toBeUndefined();
    expect(groupableDeviceId(devices, null)).toBeUndefined();
    expect(groupableDeviceId(devices, '')).toBeUndefined();
  });

  it('deviceName is empty for a missing id, not the string "null"', () => {
    expect(deviceName({}, null)).toBe('');
    expect(deviceName({}, undefined)).toBe('');
    expect(deviceName({}, '')).toBe('');
  });

  it('deviceDomain prefers the primary config entry', () => {
    const entryDomains = { e1: 'zha', e2: 'mqtt' };
    expect(deviceDomain({ primary_config_entry: 'e1', config_entries: ['e2'] }, entryDomains)).toBe(
      'zha',
    );
    expect(deviceDomain({ config_entries: ['e2'] }, entryDomains)).toBe('mqtt');
    expect(deviceDomain({ config_entries: ['e2', 'e1'] }, entryDomains)).toBe('mqtt');
  });

  it('deviceDomain is undefined when it cannot resolve', () => {
    expect(deviceDomain(undefined, { e1: 'zha' })).toBeUndefined();
    expect(deviceDomain({ primary_config_entry: 'e1' }, undefined)).toBeUndefined();
    expect(deviceDomain({}, { e1: 'zha' })).toBeUndefined();
    expect(deviceDomain({ config_entries: [] }, { e1: 'zha' })).toBeUndefined();
    expect(deviceDomain({ primary_config_entry: 'unknown' }, { e1: 'zha' })).toBeUndefined();
  });

  it('areaName and labelName fall back to the id', () => {
    expect(areaName({ a1: { name: 'Kitchen' } }, 'a1')).toBe('Kitchen');
    expect(areaName({ a1: { name: '' } }, 'a1')).toBe('a1');
    expect(areaName({}, 'a1')).toBe('a1');
    expect(areaName(undefined, 'a1')).toBe('a1');
    expect(areaName({}, null)).toBe('');

    expect(labelName({ l1: { name: 'Seasonal' } }, 'l1')).toBe('Seasonal');
    expect(labelName({}, 'l1')).toBe('l1');
    expect(labelName(undefined, 'l1')).toBe('l1');
    expect(labelName({}, null)).toBe('');
  });
});

describe('brandLogoUrl', () => {
  it('points at the integration brand by default', () => {
    expect(brandLogoUrl('zha')).toBe('https://brands.home-assistant.io/zha/icon.png');
  });

  it('uses the generic "_" namespace as the fallback', () => {
    expect(brandLogoUrl('zha', true)).toBe('https://brands.home-assistant.io/_/zha/icon.png');
    expect(brandLogoUrl('zha', false)).toBe('https://brands.home-assistant.io/zha/icon.png');
  });
});
