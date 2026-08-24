/** Config for the standalone declarative-companion screenshot capture. */
import baseConfig from './playwright.config';

export default {
  ...baseConfig,
  testDir: '.',
  testMatch: 'screenshots-declarative.capture.ts',
  timeout: 60_000,
};
