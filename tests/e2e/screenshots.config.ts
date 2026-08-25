/** Config for the one-off screenshot capture (see screenshots.capture.ts). */
import baseConfig from './playwright.config';

export default {
  ...baseConfig,
  testDir: '.',
  testMatch: 'screenshots.capture.ts',
  // The capture keeps growing (one `test()` walks every documented surface); bump past
  // the shared 60s default so a slow CI/sandbox run doesn't starve the later shots.
  timeout: 180_000,
};
