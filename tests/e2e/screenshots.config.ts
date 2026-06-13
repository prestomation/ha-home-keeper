/** Config for the one-off screenshot capture (see screenshots.capture.ts). */
import baseConfig from './playwright.config';

export default {
  ...baseConfig,
  testDir: '.',
  testMatch: 'screenshots.capture.ts',
};
