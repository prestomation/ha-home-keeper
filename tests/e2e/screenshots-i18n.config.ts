/** Config for the one-off i18n screenshot capture (see screenshots-i18n.capture.ts). */
import baseConfig from './playwright.config';

export default {
  ...baseConfig,
  testDir: '.',
  testMatch: 'screenshots-i18n.capture.ts',
};
