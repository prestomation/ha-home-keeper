/** Config for the phone-width capture (see mobile.capture.ts). */
import baseConfig from './playwright.config';

export default {
  ...baseConfig,
  testDir: '.',
  testMatch: 'mobile.capture.ts',
  timeout: 180_000,
};
