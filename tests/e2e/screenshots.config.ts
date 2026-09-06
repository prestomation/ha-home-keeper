/** Config for the one-off screenshot capture (see screenshots.capture.ts). */
import { captureConfig } from './capture-config';

export default captureConfig('screenshots.capture.ts', {
  // The capture keeps growing (one `test()` walks every documented surface); bump past
  // the shared 60s default so a slow CI/sandbox run doesn't starve the later shots.
  // Raised again when the Duplicate drawer joined the walk: a cold container was
  // spending the whole budget before the last third of the shots.
  timeout: 240_000,
});
