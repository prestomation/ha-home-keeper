// Replay the generated parity corpus against the TypeScript side.
//
// `tests/unit/test_parity_corpus.py` draws inputs with Hypothesis for the rules that
// `tests/fixtures/parity.json` marks `corpus`, and writes each input with the Python
// answer to `tests/fixtures/parity_corpus.json`. Each entry here must give the same
// answer. To write the corpus again: `bash ci/parity-corpus.sh`.
import { describe, expect, it } from 'vitest';
import { ADAPTERS, REGISTRY, read } from './parity-adapters.js';

const CORPUS = read('tests/fixtures/parity_corpus.json').rules;

it('covers each rule that the registry marks corpus', () => {
  const marked = REGISTRY.rules.filter((r) => r.corpus).map((r) => r.id);
  expect(Object.keys(CORPUS).sort()).toEqual(marked.sort());
});

for (const [ruleId, entries] of Object.entries(CORPUS)) {
  describe(`parity corpus: ${ruleId}`, () => {
    it('has entries', () => {
      expect(entries.length).toBeGreaterThan(0);
    });
    // 1 test per rule, with every entry that disagrees in the message, so a
    // regression shows its whole size at once.
    it('gives the Python answer for each entry', () => {
      const wrong = entries
        .map((entry) => ({ entry, got: ADAPTERS[ruleId](entry, {}) }))
        .filter(({ entry, got }) => !Object.is(got, entry.expected) && got !== entry.expected);
      expect(wrong).toEqual([]);
    });
  });
}
