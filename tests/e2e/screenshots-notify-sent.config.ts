/** Config for the "notification sent" screenshot capture (see the .capture.ts beside). */
import { captureConfig } from './capture-config';

export default captureConfig('screenshots-notify-sent.capture.ts', {
  timeout: 120_000,
});
