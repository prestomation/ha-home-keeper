import { describe, expect, it } from 'vitest';
import {
  PRESET_SECTIONS,
  changedSections,
  companionOrigin,
  limitProgress,
  presetFor,
  resetToPreset,
} from '../src/preset-summary.ts';

/** The ZHA wear-counter preset's default spec, in the shape the backend sends. */
const SPEC = {
  name: 'Zigbee (ZHA): wear counters',
  description: '',
  enabled: true,
  preset_id: 'zha_wear_high',
  selection: {
    target_integration: 'zha',
    domain: 'sensor',
    translation_keys: ['filter_run_time'],
    area_ids: [],
    label_ids: [],
    exclude_entity_ids: [],
    exclude_device_ids: [],
    exclude_area_ids: [],
    exclude_label_ids: [],
  },
  trigger: { mode: 'template', template: '{{ state | float > 4320 }}', clear_on_recover: true },
  task_template: {
    name_template: '{{ task_name }}: {{ device_name or friendly_name }}',
    notes_template: '{{ friendly_name }}: {{ state }}',
    labels: [],
    task_names: { filter_run_time: 'Replace the filter' },
  },
  per_entity_overrides: {},
};

const draftOf = (spec = SPEC) => ({ id: '', ...JSON.parse(JSON.stringify(spec)) });

describe('presetFor', () => {
  const presets = [{ id: 'a' }, { id: 'zha_wear_high' }];

  it('finds the preset the draft names', () => {
    expect(presetFor({ preset_id: 'zha_wear_high' }, presets)).toBe(presets[1]);
  });

  it('finds nothing for a draft with no preset', () => {
    expect(presetFor({ preset_id: null }, presets)).toBeNull();
    expect(presetFor({ preset_id: '' }, presets)).toBeNull();
  });

  it('finds nothing for an unknown preset or before the presets are loaded', () => {
    expect(presetFor({ preset_id: 'gone' }, presets)).toBeNull();
    expect(presetFor({ preset_id: 'zha_wear_high' }, null)).toBeNull();
  });
});

describe('changedSections', () => {
  it('lists the sections in form order', () => {
    expect(PRESET_SECTIONS).toEqual(['selection', 'trigger', 'task_template']);
  });

  it('reports nothing for a draft seeded from the preset', () => {
    expect(changedSections(draftOf(), SPEC)).toEqual([]);
  });

  it('does not count a name, a description or enabled', () => {
    const draft = draftOf();
    draft.name = 'My purifiers';
    draft.description = 'Bedroom only';
    draft.enabled = false;
    expect(changedSections(draft, SPEC)).toEqual([]);
  });

  it('does not count the exclusions, which are the user’s own', () => {
    const draft = draftOf();
    draft.selection.exclude_entity_ids = ['sensor.hall_filter_run_time'];
    draft.selection.exclude_area_ids = ['garage'];
    expect(changedSections(draft, SPEC)).toEqual([]);
  });

  it('reads an empty box the form cleared as no change', () => {
    // The form writes `undefined` for a cleared box, the backend stores `null` or
    // `[]`; none of them says anything.
    const draft = draftOf();
    draft.selection.device_class = undefined;
    draft.selection.entity_regex = '';
    draft.selection.device_ids = [];
    draft.trigger.attribute = null;
    draft.task_template.category = undefined;
    expect(changedSections(draft, SPEC)).toEqual([]);
  });

  it('reads an empty table as no table', () => {
    const spec = JSON.parse(JSON.stringify(SPEC));
    delete spec.task_template.task_names;
    const draft = draftOf(spec);
    draft.task_template.task_names = {};
    expect(changedSections(draft, spec)).toEqual([]);
  });

  it('counts a blank item in a list as a change', () => {
    const draft = draftOf();
    draft.selection.translation_keys = ['filter_run_time', ''];
    expect(changedSections(draft, SPEC)).toEqual(['selection']);
  });

  it('reads the hold of 0 the form writes as no hold', () => {
    const draft = draftOf();
    draft.trigger.for_seconds = 0;
    expect(changedSections(draft, SPEC)).toEqual([]);
    draft.trigger.for_seconds = 60;
    expect(changedSections(draft, SPEC)).toEqual(['trigger']);
  });

  it('does not care about key order', () => {
    const draft = draftOf();
    draft.trigger = { clear_on_recover: true, template: SPEC.trigger.template, mode: 'template' };
    expect(changedSections(draft, SPEC)).toEqual([]);
  });

  it('reports each changed section', () => {
    const draft = draftOf();
    draft.selection.area_ids = ['bedroom'];
    expect(changedSections(draft, SPEC)).toEqual(['selection']);
    draft.trigger.template = '{{ state | float > 2000 }}';
    expect(changedSections(draft, SPEC)).toEqual(['selection', 'trigger']);
    draft.task_template.task_names = { filter_run_time: 'Swap the filter' };
    expect(changedSections(draft, SPEC)).toEqual(['selection', 'trigger', 'task_template']);
  });

  it('reports a changed key list, and a changed task label', () => {
    const keys = draftOf();
    keys.selection.translation_keys = ['filter_run_time', 'filter_life'];
    expect(changedSections(keys, SPEC)).toEqual(['selection']);
    const labels = draftOf();
    labels.task_template.labels = ['filters'];
    expect(changedSections(labels, SPEC)).toEqual(['task_template']);
  });

  it('reports a trigger that lost auto-clear', () => {
    const draft = draftOf();
    draft.trigger.clear_on_recover = false;
    expect(changedSections(draft, SPEC)).toEqual(['trigger']);
  });
});

describe('resetToPreset', () => {
  it('puts the preset sections back and keeps the rest', () => {
    const draft = draftOf();
    draft.id = 'spec-1';
    draft.name = 'My purifiers';
    draft.enabled = false;
    draft.selection.area_ids = ['bedroom'];
    draft.selection.exclude_entity_ids = ['sensor.hall_filter_run_time'];
    draft.trigger = { mode: 'state', state: 'on' };
    draft.task_template.name_template = 'Filter';

    const next = resetToPreset(draft, SPEC);

    expect(next.id).toBe('spec-1');
    expect(next.name).toBe('My purifiers');
    expect(next.enabled).toBe(false);
    expect(next.selection.exclude_entity_ids).toEqual(['sensor.hall_filter_run_time']);
    expect(next.selection.area_ids).toEqual([]);
    expect(next.trigger).toEqual(SPEC.trigger);
    expect(next.task_template).toEqual(SPEC.task_template);
    expect(changedSections(next, SPEC)).toEqual([]);
  });

  it('gives every exclusion list a value, even one the draft lacks', () => {
    const draft = draftOf();
    delete draft.selection.exclude_label_ids;
    expect(resetToPreset(draft, SPEC).selection.exclude_label_ids).toEqual([]);
  });

  it('copies the preset, so an edit after the reset leaves the preset alone', () => {
    const next = resetToPreset(draftOf(), SPEC);
    next.trigger.template = 'changed';
    next.selection.translation_keys.push('x');
    next.task_template.task_names.filter_run_time = 'x';
    expect(SPEC.trigger.template).toBe('{{ state | float > 4320 }}');
    expect(SPEC.selection.translation_keys).toEqual(['filter_run_time']);
    expect(SPEC.task_template.task_names.filter_run_time).toBe('Replace the filter');
  });

  it('leaves the draft it was given alone', () => {
    const draft = draftOf();
    draft.trigger.template = 'mine';
    resetToPreset(draft, SPEC);
    expect(draft.trigger.template).toBe('mine');
  });
});

describe('limitProgress', () => {
  const hours = { kind: 'hours', value: 4320, above: true };

  it('converts a reading in minutes to hours', () => {
    // ZHA reports the filter run time in minutes: 129600 min is 2160 h, half of 4320.
    expect(limitProgress('129600', 'min', hours)).toBe(0.5);
  });

  it('reads a time in hours or days as the trigger does', () => {
    expect(limitProgress('1080', 'h', hours)).toBe(0.25);
    expect(limitProgress('90', 'days', hours)).toBe(0.5);
  });

  it.each([
    ['ms', 3600000, 1],
    ['s', 3600, 1],
    ['sec', 3600, 1],
    ['seconds', 3600, 1],
    ['min', 60, 1],
    ['mins', 60, 1],
    ['minutes', 60, 1],
    ['h', 1, 1],
    ['hr', 1, 1],
    ['hrs', 1, 1],
    ['hours', 1, 1],
    ['d', 1, 24],
    ['day', 1, 24],
    ['days', 1, 24],
    ['w', 1, 168],
    ['week', 1, 168],
    ['weeks', 1, 168],
  ])('reads a reading in %s as hours', (unit, reading, hours) => {
    // *reading* in *unit* is *hours* hours, a quarter of a limit of 4 times that.
    const limit = { kind: 'hours', value: hours * 4, above: true };
    expect(limitProgress(String(reading), unit, limit)).toBeCloseTo(0.25, 12);
  });

  it('reads a reading with an unknown unit as it is', () => {
    expect(limitProgress('15', 'washes', { kind: 'hours', value: 30, above: true })).toBe(0.5);
    expect(limitProgress('15', null, { kind: 'hours', value: 30, above: true })).toBe(0.5);
  });

  it('never converts a limit that is not a time', () => {
    expect(limitProgress('60', 'min', { kind: 'number', value: 120, above: true })).toBe(0.5);
  });

  it('stays between 0 and 1', () => {
    expect(limitProgress('9000', 'h', hours)).toBe(1);
    expect(limitProgress('-5', 'h', hours)).toBe(0);
    expect(limitProgress('4320', 'h', hours)).toBe(1);
  });

  it('draws no bar for a limit the reading must fall below', () => {
    expect(limitProgress('5', '%', { kind: 'percent', value: 10, above: false })).toBeNull();
  });

  it('draws no bar without a limit, or with one of 0', () => {
    expect(limitProgress('5', 'h', null)).toBeNull();
    expect(limitProgress('5', 'h', undefined)).toBeNull();
    expect(limitProgress('5', 'h', { kind: 'number', value: 0, above: true })).toBeNull();
  });

  it('draws no bar for a reading that is not a number', () => {
    expect(limitProgress('unavailable', 'h', hours)).toBeNull();
    expect(limitProgress('', 'h', hours)).toBeNull();
    expect(limitProgress('  ', 'h', hours)).toBeNull();
    expect(limitProgress(null, 'h', hours)).toBeNull();
    expect(limitProgress(undefined, 'h', hours)).toBeNull();
  });
});

describe('companionOrigin', () => {
  const PRESET = {
    id: 'zha_wear_high',
    icon: 'mdi:air-filter',
    requires_integration: 'zha',
    brand: 'Zigbee (ZHA)',
    shape: 'wear_high',
    limit_text: 'above 180 days',
    default_spec: SPEC,
  };
  const GENERAL = {
    id: 'firmware_update_available',
    icon: 'mdi:update',
    requires_integration: null,
    brand: null,
    shape: null,
    limit_text: null,
    default_spec: { ...SPEC, preset_id: 'firmware_update_available' },
  };
  const PRESETS = [GENERAL, PRESET];

  it('says the brand, shape, platform, limit and icon of a companion from a preset', () => {
    expect(companionOrigin(draftOf(), PRESETS)).toEqual({
      domain: 'zha',
      brand: 'Zigbee (ZHA)',
      shape: 'wear_high',
      platform: 'sensor',
      limitText: 'above 180 days',
      icon: 'mdi:air-filter',
      custom: false,
    });
  });

  it('keeps the limit while the trigger only differs by empty members or a hold of 0', () => {
    const draft = draftOf();
    draft.trigger = { ...draft.trigger, for_seconds: 0, attribute: '' };
    expect(companionOrigin(draft, PRESETS).limitText).toBe('above 180 days');
  });

  it('drops the limit when the user changed the trigger', () => {
    const draft = draftOf();
    draft.trigger = { ...draft.trigger, template: '{{ state | float > 100 }}' };
    const origin = companionOrigin(draft, PRESETS);
    expect(origin.limitText).toBeNull();
    // The rest still comes from the preset.
    expect([origin.brand, origin.shape, origin.custom]).toEqual([
      'Zigbee (ZHA)',
      'wear_high',
      false,
    ]);
  });

  it('gives a custom companion the brand of a preset for the same integration', () => {
    const draft = { ...draftOf(), preset_id: null };
    expect(companionOrigin(draft, PRESETS)).toEqual({
      domain: 'zha',
      brand: 'Zigbee (ZHA)',
      shape: null,
      platform: 'sensor',
      limitText: null,
      icon: null,
      custom: true,
    });
  });

  it('gives no brand when no preset is for the integration', () => {
    const draft = draftOf();
    draft.preset_id = null;
    draft.selection = { ...draft.selection, target_integration: 'my_custom' };
    const origin = companionOrigin(draft, PRESETS);
    expect([origin.domain, origin.brand]).toEqual(['my_custom', null]);
  });

  it('gives no domain to a companion with no target integration', () => {
    const draft = draftOf(GENERAL.default_spec);
    draft.selection = { ...draft.selection, target_integration: '', domain: 'update' };
    expect(companionOrigin(draft, PRESETS)).toEqual({
      domain: null,
      brand: null,
      shape: null,
      platform: 'update',
      limitText: null,
      icon: 'mdi:update',
      custom: false,
    });
  });

  it('keeps the logo of a preset the catalog no longer has', () => {
    const draft = { ...draftOf(), preset_id: 'zha_gone' };
    const origin = companionOrigin(draft, [GENERAL]);
    expect(origin).toEqual({
      domain: 'zha',
      brand: null,
      shape: null,
      platform: 'sensor',
      limitText: null,
      icon: null,
      custom: false,
    });
  });

  it('copes when the preset list did not load', () => {
    const origin = companionOrigin(draftOf(), null);
    expect([origin.domain, origin.brand, origin.limitText, origin.custom]).toEqual([
      'zha',
      null,
      null,
      false,
    ]);
  });

  it('copes with an older backend that sends no brand, shape or limit text', () => {
    const old = { id: PRESET.id, icon: PRESET.icon, requires_integration: 'zha', default_spec: SPEC };
    const origin = companionOrigin(draftOf(), [old]);
    expect([origin.brand, origin.shape, origin.limitText, origin.icon]).toEqual([
      null,
      null,
      null,
      'mdi:air-filter',
    ]);
  });

  it('skips a same-integration preset with no brand when it looks for one', () => {
    const noBrand = { ...PRESET, id: 'zha_other', brand: null };
    const draft = { ...draftOf(), preset_id: null };
    expect(companionOrigin(draft, [noBrand, PRESET]).brand).toBe('Zigbee (ZHA)');
    expect(companionOrigin(draft, [noBrand]).brand).toBeNull();
  });
});
