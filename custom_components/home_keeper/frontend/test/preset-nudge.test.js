import { describe, expect, it } from 'vitest';
import {
  MAX_IDS,
  ONE_STEP_MAX,
  addOutcome,
  cardPresets,
  dialogPresets,
  markDismissed,
  markShown,
  mergeNudgeState,
  newPresets,
  parseNudgeState,
  presetIdsWithCompanion,
  usablePresets,
} from '../src/preset-nudge.ts';

const preset = (id, matches) => ({
  id,
  name: id,
  description: '',
  icon: 'mdi:update',
  requires_integration: null,
  default_spec: {},
  matches,
});

const ids = (list) => list.map((p) => p.id);

describe('parseNudgeState', () => {
  it('reads the stored lists', () => {
    expect(parseNudgeState({ shown: ['a', 'b'], dismissed: ['b'] })).toEqual({
      shown: ['a', 'b'],
      dismissed: ['b'],
    });
  });

  it('reads anything that is not an object as empty', () => {
    for (const raw of [null, undefined, true, false, 0, 'a']) {
      expect(parseNudgeState(raw)).toEqual({ shown: [], dismissed: [] });
    }
  });

  it('keeps only non-empty strings, once each, in order', () => {
    expect(parseNudgeState({ shown: [1, 'a', '', 'a', null, 'b'], dismissed: 'x' })).toEqual({
      shown: ['a', 'b'],
      dismissed: [],
    });
  });

  it('reads a missing list as empty', () => {
    expect(parseNudgeState({ shown: ['a'] })).toEqual({ shown: ['a'], dismissed: [] });
    expect(parseNudgeState({})).toEqual({ shown: [], dismissed: [] });
  });

  it('stops at MAX_IDS ids, well above the catalog', () => {
    expect(MAX_IDS).toBe(1000);
    const many = Array.from({ length: MAX_IDS + 50 }, (_, i) => `p${i}`);
    const out = parseNudgeState({ shown: many, dismissed: [] });
    expect(out.shown).toHaveLength(MAX_IDS);
    expect(out.shown[MAX_IDS - 1]).toBe(`p${MAX_IDS - 1}`);
  });

  it('keeps an id hidden after every other preset of a large catalog', () => {
    const others = Array.from({ length: 150 }, (_, i) => `p${i}`);
    const out = parseNudgeState({ shown: [], dismissed: [...others, 'late'] });
    expect(out.dismissed).toHaveLength(151);
    expect(out.dismissed).toContain('late');
  });
});

describe('mergeNudgeState', () => {
  it('copies the read state when nothing is loaded yet', () => {
    const b = { shown: ['a'], dismissed: ['b'] };
    const out = mergeNudgeState(null, b);
    expect(out).toEqual(b);
    out.shown.push('z');
    out.dismissed.push('z');
    expect(b).toEqual({ shown: ['a'], dismissed: ['b'] });
  });

  it('keeps every id either copy holds, the first copy first', () => {
    expect(
      mergeNudgeState({ shown: ['a'], dismissed: ['c'] }, { shown: ['b', 'a'], dismissed: ['d'] }),
    ).toEqual({ shown: ['a', 'b'], dismissed: ['c', 'd'] });
  });
});

describe('markShown and markDismissed', () => {
  it('add to one list and leave the input as it was', () => {
    const state = { shown: ['a'], dismissed: ['x'] };
    expect(markShown(state, ['a', 'b'])).toEqual({ shown: ['a', 'b'], dismissed: ['x'] });
    expect(markDismissed(state, ['x', 'y'])).toEqual({ shown: ['a'], dismissed: ['x', 'y'] });
    expect(state).toEqual({ shown: ['a'], dismissed: ['x'] });
  });

  it('return new lists', () => {
    const state = { shown: ['a'], dismissed: ['x'] };
    const shown = markShown(state, []);
    const dismissed = markDismissed(state, []);
    expect(shown.dismissed).not.toBe(state.dismissed);
    expect(dismissed.shown).not.toBe(state.shown);
  });
});

describe('usablePresets', () => {
  it('keeps a preset that matches at least one entity, in catalog order', () => {
    const list = [preset('a', 1), preset('b', 0), preset('c', 500), preset('d', null), preset('e')];
    expect(ids(usablePresets(list, []))).toEqual(['a', 'c']);
  });

  it('drops a preset that already has a companion', () => {
    const list = [preset('a', 2), preset('b', 3)];
    const companions = [{ id: 'x', preset_id: 'a' }, { id: 'y', preset_id: null }];
    expect(ids(usablePresets(list, companions))).toEqual(['b']);
  });

  it('is empty before the presets load', () => {
    expect(usablePresets(null, [])).toEqual([]);
  });
});

describe('presetIdsWithCompanion', () => {
  it('names the presets a companion was made from', () => {
    const list = [preset('a', 1), preset('b', 0), preset('c', 2)];
    const companions = [{ id: 'x', preset_id: 'b' }, { id: 'y', preset_id: null }];
    expect(presetIdsWithCompanion(list, companions)).toEqual(['b']);
    expect(presetIdsWithCompanion(null, companions)).toEqual([]);
  });
});

describe('newPresets, cardPresets and dialogPresets', () => {
  const usable = [preset('a', 1), preset('b', 2)];

  it('a preset is new until it is shown or dismissed', () => {
    expect(ids(newPresets(usable, { shown: [], dismissed: [] }))).toEqual(['a', 'b']);
    expect(ids(newPresets(usable, { shown: ['a'], dismissed: ['b'] }))).toEqual([]);
    expect(ids(newPresets(usable, { shown: ['a'], dismissed: [] }))).toEqual(['b']);
  });

  it('the card lists only offered presets that are not dismissed', () => {
    expect(cardPresets(usable, { shown: [], dismissed: [] })).toEqual([]);
    expect(ids(cardPresets(usable, { shown: ['a', 'b'], dismissed: ['a'] }))).toEqual(['b']);
    expect(ids(cardPresets(usable, { shown: ['a', 'b'], dismissed: [] }))).toEqual(['a', 'b']);
  });

  it('the dialog opens for a preset it has not offered', () => {
    expect(ids(dialogPresets(usable, { shown: [], dismissed: [] }))).toEqual(['a', 'b']);
  });

  it('the dialog lists the presets it offered before, with the new one', () => {
    expect(ids(dialogPresets(usable, { shown: ['a'], dismissed: [] }))).toEqual(['a', 'b']);
  });

  it('the dialog stays closed when it offered every preset', () => {
    expect(dialogPresets(usable, { shown: ['a', 'b'], dismissed: [] })).toEqual([]);
  });

  it('a dismissed preset does not open the dialog and is not listed', () => {
    expect(dialogPresets(usable, { shown: ['a'], dismissed: ['b'] })).toEqual([]);
    expect(ids(dialogPresets(usable, { shown: [], dismissed: ['b'] }))).toEqual(['a']);
  });

  it('a preset over the one-step limit stays out of the dialog', () => {
    const big = [preset('a', ONE_STEP_MAX), preset('b', ONE_STEP_MAX + 1)];
    expect(ONE_STEP_MAX).toBe(50);
    expect(ids(dialogPresets(big, { shown: [], dismissed: [] }))).toEqual(['a']);
    // A new big preset alone opens nothing to choose from.
    expect(dialogPresets([preset('b', 51)], { shown: [], dismissed: [] })).toEqual([]);
  });
});

describe('addOutcome', () => {
  it('all added', () => {
    expect(addOutcome([{ ok: true }, { ok: true }])).toEqual({
      kind: 'all',
      added: 2,
      total: 2,
      error: '',
    });
  });

  it('some added keeps the first error', () => {
    expect(
      addOutcome([{ ok: false, error: 'first' }, { ok: true }, { ok: false, error: 'second' }]),
    ).toEqual({ kind: 'some', added: 1, total: 3, error: 'first' });
  });

  it('none added', () => {
    expect(addOutcome([{ ok: false, error: 'boom' }])).toEqual({
      kind: 'none',
      added: 0,
      total: 1,
      error: 'boom',
    });
  });

  it('a failure without a message reads as an empty error', () => {
    expect(addOutcome([{ ok: false }]).error).toBe('');
  });

  it('nothing to add counts as all', () => {
    expect(addOutcome([])).toEqual({ kind: 'all', added: 0, total: 0, error: '' });
  });
});
