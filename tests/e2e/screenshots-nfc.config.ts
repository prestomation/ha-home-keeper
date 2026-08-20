/** Config for the one-off NFC tag screenshot capture. */
import baseConfig from './playwright.config';

export default {
  ...baseConfig,
  testDir: '.',
  testMatch: 'screenshots-nfc.capture.ts',
};
