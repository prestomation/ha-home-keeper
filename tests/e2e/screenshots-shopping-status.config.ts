/** Config for the buy-reminder status capture (see the .capture.ts beside). */
import { captureConfig } from './capture-config';

export default captureConfig('screenshots-shopping-status.capture.ts', {
  timeout: 180_000,
});
