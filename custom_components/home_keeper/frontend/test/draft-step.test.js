import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { INITIAL_DRAFT, draftStep } from '../src/draft-step.ts';

describe('draftStep', () => {
  it('starts at draft 0 with no verdict', () => {
    expect(INITIAL_DRAFT).toEqual({ current: 0, verdict: 'none' });
  });

  it('numbers a new draft one higher and clears the verdict', () => {
    const answered = draftStep(INITIAL_DRAFT, { type: 'answer', draftId: 0 });
    expect(answered.verdict).toBe('fresh');
    expect(draftStep(answered, { type: 'replace' })).toEqual({ current: 1, verdict: 'none' });
  });

  it('accepts an answer for the open draft and keeps the number', () => {
    const open = draftStep(INITIAL_DRAFT, { type: 'replace' });
    expect(draftStep(open, { type: 'answer', draftId: 1 })).toEqual({
      current: 1,
      verdict: 'fresh',
    });
  });

  it('marks an answer for an older draft as stale and keeps the number', () => {
    let state = draftStep(INITIAL_DRAFT, { type: 'replace' }); // draft 1
    state = draftStep(state, { type: 'replace' }); // close
    state = draftStep(state, { type: 'replace' }); // draft 3
    expect(draftStep(state, { type: 'answer', draftId: 1 })).toEqual({
      current: 3,
      verdict: 'stale',
    });
  });

  it('marks an answer for a later number as stale', () => {
    expect(draftStep(INITIAL_DRAFT, { type: 'answer', draftId: 5 }).verdict).toBe('stale');
  });

  it('does not change the input state', () => {
    const state = { current: 2, verdict: 'none' };
    draftStep(state, { type: 'replace' });
    draftStep(state, { type: 'answer', draftId: 1 });
    expect(state).toEqual({ current: 2, verdict: 'none' });
  });
});

/*
 * Model test. The model gives each form draft its own identity and remembers which
 * draft each save came from (`pending`). A driver does what the panel does: it moves
 * the state with `draftStep`, sends the draft number with each save, and closes the
 * form only on a fresh answer. Answers can come in any order.
 */
describe('draftStep model', () => {
  class OpenNew {
    check() {
      return true;
    }
    run(m, r) {
      m.open = ++m.made;
      r.state = draftStep(r.state, { type: 'replace' });
    }
    toString() {
      return 'OpenNew';
    }
  }
  class Save {
    check(m) {
      return m.open !== null;
    }
    run(m, r) {
      m.pending.push({ draft: m.open, draftId: r.state.current });
    }
    toString() {
      return 'Save';
    }
  }
  class Escape {
    check(m) {
      return m.open !== null;
    }
    run(m, r) {
      m.open = null;
      r.state = draftStep(r.state, { type: 'replace' });
    }
    toString() {
      return 'Escape';
    }
  }
  class Answer {
    constructor(pick) {
      this.pick = pick;
    }
    check(m) {
      return m.pending.length > 0;
    }
    run(m, r) {
      const [answer] = m.pending.splice(this.pick % m.pending.length, 1);
      const before = r.state.current;
      r.state = draftStep(r.state, { type: 'answer', draftId: answer.draftId });
      expect(r.state.current, 'an answer keeps the draft number').toBe(before);
      // The invariant: an answer for another draft never changes the open form.
      const own = m.open !== null && answer.draft === m.open;
      expect(r.state.verdict).toBe(own ? 'fresh' : 'stale');
      if (own) {
        // A fresh answer closes the form, as the panel does.
        m.open = null;
        r.state = draftStep(r.state, { type: 'replace' });
      }
    }
    toString() {
      return `Answer(${this.pick})`;
    }
  }

  it('an answer for another draft never changes the open form', () => {
    const commands = [
      fc.constant(new OpenNew()),
      fc.constant(new Save()),
      fc.constant(new Escape()),
      fc.nat(4).map((pick) => new Answer(pick)),
    ];
    fc.assert(
      fc.property(fc.commands(commands, { maxCommands: 40 }), (cmds) => {
        const setup = () => ({
          model: { open: null, made: 0, pending: [] },
          real: { state: INITIAL_DRAFT },
        });
        fc.modelRun(setup, cmds);
      }),
    );
  });
});
