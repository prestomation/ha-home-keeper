import { defineConfig, mergeConfig } from 'vitest/config';

import baseConfig from './vitest.config.js';

// Vitest config used only by Stryker (see stryker.conf.json).
//
// It is the normal config minus the `*-parity.test.js` files, which analyse
// `src/*.ts` as *text* read off disk rather than importing it. Inside Stryker's
// sandbox they would read *mutated* source, so a mutant that alters any string
// literal flips them red and gets counted as "killed" by a test that never
// exercised the behaviour — inflating the score with pure noise. They are
// parity/lint gates, not behavioural tests, so dropping them here costs no real
// signal; `ci/test-frontend.sh` still runs them on every PR.
export default mergeConfig(
  baseConfig,
  defineConfig({
    test: {
      exclude: ['**/node_modules/**', '**/*-parity.test.js'],
    },
  }),
);
