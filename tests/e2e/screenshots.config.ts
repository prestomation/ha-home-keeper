/** Config for the one-off screenshot capture (see screenshots.capture.ts). */
import { captureConfig } from './capture-config';

export default captureConfig('screenshots.capture.ts', {
  // The capture is a serial group of tests that share 1 page. This limit applies to
  // each test, not to the whole group, so a part that grows does not take time from
  // the parts after it.
  timeout: 300_000,
  use: {
    // A stuck step fails in seconds and names itself, before the test limit.
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
});
