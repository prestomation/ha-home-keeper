/** Config for the one-off date-control exploration (see date-control-explore.capture.ts). */
import baseConfig from './playwright.config';

export default {
  ...baseConfig,
  testDir: '.',
  testMatch: 'date-control-explore.capture.ts',
};
