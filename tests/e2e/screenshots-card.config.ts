/** Config for the dashboard-card screenshot capture (see screenshots-card.capture.ts). */
import baseConfig from './playwright.config';

export default {
  ...baseConfig,
  testDir: '.',
  testMatch: 'screenshots-card.capture.ts',
};
