/**
 * The Tasks tab's preset suggestions: a one-time dialog, then a card above the list.
 *
 * When a shipped preset matches entities in this home and no companion uses it yet,
 * the dialog "Presets you can use" opens once, with a checked row for each preset.
 * "Add" saves the checked presets as they are. "Not now" closes the dialog, and the
 * card above the task list then keeps the suggestions: its Set up opens the normal
 * Add dialog on one preset, and its Not now hides them for this user.
 *
 * Which presets to show is decided in `preset-nudge.ts`; this module draws and wires.
 * Everything is a free function over a `PanelHost` (see `panel-host.ts`).
 */

import * as api from './api';
import { t, tn } from './i18n';
import { errorMessage, openDeclarativeForm, seededFrom } from './panel-declarative';
import { makeDialog } from './panel-dialogs';
import type { PanelHost } from './panel-host';
import {
  addOutcome,
  cardPresets,
  dialogPresets,
  markDismissed,
  markShown,
  mergeNudgeState,
  newPresets,
  presetIdsWithCompanion,
  usablePresets,
} from './preset-nudge';
import type { DeclarativeCompanionPreset } from './types';
import {
  RELOAD_RETRIES,
  RELOAD_RETRY_MS,
  btnAttrs,
  escapeHTML,
  setBtnWeight,
  toast,
} from './utils';

const COMPANIONS = { view: 'settings', detail: null, section: 'companions' } as const;

function usable(p: PanelHost): DeclarativeCompanionPreset[] {
  return usablePresets(p._declarativePresets, p._declarativeCompanions);
}

/**
 * Save this user's answers. Writes queue behind each other, and each one reads the
 * stored copy first and writes the union, so an answer given in another browser
 * tab since this one loaded is kept.
 */
function savePresetNudge(p: PanelHost): void {
  const hass = p._hass;
  if (!hass || !p._presetNudge) return;
  p._presetNudgeSaving = p._presetNudgeSaving
    .then(async () => {
      const stored = await api.getPresetNudge(hass).catch(() => null);
      const local = p._presetNudge;
      if (!local) return;
      const merged = stored ? mergeNudgeState(local, stored) : local;
      p._presetNudge = merged;
      await api.setPresetNudge(hass, merged);
    })
    .catch(() => {
      // Best-effort, like the intro card: a lost write shows the suggestion again.
    });
}

// ── the card ────────────────────────────────────────────────────────────────

/** The card above the task list, or '' when there is nothing to suggest. */
export function presetNudgeCard(p: PanelHost): string {
  // Hidden while the dialog is open, and while its add runs after an early close.
  if (!p._presetNudge || p._presetDialog.open || p._presetDialog.busy) return '';
  const presets = cardPresets(usable(p), p._presetNudge);
  if (!presets.length) return '';
  const rows = presets
    .map(
      (preset) => `
        <li class="hk-preset-nudge-row" data-preset-id="${escapeHTML(preset.id)}">
          <ha-icon class="hk-preset-nudge-icon" icon="${escapeHTML(preset.icon)}"></ha-icon>
          <span class="hk-preset-nudge-text">
            <span class="hk-preset-nudge-name">${escapeHTML(preset.name)}</span>
            <span class="hk-preset-nudge-count">${escapeHTML(
              tn('tasks.presets.matches', preset.matches ?? 0),
            )}</span>
          </span>
          <ha-button ${btnAttrs('secondary')} class="hk-preset-nudge-setup" data-preset-id="${escapeHTML(
            preset.id,
          )}">${escapeHTML(t('tasks.presets.setUp'))}</ha-button>
        </li>`,
    )
    .join('');
  return `
      <section class="hk-preset-nudge" aria-labelledby="hk-preset-nudge-title">
        <div class="hk-preset-nudge-head">
          <div class="hk-form-title" id="hk-preset-nudge-title">${escapeHTML(
            t('tasks.presets.title'),
          )}</div>
          <ha-icon-button class="hk-preset-nudge-hide" label="${escapeHTML(
            t('tasks.presets.notNow'),
          )}"><ha-icon icon="mdi:close"></ha-icon></ha-icon-button>
        </div>
        <div class="hk-preset-nudge-body">${escapeHTML(t('tasks.presets.body'))}</div>
        <ul class="hk-preset-nudge-list">${rows}</ul>
        <div class="hk-preset-nudge-actions">
          <ha-button ${btnAttrs('tertiary')} class="hk-preset-nudge-hide">${escapeHTML(
            t('tasks.presets.notNow'),
          )}</ha-button>
          <a class="hk-preset-nudge-all" href="${escapeHTML(p._hrefFor(COMPANIONS))}">${escapeHTML(
            t('tasks.presets.seeAll'),
          )}</a>
        </div>
      </section>`;
}

/** Wire the card's Set up, Not now and See all presets. */
export function wirePresetNudge(p: PanelHost, root: ParentNode): void {
  root.querySelectorAll<HTMLElement>('.hk-preset-nudge-setup').forEach((b) =>
    b.addEventListener('click', () => {
      const preset = p._declarativePresets?.find((x) => x.id === b.dataset.presetId);
      // The Add dialog lets the user check the preset before it saves. The refresh
      // after the save takes the row away, because the preset then has a companion.
      if (preset) void openDeclarativeForm(p, seededFrom(preset));
    }),
  );
  root.querySelectorAll<HTMLElement>('.hk-preset-nudge-hide').forEach((b) =>
    b.addEventListener('click', () => {
      if (!p._presetNudge) return;
      const ids = cardPresets(usable(p), p._presetNudge).map((x) => x.id);
      p._presetNudge = markDismissed(p._presetNudge, ids);
      p._render();
      savePresetNudge(p);
    }),
  );
  root.querySelector<HTMLAnchorElement>('.hk-preset-nudge-all')?.addEventListener('click', (e) => {
    e.preventDefault();
    p._navigate(COMPANIONS);
  });
}

// ── the one-time dialog ─────────────────────────────────────────────────────

/**
 * Open the dialog when a suggestion is new to this user. State only: the caller
 * renders. The caller also checks that the panel has loaded and that no other
 * dialog or form is open; this checks the page and the user's answers.
 */
export function maybeOpenPresetDialog(p: PanelHost): void {
  const state = p._presetNudge;
  if (p._presetDialog.open || p._presetDialog.busy || !state) return;
  if (p._view !== 'tasks' || p._detail) return;
  // The first-run intro speaks first. The dialog waits for the next visit after it,
  // and the card waits for the dialog.
  if (!p._introDismissed) return;
  const found = usable(p);
  // A preset with a companion was met already; if the companion goes, it shows on
  // the card, not in the dialog.
  const owned = presetIdsWithCompanion(p._declarativePresets, p._declarativeCompanions).filter(
    (id) => !state.shown.includes(id),
  );
  if (!owned.length && !newPresets(found, state).length) return;
  const ids = dialogPresets(found, state).map((x) => x.id);
  if (ids.length) p._presetDialog = { open: true, ids, selected: [...ids], busy: false };
  // Marked when offered, so a reload does not offer them again. A preset too big for
  // the dialog is offered by the card alone.
  p._presetNudge = markShown(state, [...owned, ...found.map((x) => x.id)]);
  savePresetNudge(p);
}

function closePresetDialog(p: PanelHost): void {
  p._presetDialog = { open: false, ids: [], selected: [], busy: false };
  p._render();
}

/** Build the dialog into *host*. */
export function renderPresetDialog(p: PanelHost, host: HTMLElement): void {
  const state = p._presetDialog;
  const presets = state.ids
    .map((id) => p._declarativePresets?.find((x) => x.id === id))
    .filter((x): x is DeclarativeCompanionPreset => Boolean(x));
  const { dialog, body, footer, mount } = makeDialog(t('tasks.presets.dialogTitle'), () => {
    if (!p._presetDialog.open) return;
    // Closed while an add runs: the add goes on and reports with its toast.
    if (p._presetDialog.busy) {
      p._presetDialog.open = false;
      p._render();
      return;
    }
    // Closing it is "Not now": the card keeps the suggestions.
    closePresetDialog(p);
  });
  dialog.classList.add('hk-preset-dialog');

  const intro = document.createElement('p');
  intro.className = 'hk-preset-dialog-body';
  intro.textContent = t('tasks.presets.dialogBody');
  body.appendChild(intro);

  const add = document.createElement('ha-button');
  const later = document.createElement('ha-button');
  const syncButtons = (): void => {
    const n = p._presetDialog.selected.length;
    add.textContent = tn('tasks.presets.add', n);
    add.toggleAttribute('disabled', n === 0 || p._presetDialog.busy);
    later.toggleAttribute('disabled', p._presetDialog.busy);
  };

  const list = document.createElement('div');
  list.className = 'hk-preset-dialog-list';
  for (const preset of presets) {
    const row = document.createElement('label');
    row.className = 'hk-preset-pick';
    row.innerHTML = `
        <input type="checkbox" data-preset-id="${escapeHTML(preset.id)}">
        <ha-icon icon="${escapeHTML(preset.icon)}"></ha-icon>
        <span class="hk-preset-pick-text">
          <span class="hk-preset-pick-name">${escapeHTML(preset.name)}</span>
          <span class="hk-preset-pick-desc">${escapeHTML(preset.description)}</span>
          <span class="hk-preset-pick-count">${escapeHTML(
            tn('tasks.presets.matches', preset.matches ?? 0),
          )}</span>
        </span>`;
    const box = row.querySelector('input') as HTMLInputElement;
    box.checked = state.selected.includes(preset.id);
    box.disabled = state.busy;
    box.addEventListener('change', () => {
      const others = p._presetDialog.selected.filter((id) => id !== preset.id);
      // Kept in list order, so the adds run in the order the user reads them.
      const selected = box.checked ? [...others, preset.id] : others;
      p._presetDialog.selected = p._presetDialog.ids.filter((id) => selected.includes(id));
      // Patched in place: a re-render would move the focus off the checkbox.
      syncButtons();
    });
    list.appendChild(row);
  }
  body.appendChild(list);

  // ha-dialog-footer renders only its named slots; an unslotted button never shows.
  later.setAttribute('slot', 'secondaryAction');
  later.classList.add('hk-preset-dialog-later');
  setBtnWeight(later, 'tertiary');
  later.textContent = t('tasks.presets.notNow');
  later.addEventListener('click', () => closePresetDialog(p));
  footer.appendChild(later);

  add.setAttribute('slot', 'primaryAction');
  add.classList.add('hk-preset-dialog-add');
  setBtnWeight(add, 'primary');
  add.addEventListener('click', () => void addSelectedPresets(p));
  footer.appendChild(add);
  syncButtons();

  mount();
  host.appendChild(dialog);
}

/** Add one preset, waiting out a config-entry reload that an earlier add started. */
async function addPreset(
  p: PanelHost,
  preset: DeclarativeCompanionPreset,
  retriesLeft = RELOAD_RETRIES,
): Promise<void> {
  if (!p._hass) throw new Error('no connection');
  try {
    await api.addDeclarativeCompanion(p._hass, preset.default_spec);
  } catch (err) {
    // `not_loaded` comes before the store writes anything, so a retry never makes a
    // second companion.
    if (api.isNotLoaded(err) && retriesLeft > 0) {
      await new Promise((r) => setTimeout(r, RELOAD_RETRY_MS));
      return addPreset(p, preset, retriesLeft - 1);
    }
    throw err;
  }
}

/** Save each checked preset as it is, then refresh once and say how it went. */
export async function addSelectedPresets(p: PanelHost): Promise<void> {
  if (!p._hass || p._presetDialog.busy) return;
  p._presetDialog.busy = true;
  p._render();
  // A fresh list, so a companion made in another tab since this one loaded is seen.
  try {
    p._declarativeCompanions = await api.listDeclarativeCompanions(p._hass);
  } catch {
    // Keep the list the panel has.
  }
  const chosen = p._presetDialog.selected
    .map((id) => p._declarativePresets?.find((x) => x.id === id))
    .filter((x): x is DeclarativeCompanionPreset => Boolean(x))
    // A companion made from the preset since the dialog opened is left alone.
    .filter((x) => !p._declarativeCompanions.some((c) => c.preset_id === x.id));
  const results: { ok: boolean; error?: string }[] = [];
  // One after another: each add can reload the config entry under the next.
  for (const preset of chosen) {
    try {
      await addPreset(p, preset);
      results.push({ ok: true });
    } catch (err) {
      results.push({ ok: false, error: errorMessage(err) });
    }
  }
  p._presetDialog = { open: false, ids: [], selected: [], busy: false };
  await p._refresh();
  const outcome = addOutcome(results);
  if (!outcome.total) return;
  if (outcome.kind === 'all') toast(p, tn('tasks.presets.added', outcome.added));
  else if (outcome.kind === 'some') {
    toast(p, t('tasks.presets.addedSome', { added: outcome.added, total: outcome.total }));
  } else toast(p, t('tasks.presets.addFailed', { error: outcome.error }));
}
