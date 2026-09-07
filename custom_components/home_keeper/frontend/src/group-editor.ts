import { emptyGroup } from './card-filter';
import type { CompanionOption, FormField } from './forms';
import { filterGroupSchema, groupFormData, toFilterGroup } from './forms';
import { t } from './i18n';
import type { FilterGroup } from './types';
import { setBtnWeight } from './utils';

/**
 * The **filter groups** editor, shared by the Settings → Profiles rows and the
 * dashboard card's own editor.
 *
 * A profile selects tasks with an OR of groups (`card-filter.groupMatches`), and both
 * surfaces edit the same list of them, so the DOM, the per-group form, the OR divider
 * and the add/delete rules live here once. The two surfaces differ only in what they
 * are given: the panel translates its labels, the card editor is English-only, and
 * each supplies its own `ha-form` constructor (the panel's registers the element for
 * `hass` updates; the card's does not).
 *
 * The caller owns the `groups` array. This renders it, mutates it in place when a
 * group is added or deleted, and reports the new list through `onChange` — so the
 * caller's save path reads one value whichever way the list changed.
 */

/** How one surface builds an `ha-form`. Same shape as the panel's `_makeForm`, which
 *  is what the panel passes straight in. */
export type MakeGroupForm = (
  schema: FormField[],
  data: Record<string, unknown>,
  onChange: (value: Record<string, unknown>) => void,
  labelling?: {
    computeLabel: (s: { name: string }) => string;
    computeHelper?: (s: { name: string }) => string;
  },
) => HTMLElement;

/** The words around the groups. Supplied by the caller because the card editor is
 *  English-only while the panel translates. */
export interface GroupEditorStrings {
  /** The heading on group *n*, counted from 1 as the reader sees it. */
  title: (n: number) => string;
  add: string;
  remove: string;
  /** The divider between two groups — the operator the profile applies. */
  or: string;
  /** What matching one group means, repeated on each so the rule is where the fields
   *  are rather than only at the top of the section. */
  help: string;
}

export interface GroupEditorOptions {
  /** The integrations this install can filter by; empty drops both companion fields. */
  companions: CompanionOption[];
  makeForm: MakeGroupForm;
  strings: GroupEditorStrings;
  /** Called with the new list after every edit, add or delete. */
  onChange: (groups: FilterGroup[]) => void;
  /** Id for the Add button, so a test (or a label) can name one surface's button. */
  addId?: string;
  /** Field labelling. Defaults to the translated panel spelling; the card editor
   *  passes its own English one. */
  computeLabel?: (s: { name: string }) => string;
  computeHelper?: (s: { name: string }) => string;
}

/** The panel's field labels. `labels` is the shared task field, so it keeps that
 *  key space; everything else is a filter field named under `notify.`. */
function defaultComputeLabel(s: { name: string }): string {
  if (s.name === 'labels') return t('field.labels');
  return t('notify.' + s.name);
}

/** Render (or re-render) the whole groups editor into *host*.
 *
 * A re-render clears *host* and rebuilds it. The forms are cheap, the state that
 * matters is the `groups` array the caller owns, and rebuilding is what renumbers the
 * titles and drops the last Delete button when a delete leaves one group behind. */
export function renderGroupsEditor(
  host: HTMLElement,
  groups: FilterGroup[],
  opts: GroupEditorOptions,
): void {
  const computeLabel = opts.computeLabel ?? defaultComputeLabel;
  const rerender = (): void => renderGroupsEditor(host, groups, opts);
  host.textContent = '';

  groups.forEach((group, index) => {
    // The operator, between the two things it joins. Decorative: the heading above
    // each group already names it, so a screen reader is not read a bare "OR".
    if (index) {
      const or = document.createElement('div');
      or.className = 'hk-filter-or';
      or.setAttribute('aria-hidden', 'true');
      or.textContent = opts.strings.or;
      host.appendChild(or);
    }

    const card = document.createElement('div');
    card.className = 'hk-filter-group';
    card.dataset.group = String(index);

    const head = document.createElement('div');
    head.className = 'hk-filter-group-head';
    const title = document.createElement('span');
    title.className = 'hk-filter-group-title';
    title.textContent = opts.strings.title(index + 1);
    head.appendChild(title);
    // No Delete on a lone group: a profile always has one, and an empty group is how
    // "everything" is spelled, so there is nothing a delete there could mean.
    if (groups.length > 1) {
      const del = document.createElement('ha-icon-button');
      del.className = 'hk-filter-group-delete';
      del.setAttribute('icon', 'mdi:delete-outline');
      del.setAttribute('title', opts.strings.remove);
      del.setAttribute('aria-label', opts.strings.remove);
      del.addEventListener('click', () => {
        groups.splice(index, 1);
        rerender();
        opts.onChange([...groups]);
      });
      head.appendChild(del);
    }
    card.appendChild(head);

    const help = document.createElement('div');
    help.className = 'hk-settings-intro';
    help.textContent = opts.strings.help;
    card.appendChild(help);

    card.appendChild(
      opts.makeForm(
        filterGroupSchema(opts.companions),
        groupFormData(group),
        (value) => {
          // Written back into the caller's array by index, so an edit in one group
          // cannot disturb another — and normalized on the way in, since `ha-form`
          // emits a cleared picker as `undefined`.
          groups[index] = toFilterGroup(value);
          opts.onChange([...groups]);
        },
        { computeLabel, computeHelper: opts.computeHelper },
      ),
    );

    host.appendChild(card);
  });

  const add = document.createElement('ha-button');
  add.className = 'hk-filter-group-add';
  if (opts.addId) add.id = opts.addId;
  setBtnWeight(add, 'secondary');
  add.textContent = opts.strings.add;
  add.addEventListener('click', () => {
    groups.push(emptyGroup());
    rerender();
    opts.onChange([...groups]);
  });
  host.appendChild(add);
}

/**
 * The groups editor's own styles, included by `panel-styles.ts` and by the card
 * editor's stylesheet — one definition, so a group looks the same wherever it is
 * edited.
 *
 * A group is a bordered block like `.hk-item-card` but flat: it never collapses, so it
 * carries no header button and no chevron. The divider is a centred word with a rule
 * running out either side, which is what makes the OR read as joining the two groups
 * rather than labelling the one below it.
 */
export const GROUP_EDITOR_CSS = `
  .hk-filter-group {
    border: 1px solid var(--divider-color); border-radius: 8px;
    padding: 8px 12px 12px; margin-top: 8px;
  }
  .hk-filter-group ha-form { display: block; }
  .hk-filter-group-head { display: flex; align-items: center; gap: 8px; }
  .hk-filter-group-title { flex: 1; font-weight: 500; }
  .hk-filter-group-delete { color: var(--secondary-text-color); flex: 0 0 auto; }
  .hk-filter-group-delete:hover { color: var(--error-color, #db4437); }
  .hk-filter-group .hk-settings-intro { margin: 4px 0 8px; }
  .hk-filter-or {
    display: flex; align-items: center; gap: 8px; margin: 12px 0 4px;
    color: var(--secondary-text-color); font-size: 0.78rem;
    text-transform: uppercase; letter-spacing: 0.08em;
  }
  .hk-filter-or::before, .hk-filter-or::after {
    content: ''; flex: 1; border-top: 1px solid var(--divider-color);
  }
  .hk-filter-group-add { margin-top: 8px; }
`;
