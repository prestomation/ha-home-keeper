import fc from 'fast-check';

/**
 * Run settings for the `fast-check` model tests, picked by `HK_FC_PROFILE`, as
 * `HK_HYPOTHESIS_PROFILE` does for the Python property tests.
 *
 * - `ci` (default): a fixed seed, so each run checks the same cases.
 * - `long`: a new random seed and many runs. Run it by hand to search for new defects:
 *   `HK_FC_PROFILE=long npx vitest run <file>`. A failure prints its seed and path.
 * - `stryker`: a fixed seed and few runs, so each mutant stays below the Stryker timeout.
 */
const PROFILES = {
  ci: { seed: 20261117, numRuns: 200 },
  long: { numRuns: 5000 },
  stryker: { seed: 20261117, numRuns: 40 },
};

const name = process.env.HK_FC_PROFILE || 'ci';
if (!(name in PROFILES)) throw new Error(`Unknown HK_FC_PROFILE: ${name}`);
fc.configureGlobal(PROFILES[name]);
