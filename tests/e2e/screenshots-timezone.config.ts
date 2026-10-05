/** Config for the Home Assistant time zone capture (see the .capture.ts beside). */
import { captureConfig } from './capture-config';

// The browser runs in a zone 13 hours from Home Assistant's (America/New_York, in
// tests/integration/ha_config), so a time shown in the browser zone would be wrong.
export default captureConfig('screenshots-timezone.capture.ts', {
  timeout: 180_000,
  use: { timezoneId: 'Asia/Tokyo' },
});
