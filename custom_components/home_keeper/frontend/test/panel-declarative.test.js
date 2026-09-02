import { describe, expect, it } from 'vitest';
import { emptyDeclarativeCompanion, triggerForMode } from '../src/panel-declarative.ts';

/**
 * Changing a declarative companion's trigger mode rewrites its trigger block.
 *
 * `models.normalize_sensor` does not ignore a key that belongs to another mode — it
 * raises on it. A recipe seeded from the Device Pulse preset carries a `threshold`
 * trigger (`comparison`, `value`); switching the dropdown to *state* kept both, and
 * the save came back "sensor.comparison is not valid for a state-mode sensor task"
 * (issues #230 / #231). `triggerForMode` is the rule the form applies on every mode
 * change, kept pure so it can be pinned here rather than through the dialog.
 *
 * The backend contract each case mirrors, from `normalize_sensor`:
 *   usage         target / baseline / unit / also_every / combinator (+ attribute)
 *   threshold     comparison / value / for_seconds / clear_on_recover (+ attribute)
 *   state         state / for_seconds / clear_on_recover (+ attribute)
 *   availability  for_seconds / clear_on_recover
 */

/** The trigger the Device Pulse preset seeds, verbatim from `declarative_presets.py`. */
const DEVICE_PULSE_TRIGGER = {
  mode: 'threshold',
  comparison: '>',
  value: 0,
  for_seconds: 3600,
  clear_on_recover: true,
};

describe('triggerForMode', () => {
  it('drops comparison and value when threshold becomes state', () => {
    const next = triggerForMode(DEVICE_PULSE_TRIGGER, 'state');

    expect(next).not.toHaveProperty('comparison');
    expect(next).not.toHaveProperty('value');
    expect(next.mode).toBe('state');
    // The hold and the auto-clear are shared by both modes, so they survive.
    expect(next.for_seconds).toBe(3600);
    expect(next.clear_on_recover).toBe(true);
  });

  it('leaves the source trigger alone', () => {
    triggerForMode(DEVICE_PULSE_TRIGGER, 'state');

    expect(DEVICE_PULSE_TRIGGER).toEqual({
      mode: 'threshold',
      comparison: '>',
      value: 0,
      for_seconds: 3600,
      clear_on_recover: true,
    });
  });

  it('seeds the state a state trigger needs, since the form shows one', () => {
    // The form's State box reads "on" whether or not the draft has the key. Without
    // the seed the two disagree and the save fails as "sensor.state is required".
    expect(triggerForMode(DEVICE_PULSE_TRIGGER, 'state').state).toBe('on');
  });

  it('keeps a state already typed rather than re-seeding it', () => {
    const next = triggerForMode({ mode: 'state', state: 'docked' }, 'state');

    expect(next.state).toBe('docked');
  });

  it('drops state when state becomes usage', () => {
    const next = triggerForMode(
      { mode: 'state', state: 'on', for_seconds: 60, clear_on_recover: true },
      'usage',
    );

    expect(next).not.toHaveProperty('state');
    expect(next.mode).toBe('usage');
    // A meter has no condition to hold or to recover from.
    expect(next).not.toHaveProperty('for_seconds');
    expect(next).not.toHaveProperty('clear_on_recover');
  });

  it('drops the usage-only keys when usage becomes threshold', () => {
    const next = triggerForMode(
      {
        mode: 'usage',
        target: 300,
        baseline: 120,
        unit: 'h',
        also_every: { interval: 6, unit: 'months' },
        combinator: 'any',
      },
      'threshold',
    );

    for (const key of ['target', 'baseline', 'unit', 'also_every', 'combinator']) {
      expect(next, `${key} is rejected by a threshold binding`).not.toHaveProperty(key);
    }
    expect(next.mode).toBe('threshold');
    expect(next.comparison).toBe('>=');
  });

  it('drops attribute when the mode becomes availability', () => {
    const next = triggerForMode(
      { mode: 'state', state: 'on', attribute: 'battery_level', clear_on_recover: true },
      'availability',
    );

    // The form offers no attribute box in this mode, so a carried-over one would be
    // a setting nobody can see or clear.
    expect(next).not.toHaveProperty('attribute');
    expect(next).not.toHaveProperty('state');
    expect(next.mode).toBe('availability');
    expect(next.clear_on_recover).toBe(true);
  });

  it('carries an attribute between the three modes that offer one', () => {
    const trigger = { mode: 'state', state: 'on', attribute: 'battery_level' };

    expect(triggerForMode(trigger, 'threshold').attribute).toBe('battery_level');
    expect(triggerForMode(trigger, 'usage').attribute).toBe('battery_level');
  });

  it('keeps only the mode for an unknown mode', () => {
    // Nothing in the panel can produce this; the rule is an allowlist so a mode it
    // has never heard of cannot smuggle another mode's keys through.
    const next = triggerForMode({ mode: 'state', state: 'on', value: 3 }, 'nonsense');

    expect(next).toEqual({ mode: 'nonsense' });
  });
});

describe('emptyDeclarativeCompanion', () => {
  it('produces a state-mode draft with no id', () => {
    const draft = emptyDeclarativeCompanion();

    expect(draft.id).toBe('');
    expect(draft.enabled).toBe(true);
    expect(draft.preset_id).toBeNull();
    expect(draft.trigger).toEqual({ mode: 'state', state: 'on', clear_on_recover: true });
  });

  it('builds its trigger by the same rule a mode change applies', () => {
    // One rule, so a blank draft and a switched one can never carry different keys.
    expect(emptyDeclarativeCompanion().trigger).toEqual(triggerForMode({}, 'state'));
  });

  it('returns a fresh object each call', () => {
    const first = emptyDeclarativeCompanion();
    first.selection.area_ids.push('area_kitchen');

    expect(emptyDeclarativeCompanion().selection.area_ids).toEqual([]);
  });
});
