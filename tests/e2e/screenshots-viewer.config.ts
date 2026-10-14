/** Config for the view-only panel screenshot capture: logged in as the `viewer` user. */
import { captureConfig } from './capture-config';

export default captureConfig('screenshots-viewer.capture.ts', {
  use: { storageState: './.auth/viewer-state.json' },
});
