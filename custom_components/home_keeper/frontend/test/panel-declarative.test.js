import { describe, expect, it } from 'vitest';
import {
  declarativeOverlap,
  emptyDeclarativeCompanion,
  triggerForMode,
} from '../src/panel-declarative.ts';

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

  it('seeds the name template every bundled preset uses', () => {
    // `{{ friendly_name }}` alone repeats the device name Home Assistant prefixes:
    // "Replace Roborock S7 Main brush time left", and an entity id to match.
    expect(emptyDeclarativeCompanion().task_template.name_template).toBe(
      '{{ device_name or friendly_name }}',
    );
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

/**
 * Two recipes can cover the same entities, and each one materializes its own task.
 * The same entity then gets two identical tasks, and the task list says nothing about
 * why. Add the same recipe twice and every task is duplicated.
 *
 * `declarativeOverlap` is what the add/edit dialog's preview warns from. It reads the
 * tasks and recipes the panel already holds, so no backend call is added: a
 * materialized task carries its recipe id in `source.declarative_companion.spec_id`
 * and the entity it watches in `sensor.entity_id`.
 */
describe('declarativeOverlap', () => {
  /** A task materialized by *specId* for *entityId*, as the reconciler builds it. */
  const managed = (specId, entityId) => ({
    id: `${specId}:${entityId}`,
    name: entityId,
    recurrence_type: 'sensor',
    source: { declarative_companion: { spec_id: specId } },
    sensor: { entity_id: entityId, mode: 'state', state: 'on' },
  });
  const BATTERY = 'binary_sensor.remote_battery';
  const LOCK = 'binary_sensor.front_door_battery';
  const SPECS = [
    { id: 'spec-a', name: 'Low battery' },
    { id: 'spec-b', name: 'Batteries again' },
  ];

  it('names the recipe that already covers the matches', () => {
    const overlap = declarativeOverlap(
      [{ entity_id: BATTERY }, { entity_id: LOCK }],
      [managed('spec-a', BATTERY), managed('spec-a', LOCK)],
      SPECS,
      '',
    );

    expect(overlap).toEqual({ name: 'Low battery', count: 2 });
  });

  it('counts only the entities this draft matches', () => {
    // The other recipe is wider than the draft. Only the shared entity counts.
    const overlap = declarativeOverlap(
      [{ entity_id: BATTERY }],
      [managed('spec-a', BATTERY), managed('spec-a', LOCK)],
      SPECS,
      '',
    );

    expect(overlap).toEqual({ name: 'Low battery', count: 1 });
  });

  it('reports nothing when no other recipe covers a match', () => {
    const elsewhere = [managed('spec-a', LOCK)];
    const overlap = declarativeOverlap([{ entity_id: BATTERY }], elsewhere, SPECS, '');

    expect(overlap).toBeNull();
  });

  it('reports nothing when the recipe matches no entity', () => {
    expect(declarativeOverlap([], [managed('spec-a', BATTERY)], SPECS, '')).toBeNull();
  });

  it('ignores a task that no recipe made', () => {
    // A hand-made sensor task on the same entity is the user's own. It is not a
    // duplicate of anything, so the dialog must stay quiet about it.
    const byHand = { id: 't1', name: 'Replace it', sensor: { entity_id: BATTERY } };

    expect(declarativeOverlap([{ entity_id: BATTERY }], [byHand], SPECS, '')).toBeNull();
  });

  it('ignores a task with no sensor binding', () => {
    const noSensor = {
      id: 't2',
      name: 'Odd one',
      source: { declarative_companion: { spec_id: 'spec-a' } },
    };

    expect(declarativeOverlap([{ entity_id: BATTERY }], [noSensor], SPECS, '')).toBeNull();
  });

  it('does not count the edited recipe against itself', () => {
    // Editing a recipe re-renders the preview over the tasks that recipe already
    // made. Those are the tasks the save rebuilds, not a second copy of them.
    const overlap = declarativeOverlap(
      [{ entity_id: BATTERY }],
      [managed('spec-a', BATTERY)],
      SPECS,
      'spec-a',
    );

    expect(overlap).toBeNull();
  });

  it('names the recipe with the most overlap', () => {
    const overlap = declarativeOverlap(
      [{ entity_id: BATTERY }, { entity_id: LOCK }],
      [managed('spec-a', BATTERY), managed('spec-b', BATTERY), managed('spec-b', LOCK)],
      SPECS,
      '',
    );

    expect(overlap).toEqual({ name: 'Batteries again', count: 2 });
  });

  it('counts an entity once even if the recipe has two tasks for it', () => {
    const overlap = declarativeOverlap(
      [{ entity_id: BATTERY }],
      [managed('spec-a', BATTERY), { ...managed('spec-a', BATTERY), id: 'copy' }],
      SPECS,
      '',
    );

    expect(overlap).toEqual({ name: 'Low battery', count: 1 });
  });

  it('falls back to the recipe id when the recipe is gone', () => {
    // A task outlives its recipe only between a delete and the reconcile that
    // removes it, but an id says more than an empty name.
    const overlap = declarativeOverlap(
      [{ entity_id: BATTERY }],
      [managed('spec-z', BATTERY)],
      SPECS,
      '',
    );

    expect(overlap).toEqual({ name: 'spec-z', count: 1 });
  });
});
