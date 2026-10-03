import { afterEach, describe, expect, it } from 'vitest';
import { setLanguage } from '../src/i18n.ts';
import { wireBrandImage } from '../src/panel-chips.ts';
import { declarativeRow, wireDeclarativeSection } from '../src/panel-declarative.ts';

/**
 * A declarative companion row on the Companions card: the integration logo on a tile,
 * a badge for the preset shape, and 1 meta line with the integration, the platform,
 * the limit and the count.
 */

const SELECTION = {
  target_integration: 'roborock',
  domain: 'sensor',
  area_ids: [],
  label_ids: [],
  exclude_entity_ids: [],
  exclude_device_ids: [],
  exclude_area_ids: [],
  exclude_label_ids: [],
};
const TRIGGER = { mode: 'template', template: '{{ state | float < 24 }}', clear_on_recover: true };
const SPEC = {
  id: 'spec1',
  name: 'Roborock: parts near the end of their life',
  description: '',
  enabled: true,
  preset_id: 'roborock_life_low',
  selection: SELECTION,
  trigger: TRIGGER,
  task_template: { name_template: '', notes_template: '', labels: [] },
  per_entity_overrides: {},
};
const PRESET = {
  id: 'roborock_life_low',
  name: 'Roborock: parts near the end of their life',
  description: '',
  icon: 'mdi:robot-vacuum',
  requires_integration: 'roborock',
  brand: 'Roborock',
  shape: 'life_low',
  limit_text: 'less than 24 hours left',
  default_spec: SPEC,
};
const TITLES = { 'component.sensor.title': 'Sensor', 'component.update.title': 'Update' };

const host = (over = {}) => ({
  _tasks: [
    { id: 't1', source: { declarative_companion: { spec_id: 'spec1' } } },
    { id: 't2', source: { declarative_companion: { spec_id: 'spec1' } } },
    { id: 't3', source: null },
  ],
  _declarativePresets: [PRESET],
  _hass: { localize: (key) => TITLES[key] ?? '' },
  ...over,
});

const render = (spec, p = host()) => {
  const el = document.createElement('div');
  el.innerHTML = declarativeRow(p, spec);
  return el;
};

const meta = (el) => [...el.querySelectorAll('.hk-decl-meta > span')].map((s) => s.textContent);

afterEach(() => setLanguage('en'));

describe('declarativeRow', () => {
  it('shows the integration logo, the shape badge and the meta line', () => {
    const el = render(SPEC);
    const img = el.querySelector('.hk-decl-tile img.hk-decl-logo');
    expect(img.getAttribute('src')).toBe('https://brands.home-assistant.io/roborock/icon.png');
    expect(img.dataset.domain).toBe('roborock');
    expect(img.dataset.fallbackIcon).toBe('mdi:robot-vacuum');
    const badge = el.querySelector('.hk-decl-shape');
    expect(badge.getAttribute('title')).toBe('Parts near the end of their life');
    expect(badge.querySelector('ha-icon').getAttribute('icon')).toBe('mdi:timer-sand-complete');
    expect(meta(el)).toEqual([
      'Roborock',
      'Sensor',
      'less than 24 hours left',
      '2 matched task(s)',
    ]);
    expect(el.querySelector('.hk-decl-custom')).toBeNull();
    expect(el.textContent).not.toContain('roborock_life_low');
  });

  it('gives each shape its own badge icon', () => {
    const icons = {
      percent_low: 'mdi:trending-down',
      life_low: 'mdi:timer-sand-complete',
      wear_high: 'mdi:counter',
      reading_low: 'mdi:arrow-down-bold',
      reading_high: 'mdi:arrow-up-bold',
      alert: 'mdi:alert-outline',
    };
    for (const [shape, icon] of Object.entries(icons)) {
      const el = render(SPEC, host({ _declarativePresets: [{ ...PRESET, shape }] }));
      expect(el.querySelector('.hk-decl-shape ha-icon').getAttribute('icon')).toBe(icon);
      expect(el.querySelector('.hk-decl-shape').getAttribute('title')).not.toMatch(/^declarative/);
    }
  });

  it('marks a custom companion and names its integration from Home Assistant', () => {
    const spec = {
      ...SPEC,
      preset_id: null,
      selection: { ...SELECTION, target_integration: 'zha', domain: 'binary_sensor' },
    };
    const p = host({
      _hass: { localize: (key) => ({ 'component.zha.title': 'Zigbee Home Automation' })[key] ?? '' },
    });
    const el = render(spec, p);
    expect(el.querySelector('.hk-decl-custom').textContent).toBe('Custom');
    expect(el.querySelector('.hk-decl-shape')).toBeNull();
    expect(el.querySelector('img.hk-decl-logo').dataset.fallbackIcon).toBe('mdi:puzzle-outline');
    // No title for the platform: the raw id stands in.
    expect(meta(el)).toEqual(['Zigbee Home Automation', 'binary_sensor', '2 matched task(s)']);
  });

  it('falls back to the domain when Home Assistant has no title or no localize', () => {
    const spec = { ...SPEC, preset_id: null, selection: { ...SELECTION, target_integration: 'my_hacs' } };
    expect(meta(render(spec, host({ _hass: undefined })))[0]).toBe('my_hacs');
    expect(meta(render(spec, host({ _hass: {} })))).toEqual(['my_hacs', 'sensor', '2 matched task(s)']);
  });

  it('shows the preset icon and "Any integration" when there is no target integration', () => {
    const spec = {
      ...SPEC,
      preset_id: 'firmware_update_available',
      selection: { ...SELECTION, target_integration: undefined, domain: 'update' },
    };
    const general = { ...PRESET, id: 'firmware_update_available', icon: 'mdi:update', brand: null, shape: null, limit_text: null, requires_integration: null };
    const el = render(spec, host({ _declarativePresets: [general], _tasks: [] }));
    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelector('ha-icon.hk-decl-logo').getAttribute('icon')).toBe('mdi:update');
    expect(meta(el)).toEqual(['Any integration', 'Update', '0 matched task(s)']);
  });

  it('shows the puzzle icon when there is neither an integration nor a preset', () => {
    const spec = { ...SPEC, preset_id: null, selection: { ...SELECTION, target_integration: '' } };
    const el = render(spec);
    expect(el.querySelector('ha-icon.hk-decl-logo').getAttribute('icon')).toBe('mdi:puzzle-outline');
  });

  it('escapes the name, the description and the domain', () => {
    const spec = {
      ...SPEC,
      preset_id: null,
      name: '<b>x</b>',
      description: '<i>y</i>',
      selection: { ...SELECTION, target_integration: '"><script>' },
    };
    const el = render(spec, host({ _hass: undefined }));
    expect(el.querySelector('b')).toBeNull();
    expect(el.querySelector('i')).toBeNull();
    expect(el.querySelector('script')).toBeNull();
    expect(el.querySelector('.hk-companion-name').textContent).toContain('<b>x</b>');
    expect(el.querySelector('.hk-companion-desc').textContent).toBe('<i>y</i>');
  });

  it('shows the meta line in the panel language', () => {
    setLanguage('de');
    const spec = { ...SPEC, preset_id: null, selection: { ...SELECTION, target_integration: '' } };
    const el = render(spec, host({ _declarativePresets: [] }));
    expect(meta(el)[0]).toBe('Beliebige Integration');
    expect(el.querySelector('.hk-decl-custom').textContent).toBe('Eigene');
  });
});

describe('the logo fallback', () => {
  const error = (img) => img.dispatchEvent(new Event('error'));

  it('tries the generic brand image, then the fallback', () => {
    const img = document.createElement('img');
    img.dataset.domain = 'zha';
    let fellBack = 0;
    wireBrandImage(img, () => (fellBack += 1));
    error(img);
    expect(img.src).toBe('https://brands.home-assistant.io/_/zha/icon.png');
    expect(img.dataset.retried).toBe('1');
    expect(fellBack).toBe(0);
    error(img);
    expect(fellBack).toBe(1);
  });

  it('falls back at once when the image has no domain', () => {
    const img = document.createElement('img');
    let fellBack = 0;
    wireBrandImage(img, () => (fellBack += 1));
    error(img);
    expect(fellBack).toBe(1);
  });

  it('puts the preset icon in place of a row logo that does not load', () => {
    const root = document.createElement('div');
    root.innerHTML = declarativeRow(host(), SPEC);
    wireDeclarativeSection(host(), root);
    const img = root.querySelector('img.hk-decl-logo');
    error(img);
    error(img);
    expect(root.querySelector('img.hk-decl-logo')).toBeNull();
    const icon = root.querySelector('ha-icon.hk-decl-logo');
    expect(icon.getAttribute('icon')).toBe('mdi:robot-vacuum');
    // The badge stays on the tile.
    expect(root.querySelector('.hk-decl-tile .hk-decl-shape')).not.toBeNull();
  });
});
