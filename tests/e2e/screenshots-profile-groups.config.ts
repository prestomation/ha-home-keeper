/** Config for the profile filter-groups screenshot capture (see the .capture.ts
 *  beside). One test shoots both widths, so the timeout covers two page loads and
 *  two long forms rather than one. */
import { captureConfig } from './capture-config';

export default captureConfig('screenshots-profile-groups.capture.ts', {
  timeout: 180_000,
});
