/** Config for the one-off device-page-enrichment screenshot capture. */
import baseConfig from './playwright.config';

export default {
  ...baseConfig,
  testDir: '.',
  testMatch: 'screenshots-device-page.capture.ts',
};
