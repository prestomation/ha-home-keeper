/** Config for the one-off device-attachment screenshot capture. */
import baseConfig from './playwright.config';

export default {
  ...baseConfig,
  testDir: '.',
  testMatch: 'screenshots-device-attach.capture.ts',
};
