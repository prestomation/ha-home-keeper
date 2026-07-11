/** Config for the one-off screenshot capture (see screenshots.capture.ts). */
import baseConfig from './playwright.config';

export default {
  ...baseConfig,
  testDir: '.',
  testMatch: 'screenshots.capture.ts',
  // The capture walks many surfaces in one sequential test; give it well beyond the
  // base 60s so adding a surface (e.g. the linked-part card) can't tip it into a
  // total-test timeout partway through.
  timeout: 180_000,
};
