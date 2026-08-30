/**
 * Dialog chrome shared by the panel and the dashboard card.
 *
 * Both surfaces now open the same Snooze and Skip dialogs, so the shell they are
 * built into has to live somewhere neither owns. Nothing here knows about tasks or
 * about either host: it builds an `ha-dialog` with a body and a footer and hands
 * them back for the caller to fill.
 *
 * `makeForm` takes `hass` and an optional `register` rather than reaching for a
 * component's own field, because the panel keeps every live form in a list it
 * re-hydrates on each `hass` update and the card does not.
 */

import type { FormField, HaFormElement } from './forms';
import { t } from './i18n';
import type { Hass } from './types';

/** The parts of a dialog a caller fills, plus the `mount` that attaches them. */
export interface DialogParts {
  dialog: HTMLElement;
  body: HTMLElement;
  footer: HTMLElement;
  mount: () => void;
}

/**
 * Build an open `ha-dialog` titled *title*, calling *onClosed* when it closes.
 *
 * Action buttons must be wrapped in `<ha-dialog-footer slot="footer">` — current
 * `ha-dialog` only exposes a "footer" slot; primaryAction/secondaryAction slotted
 * directly on `<ha-dialog>` silently don't render. Falls back to slotting straight
 * on `<ha-dialog>` (the pre-wa-dialog convention) if `ha-dialog-footer` isn't
 * registered, so older HA frontends keep working too.
 */
export function makeDialog(title: string, onClosed: () => void): DialogParts {
  const dialog = document.createElement('ha-dialog');
  dialog.setAttribute('open', '');
  dialog.setAttribute('heading', title);
  const heading = document.createElement('span');
  heading.setAttribute('slot', 'headerTitle');
  heading.textContent = title;
  dialog.appendChild(heading);
  dialog.addEventListener('closed', onClosed);

  const body = document.createElement('div');
  body.className = 'hk-completion-body';

  const hasFooter = Boolean(customElements.get('ha-dialog-footer'));
  const footer: HTMLElement = hasFooter ? document.createElement('ha-dialog-footer') : dialog;
  if (hasFooter) footer.setAttribute('slot', 'footer');

  // Deferred so the caller can fill body and footer in whatever order reads best,
  // while the dialog still reaches the DOM with its children already attached.
  const mount = (): void => {
    dialog.appendChild(body);
    if (hasFooter) dialog.appendChild(footer);
  };
  return { dialog, body, footer, mount };
}

/**
 * Build an `ha-form` for *schema* over *data*, reporting edits through *onChange*.
 *
 * Labels resolve from `field.<name>`, and helper text from `help.<name>` where a
 * string is authored — returning '' elsewhere so helpers appear only where we wrote
 * them. *register* receives the element for hosts that re-assign `hass` on update.
 */
export function makeForm(
  hass: Hass | undefined,
  schema: FormField[],
  data: Record<string, unknown>,
  onChange: (value: Record<string, unknown>) => void,
  register?: (form: HaFormElement) => void,
): HaFormElement {
  const form = document.createElement('ha-form') as HaFormElement;
  form.hass = hass;
  form.schema = schema;
  form.data = data;
  form.computeLabel = (s: { name: string }): string => (s.name ? t('field.' + s.name) : '');
  form.computeHelper = (s: { name: string }): string => {
    if (!s.name) return '';
    const h = t('help.' + s.name);
    return h === 'help.' + s.name ? '' : h;
  };
  form.addEventListener('value-changed', (e: Event) => {
    const value = (e as CustomEvent<{ value: Record<string, unknown> }>).detail.value;
    onChange(value);
  });
  register?.(form);
  return form;
}
