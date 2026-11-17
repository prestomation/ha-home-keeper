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
