/** Config for the one-off panel→device-link screenshot capture. */
import baseConfig from './playwright.config';

export default {
  ...baseConfig,
  testDir: '.',
  testMatch: 'screenshots-device-link.capture.ts',
};
