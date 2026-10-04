import { emptyGroup, GROUP_LISTS, groupActive } from './card-filter';
import type { CompanionOption, FormField } from './forms';
import { filterGroupSchema, groupFormData, toFilterGroup } from './forms';
import { t } from './i18n';
import { MDI_DELETE, MDI_FILTER } from './panel-icons';
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
 * A group is a folded row until it is the one being edited — the same `details` /
 * `summary` accordion a part is drawn as in the appliance editor, and for the same
 * reason: several open forms do not fit on a phone. The summary carries the group's
 * own name and a one-line account of what it selects, so a folded list of groups can
 * still be read as a rule.
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
  /** The heading on group *n*, counted from 1 as the reader sees it. Used when the
   *  group carries no name of its own. */
  title: (n: number) => string;
  add: string;
  remove: string;
  /** The divider between two groups — the operator the profile applies. */
  or: string;
  /** What matching one group means, repeated on each so the rule is where the fields
   *  are rather than only at the top of the section. */
  help: string;
  /** The summary line of a group that constrains nothing yet. */
  empty: string;
  /** The label mode, named on the summary line when a group asks for all of its
   *  labels rather than any of them. */
  labelsAll: string;
  /** The shopping switch, named on the summary line when it is on. */
  excludeShopping: string;
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
  /** Which group starts open. `undefined` lets the default decide (a lone group opens,
   *  a longer list stays folded); `null` is a deliberate "all closed". */
  openIndex?: number | null;
  /** Field labelling. Defaults to the translated panel spelling; the card editor
   *  passes its own English one. */
  computeLabel?: (s: { name: string }) => string;
  computeHelper?: (s: { name: string }) => string;
}

/** The panel's field labels. `labels` is the shared task field, so it keeps that
 *  key space; `name` is the group's own name and not the profile's, so it is named
 *  under `notify.` too; everything else is a filter field named there. */
function defaultComputeLabel(s: { name: string }): string {
  if (s.name === 'labels') return t('field.labels');
  if (s.name === 'name') return t('notify.group_name');
  return t('notify.' + s.name);
}

/**
 * Which group row is expanded. `undefined` (nothing chosen yet) opens a lone group —
 * a new profile's first one — and leaves a longer list folded so the section fits on
 * a phone; `null` is a deliberate "all closed". Never past the end: a group deleted
 * from under the index folds the list rather than opening a stranger.
 *
 * The same rule `openPartIndex` applies to a part row, so the two accordions behave
 * alike wherever a reader meets them.
 */
export function openGroupIndex(chosen: number | null | undefined, count: number): number {
  if (chosen === null) return -1;
  if (chosen !== undefined) return chosen < count ? chosen : -1;
  return count === 1 ? 0 : -1;
}

/**
 * The one line a folded group says about itself: how many ids each of its lists
 * carries, then the two switches that are not lists.
 *
 * Counts rather than names. A group can hold a dozen label ids, and an id is not what
 * the reader called the label anyway — the registry name is only resolvable inside a
 * picker. "Labels 2 · Areas 1" says what shape the rule is, and the row opens to say
 * the rest.
 *
 * The order is `GROUP_LISTS` — the order the form shows the fields in — with the
 * label mode directly after the label count it qualifies, and the shopping switch
 * last. A group that constrains nothing gets *strings.empty* instead, because a blank
 * line beside a name reads as a rule that failed to load.
 */
export function groupSummaryLine(
  group: FilterGroup,
  strings: GroupEditorStrings,
  computeLabel: (s: { name: string }) => string,
): string {
  if (!groupActive(group)) return strings.empty;
  const bits: string[] = [];
  for (const key of GROUP_LISTS) {
    const count = group[key].length;
    if (!count) continue;
    bits.push(`${computeLabel({ name: key })} ${count}`);
    // Directly after the count it changes the meaning of, not at the end of the line.
    if (key === 'labels' && group.labels_match === 'all') bits.push(strings.labelsAll);
  }
  if (group.exclude_shopping) bits.push(strings.excludeShopping);
  return bits.join(' · ');
}

/** Render (or re-render) the whole groups editor into *host*.
 *
 * A re-render clears *host* and rebuilds it. The forms are cheap, the state that
 * matters is the `groups` array the caller owns, and rebuilding is what renumbers the
 * headings and drops the last Delete button when a delete leaves one group behind.
 * Which row is open is the one piece of state a rebuild would lose, so it is held in
 * this call's closure and carried across every re-render it drives. */
export function renderGroupsEditor(
  host: HTMLElement,
  groups: FilterGroup[],
  opts: GroupEditorOptions,
): void {
  const computeLabel = opts.computeLabel ?? defaultComputeLabel;
  // `undefined` = nothing chosen yet, so the default below decides.
  let chosen: number | null | undefined = opts.openIndex;

  const paint = (): void => {
    host.textContent = '';
    const openIdx = openGroupIndex(chosen, groups.length);

    groups.forEach((group, index) => {
      // The operator, between the two things it joins. Decorative: the heading on
      // each group already names it, so a screen reader is not read a bare "OR".
      if (index) {
        const or = document.createElement('div');
        or.className = 'hk-filter-or';
        or.setAttribute('aria-hidden', 'true');
        or.textContent = opts.strings.or;
        host.appendChild(or);
      }
      host.appendChild(groupBox(host, groups, index, index === openIdx, opts, computeLabel, {
        onOpen: (i) => {
          chosen = i;
        },
        onClose: (i) => {
          if (chosen === i) chosen = null;
        },
        onDelete: (i) => {
          groups.splice(i, 1);
          // Follow the list. The deleted row closes, and a row below it keeps the row
          // the reader was in rather than handing the open state to whatever moved
          // into that index. `?? -1` folds "nothing chosen yet" into a number below
          // every index, so an untouched list keeps its default.
          const at = chosen ?? -1;
          if (at >= i) chosen = at === i ? null : at - 1;
          paint();
          opts.onChange([...groups]);
        },
      }));
    });

    const add = document.createElement('ha-button');
    add.className = 'hk-filter-group-add';
    if (opts.addId) add.id = opts.addId;
    setBtnWeight(add, 'secondary');
    add.textContent = opts.strings.add;
    add.addEventListener('click', () => {
      groups.push(emptyGroup());
      // The new row opens on its own: it is the one thing the click asked for, and a
      // folded blank row would have to be found and opened before it could be used.
      chosen = groups.length - 1;
      paint();
      opts.onChange([...groups]);
    });
    host.appendChild(add);
  };

  paint();
}

/** The callbacks one row needs to report what happened to it. */
interface GroupBoxHooks {
  onOpen: (index: number) => void;
  onClose: (index: number) => void;
  onDelete: (index: number) => void;
}

/**
 * One group in the editor: a `details` whose summary names it and says what it
 * selects, and whose body is the group's form and its Delete.
 *
 * Keeps `.hk-filter-group` and `data-group`: the e2e suite and the capture harnesses
 * find groups by them.
 */
function groupBox(
  host: HTMLElement,
  groups: FilterGroup[],
  index: number,
  open: boolean,
  opts: GroupEditorOptions,
  computeLabel: (s: { name: string }) => string,
  hooks: GroupBoxHooks,
): HTMLDetailsElement {
  const group = groups[index];
  const box = document.createElement('details');
  box.className = 'hk-filter-group';
  box.dataset.group = String(index);

  const summary = document.createElement('summary');
  summary.className = 'hk-filter-group-head';
  summary.innerHTML =
    '<ha-svg-icon class="hk-filter-group-ic"></ha-svg-icon>' +
    '<span class="hk-filter-group-text"><span class="hk-filter-group-name"></span>' +
    '<span class="hk-filter-group-sum"></span></span>' +
    '<ha-icon icon="mdi:chevron-down" class="hk-section-chevron"></ha-icon>';
  box.appendChild(summary);
  // ha-svg-icon draws from its `path` property; an `icon` attribute renders nothing.
  const icon = summary.querySelector<HTMLElement & { path?: string }>('.hk-filter-group-ic')!;
  icon.path = MDI_FILTER;
  const nameEl = summary.querySelector<HTMLElement>('.hk-filter-group-name')!;
  const sumEl = summary.querySelector<HTMLElement>('.hk-filter-group-sum')!;
  // Repainted from the form rather than by a re-render, so typing a name never takes
  // the control out from under the reader — the same trick `partBox` uses.
  const updateSummary = (next: FilterGroup): void => {
    nameEl.textContent = next.name || opts.strings.title(index + 1);
    sumEl.textContent = groupSummaryLine(next, opts.strings, computeLabel);
    sumEl.hidden = !sumEl.textContent;
  };
  updateSummary(group);

  const body = document.createElement('div');
  body.className = 'hk-filter-group-body';
  box.appendChild(body);

  const help = document.createElement('div');
  help.className = 'hk-settings-intro';
  help.textContent = opts.strings.help;
  body.appendChild(help);

  body.appendChild(
    opts.makeForm(
      filterGroupSchema(opts.companions),
      groupFormData(group),
      (value) => {
        // Written back into the caller's array by index, so an edit in one group
        // cannot disturb another — and normalized on the way in, since `ha-form`
        // emits a cleared picker as `undefined`.
        const next = toFilterGroup(value);
        groups[index] = next;
        updateSummary(next);
        opts.onChange([...groups]);
      },
      { computeLabel, computeHelper: opts.computeHelper },
    ),
  );

  // No Delete on a lone group: a profile always has one, and an empty group is how
  // "everything" is spelled, so there is nothing a delete there could mean.
  if (groups.length > 1) {
    // At the foot of the open row, not in its summary: a button inside a `summary`
    // toggles the row as well as firing, and the browsers disagree on which first.
    const foot = document.createElement('div');
    foot.className = 'hk-filter-group-foot';
    const del = document.createElement('ha-icon-button');
    del.className = 'hk-filter-group-delete';
    // ha-icon-button draws from its `path` property; an `icon` attribute renders
    // nothing at all (an empty 48px hit area), which is how this first shipped.
    (del as HTMLElement & { path?: string }).path = MDI_DELETE;
    del.setAttribute('title', opts.strings.remove);
    del.setAttribute('aria-label', opts.strings.remove);
    del.addEventListener('click', () => hooks.onDelete(index));
    foot.appendChild(del);
    body.appendChild(foot);
  }

  box.open = open;
  box.addEventListener('toggle', () => {
    if (box.open) {
      hooks.onOpen(index);
      // One at a time. Closing a sibling fires its own toggle, which lands in the
      // branch below with a different index and changes nothing.
      host.querySelectorAll<HTMLDetailsElement>('details.hk-filter-group[open]').forEach((other) => {
        if (other !== box) other.open = false;
      });
    } else {
      hooks.onClose(index);
    }
  });
  return box;
}

/**
 * The groups editor's own styles, included by `panel-styles.ts` and by the card
 * editor's stylesheet — one definition, so a group looks the same wherever it is
 * edited.
 *
 * A group is a folded row in the shape a part is drawn as (`.hk-part` in
 * `panel-styles.ts`): a bordered `details`, a summary of icon, name, summary line and
 * chevron, and a body that only exists while the row is open. The divider is a centred
 * word with a rule running out either side, which is what makes the OR read as joining
 * the two groups rather than labelling the one below it.
 */
// Stryker disable next-line StringLiteral: equivalent — this is a stylesheet, and the
// unit suite runs in jsdom, which computes no styles. Emptying it changes nothing any
// test can observe. The look is checked by the screenshot captures instead.
export const GROUP_EDITOR_CSS = `
  details.hk-filter-group {
    border: 1px solid var(--divider-color); border-radius: 8px;
    margin-top: 8px; padding: 0; overflow: hidden;
  }
  details.hk-filter-group > summary.hk-filter-group-head {
    list-style: none; cursor: pointer; display: flex; align-items: center; gap: 10px;
    padding: 8px 10px 8px 12px; min-height: var(--hk-tap, 48px);
  }
  details.hk-filter-group > summary.hk-filter-group-head::-webkit-details-marker {
    display: none;
  }
  details.hk-filter-group[open] > summary.hk-filter-group-head {
    border-bottom: 1px solid var(--divider-color);
    background: var(--hk-page, var(--secondary-background-color));
  }
  .hk-filter-group-ic {
    flex: none; width: 30px; height: 30px; border-radius: 50%;
    display: inline-flex; align-items: center; justify-content: center;
    background: var(--secondary-background-color); color: var(--secondary-text-color);
    --mdc-icon-size: 18px;
  }
  .hk-filter-group-text {
    flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  }
  .hk-filter-group-name { font-weight: 500; overflow-wrap: anywhere; }
  .hk-filter-group-sum {
    flex: 1 1 100%; font-size: 0.8rem; color: var(--secondary-text-color);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  /* Stated here rather than left to the panel's own \`.hk-section-chevron\`: the card
     editor's stylesheet has only this block, so the chevron would not turn there. */
  details.hk-filter-group > summary .hk-section-chevron {
    flex: none; color: var(--secondary-text-color);
    transition: transform 0.2s ease; transform: rotate(-90deg);
  }
  details.hk-filter-group[open] > summary .hk-section-chevron { transform: rotate(180deg); }
  .hk-filter-group-body { padding: 10px 12px 12px; }
  .hk-filter-group ha-form { display: block; }
  .hk-filter-group .hk-settings-intro { margin: 0 0 8px; }
  .hk-filter-group-foot { display: flex; justify-content: flex-end; margin-top: 4px; }
  .hk-filter-group-delete { color: var(--secondary-text-color); flex: 0 0 auto; }
  .hk-filter-group-delete:hover { color: var(--error-color, #db4437); }
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
