/** Config for the one-off video walkthrough capture (see walkthrough.capture.ts). */
import baseConfig from './playwright.config';

export default {
  ...baseConfig,
  testDir: '.',
  testMatch: 'walkthrough.capture.ts',
  // The narrated tour (with deliberate pauses) plus the video flush runs well past
  // the default 60s per-test budget — give it room.
  timeout: 180_000,
  use: {
    ...baseConfig.use,
    // The base config leaves actionTimeout unset (0 = no per-action cap), so a
    // click on a momentarily-unstable element would hang for the whole test budget.
    // Cap it so any bad selector fails fast and visibly instead.
    actionTimeout: 20_000,
  },
};
