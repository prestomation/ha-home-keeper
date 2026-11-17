// Run every shared case file in the parity registry through the TypeScript side.
//
// `tests/fixtures/parity.json` lists each rule that exists in Python and in
// TypeScript, and the case file that pins it. This file runs each case against the
// TypeScript function; `tests/unit/test_shared_cases.py` runs the same file against
// the Python function. When the 2 sides disagree, 1 of the 2 tests fails.
import { afterEach, describe, expect, it } from 'vitest';
import { ADAPTERS, REGISTRY, read } from './parity-adapters.js';

const savedTz = process.env.TZ;
afterEach(() => {
  if (savedTz === undefined) delete process.env.TZ;
  else process.env.TZ = savedTz;
});

it('has an adapter for every registered rule', () => {
  expect(Object.keys(ADAPTERS).sort()).toEqual(REGISTRY.rules.map((r) => r.id).sort());
});

for (const rule of REGISTRY.rules) {
  const data = read(rule.cases);
  describe(`shared cases: ${rule.id}`, () => {
    it('has cases to run', () => {
      expect(data.cases.length).toBeGreaterThan(0);
    });
    for (const c of data.cases) {
      it(c.name, () => {
        // A case that names a zone runs with it as the local zone, so a stamp that is
        // read in local time gives a different answer than one read as UTC.
        const tz = c.input?.tz;
        if (tz) process.env.TZ = tz;
        expect(ADAPTERS[rule.id](c, data)).toStrictEqual(c.expected);
      });
    }
  });
}
