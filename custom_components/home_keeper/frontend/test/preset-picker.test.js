import { describe, expect, it } from 'vitest';
import {
  groupPresets,
  presetIsMine,
  presetMatches,
  presetTaskNames,
} from '../src/preset-picker.ts';

/**
 * The preset picker's grouping and search: the presets that match entities first, the
 * general presets next, and the rest hidden until Show all or a search.
 */

const preset = (id, over = {}) => ({
  id,
  name: over.name ?? id,
  description: over.description ?? '',
  icon: 'mdi:x',
  requires_integration: over.requires ?? null,
  group: over.group ?? 'general',
  ...('matches' in over ? { matches: over.matches } : {}),
  default_spec: {
    task_template: { name_template: '', notes_template: '', labels: [], task_names: over.tasks },
  },
});

const PULSE = preset('device_pulse', { name: 'Device Pulse', requires: 'device_pulse' });
const FIRMWARE = preset('firmware', { name: 'Firmware update available' });
const ROBOROCK = preset('roborock_life_low', {
  name: 'Roborock: parts near the end of their life',
  requires: 'roborock',
  group: 'integration',
  tasks: { filter_time_left: 'Replace the filter', main_brush_time_left: 'Replace the main brush' },
});
const BROTHER = preset('brother_percent_low', {
  name: 'Brother: parts and supplies running low',
  requires: 'brother',
  group: 'integration',
  tasks: { black: 'Replace the toner', cyan: 'Replace the toner' },
});
const ECOVACS = preset('ecovacs_percent_low', {
  name: 'Ecovacs: parts and supplies running low',
  requires: 'ecovacs',
  group: 'integration',
});
// Out of order on purpose: each group is sorted by name.
const ALL = [PULSE, FIRMWARE, ECOVACS, ROBOROCK, BROTHER];
const ZEBRA = preset('zebra', { name: 'Zebra: service alerts', requires: 'zebra', group: 'integration' });

describe('presetTaskNames', () => {
  it('lists each task name once, in order', () => {
    expect(presetTaskNames(BROTHER)).toEqual(['Replace the toner']);
    expect(presetTaskNames(ROBOROCK)).toEqual(['Replace the filter', 'Replace the main brush']);
  });

  it('is empty for a preset with no task names', () => {
    expect(presetTaskNames(FIRMWARE)).toEqual([]);
  });
});

describe('presetMatches', () => {
  it('matches the name, the description, the domain and a task name, in any case', () => {
    expect(presetMatches(ROBOROCK, 'ROBOROCK')).toBe(true);
    expect(presetMatches(ROBOROCK, 'main brush')).toBe(true);
    expect(presetMatches(preset('x', { description: 'Salt is low' }), 'salt')).toBe(true);
    expect(presetMatches(PULSE, 'device_pulse')).toBe(true);
  });

  it('matches everything for an empty or blank query, and nothing it does not contain', () => {
    expect(presetMatches(FIRMWARE, '')).toBe(true);
    expect(presetMatches(FIRMWARE, '   ')).toBe(true);
    expect(presetMatches(FIRMWARE, 'toner')).toBe(false);
  });

  it('does not match across the end of one field and the start of the next', () => {
    const p = preset('x', { name: 'Salt', description: 'Low level' });
    expect(presetMatches(p, 'saltlow')).toBe(false);
    expect(presetMatches(p, 'salt')).toBe(true);
  });
});

describe('groupPresets', () => {
  const installed = new Set(['roborock', 'brother']);

  it('puts installed integrations first, sorted, then the general presets, and hides the rest', () => {
    const groups = groupPresets(ALL, installed, '', false);
    expect(groups.mine.map((p) => p.id)).toEqual(['brother_percent_low', 'roborock_life_low']);
    expect(groups.general.map((p) => p.id)).toEqual(['device_pulse', 'firmware']);
    expect(groups.other).toEqual([]);
    expect(groups.hidden).toBe(1);
  });

  it('shows the other integrations with Show all, sorted by name', () => {
    const groups = groupPresets([ZEBRA, ...ALL], installed, '', true);
    expect(groups.other.map((p) => p.id)).toEqual(['ecovacs_percent_low', 'zebra']);
    expect(groups.hidden).toBe(0);
  });

  it('searches every group, the hidden one included', () => {
    const groups = groupPresets(ALL, installed, 'running low', false);
    expect(groups.mine.map((p) => p.id)).toEqual(['brother_percent_low']);
    expect(groups.general).toEqual([]);
    expect(groups.other.map((p) => p.id)).toEqual(['ecovacs_percent_low']);
    expect(groups.hidden).toBe(0);
  });

  it('does not count a blank search as a search', () => {
    const groups = groupPresets(ALL, installed, '   ', false);
    expect(groups.other).toEqual([]);
    expect(groups.hidden).toBe(1);
  });

  it('treats a preset from an older backend with no group as general', () => {
    const legacy = { ...FIRMWARE, group: undefined };
    expect(groupPresets([legacy], installed, '', false).general).toEqual([legacy]);
  });

  it('gives empty groups for no presets', () => {
    expect(groupPresets([], installed, '', false)).toEqual({
      mine: [],
      general: [],
      other: [],
      hidden: 0,
    });
  });
});

describe('presetIsMine', () => {
  const installed = new Set(['tuya']);
  const tuya = (matches) =>
    preset('tuya_percent_low', { requires: 'tuya', group: 'integration', matches });

  it('follows the entity count when the backend sends one', () => {
    // A Tuya light: the integration is installed, but no entity has a vacuum key.
    expect(presetIsMine(tuya(0), installed)).toBe(false);
    expect(presetIsMine(tuya(1), installed)).toBe(true);
    expect(presetIsMine(tuya(3), new Set())).toBe(true);
  });

  it('falls back to the installed integration when there is no count', () => {
    expect(presetIsMine(tuya(undefined), installed)).toBe(true);
    expect(presetIsMine(tuya(null), installed)).toBe(true);
    expect(presetIsMine(tuya(null), new Set(['roborock']))).toBe(false);
    const noCount = preset('tuya_alert', { requires: 'tuya', group: 'integration' });
    expect(presetIsMine(noCount, installed)).toBe(true);
    expect(presetIsMine(noCount, new Set())).toBe(false);
  });
});

describe('groupPresets with entity counts', () => {
  it('moves an installed integration with no matching entity to the other group', () => {
    const vacuum = preset('tuya_percent_low', {
      name: 'Tuya: parts and supplies running low',
      requires: 'tuya',
      group: 'integration',
      matches: 0,
    });
    const printer = preset('brother_percent_low', {
      name: 'Brother: parts and supplies running low',
      requires: 'brother',
      group: 'integration',
      matches: 4,
    });
    const groups = groupPresets([vacuum, printer, FIRMWARE], new Set(['tuya']), '', false);
    expect(groups.mine.map((p) => p.id)).toEqual(['brother_percent_low']);
    expect(groups.other).toEqual([]);
    expect(groups.hidden).toBe(1);
    const all = groupPresets([vacuum, printer], new Set(['tuya']), '', true);
    expect(all.other.map((p) => p.id)).toEqual(['tuya_percent_low']);
  });
});
