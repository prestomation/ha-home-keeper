/**
 * Which dialogs, forms, sheets and menus are open over the panel or the card, and
 * where the keyboard goes when one closes.
 *
 * The overlays are a stack. The last one opened is on top and has the keyboard.
 * Each overlay keeps its opener: a selector for the control that opened it, which
 * the host resolves in the tree that is on screen when the overlay closes. A close
 * of the top overlay sets {@link OverlayState.focus} to that opener. The host moves
 * the keyboard there after its render and then sends `focused`.
 *
 * A menu (a deferral menu or the action sheet) hands over to the dialog that it
 * opens. The dialog takes the menu's place and its opener, so the keyboard goes back
 * to the control that opened the menu, not to a menu item that is gone. A close
 * followed by an open, before the host moved the keyboard, is the same hand-over.
 * When an overlay below the top closes, the overlay above it takes its opener for
 * the same reason.
 *
 * {@link isBusy} is the 1 rule for "the user is busy": a live load waits, a late
 * Markdown upgrade waits, and the preset suggestion does not open.
 *
 * Pure: no Home Assistant code and no DOM.
 */

export const OVERLAY_KINDS = [
  'taskForm',
  'assetForm',
  'note',
  'completion',
  'moveCompletion',
  'snooze',
  'skip',
  'actionSheet',
  'declarative',
  'preset',
  'label',
  'confirm',
  'spendSheet',
  'deferMenu',
] as const;
export type OverlayKind = (typeof OVERLAY_KINDS)[number];

/** The menus. The next overlay that opens over a menu takes its place. */
export const MENU_KINDS: readonly OverlayKind[] = ['deferMenu', 'actionSheet'];

export interface OpenOverlay {
  readonly kind: OverlayKind;
  /** A selector for the control that opened it, or null when there is none. */
  readonly opener: string | null;
}

export interface OverlayState {
  /** The open overlays. The last one is on top. */
  readonly stack: readonly OpenOverlay[];
  /** Where the keyboard must go now, or null to leave it where it is. */
  readonly focus: string | null;
}

export type OverlayEvent =
  /** *kind* opens. `opener` has the keyboard now. Nothing changes if *kind* is open. */
  | { readonly type: 'open'; readonly kind: OverlayKind; readonly opener: string | null }
  /** *kind* closes. Nothing changes if it is not open. */
  | { readonly type: 'close'; readonly kind: OverlayKind }
  /** The host moved the keyboard to `focus`, or decided to leave it. */
  | { readonly type: 'focused' };

export const NO_OVERLAY: OverlayState = { stack: [], focus: null };

export function overlayStep(s: OverlayState, e: OverlayEvent): OverlayState {
  switch (e.type) {
    case 'open': {
      // An overlay that is open stays where it is, with the opener that it had. A
      // form calls this again for a new draft while a dialog of its own is over it.
      if (isOpen(s, e.kind)) return s;
      // The keyboard is on a control of the overlay that just closed, or of the menu
      // that this overlay replaces. The control that opened that one is the real
      // opener.
      let stack = s.stack;
      let opener = s.focus ?? e.opener;
      const top = stack[stack.length - 1];
      if (top && MENU_KINDS.includes(top.kind)) {
        stack = stack.slice(0, -1);
        opener = top.opener ?? opener;
      }
      return { stack: [...stack, { kind: e.kind, opener }], focus: null };
    }
    case 'close': {
      const at = s.stack.findIndex((o) => o.kind === e.kind);
      if (at < 0) return s;
      const gone = s.stack[at];
      // The overlay above opened from a control of this one, which is gone now. It
      // takes this one's opener.
      const stack = s.stack
        .map((o, i) => (i === at + 1 ? { kind: o.kind, opener: gone.opener } : o))
        .filter((_, i) => i !== at);
      // Only the top overlay has the keyboard. A close below it leaves the keyboard.
      const focus = at === s.stack.length - 1 ? gone.opener : s.focus;
      return { stack, focus };
    }
    case 'focused':
      return s.focus === null ? s : { ...s, focus: null };
  }
}

/** Whether *kind* is open. */
export function isOpen(s: OverlayState, kind: OverlayKind): boolean {
  return s.stack.some((o) => o.kind === kind);
}

/** The 1 busy rule: true while any overlay is open. */
export function isBusy(s: OverlayState): boolean {
  return s.stack.length > 0;
}

/** The overlay on top, which has the keyboard, or null. */
export function topOverlay(s: OverlayState): OverlayKind | null {
  return s.stack.length ? s.stack[s.stack.length - 1].kind : null;
}
