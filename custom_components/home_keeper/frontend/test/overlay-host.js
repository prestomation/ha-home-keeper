/**
 * The overlay members of `PanelHost` for a test's stand-in host, built on the real
 * `overlay-state.ts`. Spread it into the stand-in, and pass *open* to start with
 * those overlays open, each with the selector *opener*.
 *
 * Not a `*.test.js` file on purpose, as `panel-harness.js` is not.
 */
import { NO_OVERLAY, isBusy, isOpen, overlayStep } from '../src/overlay-state.ts';

export function overlayMembers(open = [], opener = null) {
  let overlay = NO_OVERLAY;
  for (const kind of open) overlay = overlayStep(overlay, { type: 'open', kind, opener });
  return {
    get _overlay() {
      return overlay;
    },
    set _overlay(value) {
      overlay = value;
    },
    _isOpen: (kind) => isOpen(overlay, kind),
    _busy: () => isBusy(overlay),
    _openOverlay(kind) {
      overlay = overlayStep(overlay, { type: 'open', kind, opener: null });
    },
    _closeOverlay(kind, keyboard = true) {
      overlay = overlayStep(overlay, { type: 'close', kind });
      if (!keyboard) overlay = overlayStep(overlay, { type: 'focused' });
    },
    _flushOverlayFocus() {
      overlay = overlayStep(overlay, { type: 'focused' });
    },
  };
}
