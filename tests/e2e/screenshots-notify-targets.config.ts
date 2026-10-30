/** Config for the notification "Send to" screenshot capture (see the .capture.ts beside). */
import { captureConfig } from './capture-config';

export default captureConfig('screenshots-notify-targets.capture.ts', {
  timeout: 120_000,
});
