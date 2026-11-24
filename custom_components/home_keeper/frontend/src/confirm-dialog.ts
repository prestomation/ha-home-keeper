/**
 * The confirmation dialog, built once for the panel and the card.
 *
 * The scrim goes on `document.body`, so `position: fixed` resolves against the
 * viewport and not against a shadow root. A shadow root's `--hk-*` tokens do not
 * reach it. So the scrim defines its own tokens from Home Assistant's document-level
 * theme variables, and every rule below reads those tokens.
 *
 * The module holds no panel or card state. The caller owns the overlay bookkeeping
 * (`_openOverlay` and `_closeOverlay`) and the focus return. This module owns the
 * markup, the keyboard rules and the safe default: Cancel has the keyboard, Escape
 * and a tap outside cancel, and Tab stays inside.
 */

import { t } from './i18n';
import { setBtnWeight } from './utils';

/** What the dialog says. A null `confirmLabel` makes it a notice that has only Close. */
export interface ConfirmContent {
  title: string;
  body: string;
  confirmLabel: string | null;
  /** `danger` is the solid red button of a delete. `primary` is for a choice that
   *  loses nothing, such as the card's "mark done?" question. */
  tone?: 'danger' | 'primary';
}

export interface ConfirmHandlers {
  /** Cancel, Close, Escape or a tap outside. */
  onCancel: () => void;
  /** The confirm button. Not called for a notice. */
  onConfirm: () => void;
}

export interface ConfirmHandle {
  /** Remove the scrim and the document keydown listener. Safe to call twice. */
  close: () => void;
}

const STYLE_ID = 'hk-confirm-style';

// The tokens are defined on the scrim, because that is the one place a rule may write
// a literal value. They resolve to the same theme variables as the panel's tokens.
const CSS = `
.hk-confirm-scrim {
  --hk-confirm-dim: rgba(0, 0, 0, 0.4);
  --hk-confirm-shadow: rgba(0, 0, 0, 0.24);
  --hk-confirm-surface: var(--ha-card-background, var(--card-background-color, #fff));
  --hk-confirm-ink: var(--primary-text-color, #000);
  --hk-confirm-ink-soft: var(--secondary-text-color, #666);
  --hk-confirm-radius: 28px;
  --hk-confirm-pad: 24px;
  --hk-confirm-edge: 32px;
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--hk-confirm-dim);
}
.hk-confirm-modal {
  box-sizing: border-box;
  min-width: 280px;
  max-width: min(400px, calc(100vw - var(--hk-confirm-edge)));
  padding: var(--hk-confirm-pad);
  border-radius: var(--hk-confirm-radius);
  background: var(--hk-confirm-surface);
  box-shadow: 0 8px 32px var(--hk-confirm-shadow);
}
.hk-confirm-title {
  margin: 0 0 16px;
  font-size: 1.25rem;
  font-weight: 500;
  color: var(--hk-confirm-ink);
  overflow-wrap: anywhere;
}
.hk-confirm-body {
  margin: 0 0 24px;
  color: var(--hk-confirm-ink-soft);
  white-space: pre-line;
  overflow-wrap: anywhere;
}
.hk-confirm-body:empty {
  display: none;
}
.hk-confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
`;

/** Add the stylesheet once. A second call finds it and does nothing. */
function ensureStyle(): void {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.appendChild(style);
}

/**
 * Show the dialog. The caller decides what Cancel and the confirm button do, and
 * gets a handle to take the dialog down.
 */
export function mountConfirm(content: ConfirmContent, handlers: ConfirmHandlers): ConfirmHandle {
  ensureStyle();
  const scrim = document.createElement('div');
  scrim.className = 'hk-confirm-scrim';

  // A modal dialog that asks for an answer. It names itself from its heading, reads
  // its body as the description, and says that the page behind is inert.
  const modal = document.createElement('div');
  modal.className = 'hk-confirm-modal';
  modal.setAttribute('role', 'alertdialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-labelledby', 'hk-confirm-title');
  modal.setAttribute('aria-describedby', 'hk-confirm-body');

  const h2 = document.createElement('h2');
  h2.id = 'hk-confirm-title';
  h2.className = 'hk-confirm-title';
  h2.textContent = content.title;

  const para = document.createElement('p');
  para.id = 'hk-confirm-body';
  para.className = 'hk-confirm-body';
  para.textContent = content.body;

  const row = document.createElement('div');
  row.className = 'hk-confirm-actions';

  // Cancel when a confirm button is beside it, Close when the dialog only reports.
  const cancel = document.createElement('ha-button');
  setBtnWeight(cancel, 'tertiary');
  cancel.textContent = content.confirmLabel ? t('btn.cancel') : t('btn.close');
  cancel.addEventListener('click', () => handlers.onCancel());
  row.appendChild(cancel);

  if (content.confirmLabel) {
    const confirm = document.createElement('ha-button');
    setBtnWeight(confirm, content.tone === 'primary' ? 'primary' : 'danger-primary');
    confirm.textContent = content.confirmLabel;
    confirm.addEventListener('click', () => handlers.onConfirm());
    row.appendChild(confirm);
  }

  modal.append(h2, para, row);
  scrim.appendChild(modal);
  scrim.addEventListener('click', (e) => {
    if (e.target === scrim) handlers.onCancel();
  });

  // Escape cancels. Tab and Shift+Tab move between the dialog's own buttons and never
  // reach the page behind the scrim.
  const buttons = [...row.children] as HTMLElement[];
  const onKey = (e: KeyboardEvent): void => {
    if (e.key === 'Escape') {
      // 1 press closes 1 overlay: a handler of an overlay under this one does not run.
      e.stopImmediatePropagation();
      handlers.onCancel();
      return;
    }
    if (e.key !== 'Tab') return;
    e.preventDefault();
    const at = buttons.indexOf(document.activeElement as HTMLElement);
    const step = e.shiftKey ? -1 : 1;
    const next = at < 0 ? (e.shiftKey ? buttons.length - 1 : 0) : at + step;
    buttons[(next + buttons.length) % buttons.length].focus();
  };
  document.addEventListener('keydown', onKey);
  document.body.appendChild(scrim);

  let open = true;
  const close = (): void => {
    if (!open) return;
    open = false;
    document.removeEventListener('keydown', onKey);
    scrim.remove();
  };

  // Cancel (or Close) takes the keyboard: the safe choice for a destructive dialog.
  // In a real browser `ha-button` renders its inner <button> asynchronously, and its
  // focus() throws until it has one. So try now (a test double, or a button that has
  // rendered), and again once it has rendered, if the dialog is still open.
  const focusCancel = (): void => {
    try {
      cancel.focus();
    } catch {
      // Not rendered yet: the deferred call below focuses it.
    }
  };
  focusCancel();
  void customElements
    .whenDefined('ha-button')
    .then(() => (cancel as HTMLElement & { updateComplete?: Promise<unknown> }).updateComplete)
    .then(() => {
      if (open && cancel.isConnected) focusCancel();
    });

  return { close };
}
