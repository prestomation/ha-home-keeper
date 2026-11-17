/**
 * The overlay members of `PanelHost` for a test's stand-in host, built on the real
 * `overlay-state.ts`. Spread it into the stand-in, and pass *open* to start with
 * those overlays open.
 *
 * Not a `*.test.js` file on purpose, as `panel-harness.js` is not.
 */
import { NO_OVERLAY, isBusy, isOpen, overlayStep } from '../src/overlay-state.ts';

export function overlayMembers(open = []) {
  let overlay = NO_OVERLAY;
  for (const kind of open) overlay = overlayStep(overlay, { type: 'open', kind, opener: null });
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
    _closeOverlay(kind) {
      overlay = overlayStep(overlay, { type: 'close', kind });
    },
    _flushOverlayFocus() {
      overlay = overlayStep(overlay, { type: 'focused' });
    },
  };
}
