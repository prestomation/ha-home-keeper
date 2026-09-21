/**
 * The two lists the panel opens on — tasks and appliances — and the cards they are
 * made of: the first-run intro banner, the orphaned-integration banner and its
 * cleanup, the flat/tree appliance layout, and the one wiring pass that makes a row's
 * quick actions live.
 *
 * The cards render the chip vocabulary from `panel-chips.ts` and are arranged by the
 * grouping glue in `panel-controls.ts`; what is here is the row itself — what a task
 * or an appliance says about itself in a list, and which of its actions ride along.
 *
 * Everything is a free function over a `PanelHost` (see `panel-host.ts`).
 */

import * as api from './api';
import { assetMatchesQuery, bucketByKey, profileMatches, taskMatchesQuery } from './card-filter';
import { makeDialog } from './dialogs';
import { t, tn } from './i18n';
import {
  deviceChip,
  isManagedOrphan,
  managedChip,
  tagChip,
  taskChipsList,
  virtualDeviceChip,
} from './panel-chips';
import {
  activeProfile,
  effectiveGroup,
  groupAssets,
  groupTasks,
  renderBoard,
  renderGroups,
  scopeMatches,
} from './panel-controls';
import { deferMenu, openSkip, openSnooze, setDueToday, verbsFor } from './panel-defer';
import type { PanelHost } from './panel-host';
import { TASK_CARD_INLINE_CHIPS } from './panel-styles';
import { LS_TREE_COLLAPSED } from './panel-types';
import {
  sheetActions,
  sheetFlags,
  shortDueLabel,
  urgencyClass,
  type SheetAction,
} from './task-layout';
import type { Asset, Task } from './types';
import {
  areaName,
  assetForTask,
  assetSummary,
  btnAttrs,
  buildAssetTree,
  deviceName,
  escapeHTML,
  formatDate,
  isBuyTask,
  isMonitoredDormant,
  isOverdue,
  recurrenceSummary,
  scanRequired,
  countedProgress,
  setBtnWeight,
  statusChipHtml,
  statusText,
  toast,
  type AssetTreeEntry,
} from './utils';

/** A press held at least this long opens the task's page rather than its action
 *  sheet — the same threshold the dashboard card uses for its own press and hold
 *  (see `card.ts`). */
const HOLD_MS = 500;

/** One-time orientation banner that explains the kinds of tasks a newcomer will see
 *  mixed in the list. Dismissed permanently, server-side per-user (see
 *  `_introDismissed`). Empty once dismissed. */
function introCard(p: PanelHost): string {
  if (p._introDismissed) return '';
  return `
      <div class="hk-intro">
        <div class="hk-intro-head">
          <div class="hk-form-title">${escapeHTML(t('tasks.intro.title'))}</div>
          <ha-icon-button class="hk-intro-dismiss" label="${escapeHTML(
            t('tasks.intro.dismiss'),
          )}"><ha-icon icon="mdi:close"></ha-icon></ha-icon-button>
        </div>
        <div class="hk-intro-body">${escapeHTML(t('tasks.intro.body'))}</div>
        <ul>
          <li>${t('tasks.intro.recurring')}</li>
          <li>${t('tasks.intro.monitored')}</li>
          <li>${t('tasks.intro.companion')}</li>
        </ul>
        <ha-button ${btnAttrs('tertiary')} class="hk-intro-dismiss">${escapeHTML(t('tasks.intro.dismiss'))}</ha-button>
      </div>`;
}

export function tasksList(p: PanelHost): string {
  const intro = introCard(p);
  if (!p._tasks.length) {
    const addTask = `<b>${escapeHTML(t('btn.addTask'))}</b>`;
    return `${intro}<ha-alert alert-type="info">${t('tasks.empty', { addTask })}</ha-alert>`;
  }
  const now = Date.now();
  let tasks = [...p._tasks];
  const profile = activeProfile(p);
  if (profile) {
    // A saved Profile replaces the inline filter: status + labels/areas/devices.
    tasks = tasks.filter((task) =>
      profileMatches(task, profile.filter, p._hass?.devices, p._hass?.areas, now),
    );
  } else {
    tasks = tasks.filter((task) => scopeMatches(task, p._filter, now));
  }
  // The text filter narrows whichever of the two chose the set, rather than replacing
  // it: a Profile plus a word is how a household finds one task among its own.
  if (p._query) {
    tasks = tasks.filter((task) =>
      taskMatchesQuery(task, p._query, p._hass?.devices, p._hass?.areas),
    );
  }
  tasks.sort((a, b) => {
    const ad = a.next_due ? new Date(a.next_due).getTime() : Infinity;
    const bd = b.next_due ? new Date(b.next_due).getTime() : Infinity;
    return ad - bd;
  });
  if (!tasks.length) {
    // Closing the loop the other way: an empty result carries the way back to the
    // full list, so the dead end is escapable even when it was a Profile rather
    // than a scope pill that emptied it.
    const showAll =
      p._filter === 'all' && !profile && !p._query
        ? ''
        : `<ha-button slot="action" ${btnAttrs('secondary')} id="hk-show-all">${escapeHTML(
            t('tasks.showAll'),
          )}</ha-button>`;
    return `${intro}<ha-alert alert-type="info">${escapeHTML(t('tasks.noMatch'))}${showAll}</ha-alert>`;
  }
  const groups = groupTasks(p, tasks, now);
  const head = `${intro}${orphanBanner(p)}`;
  if (p._taskLayout === 'tiles') {
    return `${head}${renderGroups(p, groups, (task) => taskTile(p, task), 'hk-tiles')}`;
  }
  if (p._taskLayout === 'board') {
    return `${head}${renderBoard(groups, (task) => boardCard(p, task))}`;
  }
  return `${head}${renderGroups(p, groups, (task) => taskCard(p, task))}`;
}

/**
 * A dismissable-style warning shown above the task list when one or more managed
 * tasks have been orphaned (their integration was uninstalled/disabled). Offers a
 * one-click "Remove orphaned tasks" cleanup so the user isn't stuck with tasks no
 * integration owns any more.
 */
function orphanBanner(p: PanelHost): string {
  const n = p._tasks.filter((task) => isManagedOrphan(p, task)).length;
  if (!n) return '';
  return `
      <ha-alert alert-type="warning" class="hk-orphan-banner">
        ${escapeHTML(tn('managed.orphanBanner', n))}
        <ha-button slot="action" ${btnAttrs('danger')} id="cleanup-orphans-btn">${escapeHTML(
          t('btn.removeOrphaned'),
        )}</ha-button>
      </ha-alert>`;
}

/** Delete every orphaned managed task (the bulk cleanup action). */
async function cleanupOrphans(p: PanelHost): Promise<void> {
  if (!p._hass) return;
  const orphans = p._tasks.filter((task) => isManagedOrphan(p, task));
  if (!orphans.length) return;
  try {
    for (const task of orphans) await api.deleteTask(p._hass, task.id);
  } catch (err) {
    toast(p, String((err as { message?: string })?.message || err));
  }
  await p._refresh();
}

export function assetsList(p: PanelHost): string {
  if (!p._assets.length) {
    return `<ha-alert alert-type="info">${escapeHTML(t('appliances.empty'))}</ha-alert>`;
  }
  const archived = p._assetFilter === 'archived';
  let filtered = p._assets.filter((a) => Boolean(a.archived_at) === archived);
  if (p._query) {
    filtered = filtered.filter((a) =>
      assetMatchesQuery(a, p._query, p._hass?.devices, p._hass?.areas),
    );
  }
  if (!filtered.length) {
    // An empty Archived scope is a fact about the data. A scope emptied by something
    // the reader typed is a dead end, and gets the same way out the task list has had
    // since #262 — clearing the text only, because someone standing on Archived chose
    // to be there.
    const emptyKey = archived && !p._query ? 'appliances.archivedEmpty' : 'appliances.noMatch';
    const showAll = p._query
      ? `<ha-button slot="action" ${btnAttrs('secondary')} id="hk-show-all">${escapeHTML(
          t('appliances.showAll'),
        )}</ha-button>`
      : '';
    return `<ha-alert alert-type="info">${escapeHTML(t(emptyKey))}${showAll}</ha-alert>`;
  }
  const cmp = (a: Asset, b: Asset) => (a.name || '').localeCompare(b.name || '');
  if (p._assetView === 'tree') {
    const tree = buildAssetTree(filtered, cmp);
    const renderEntries = (entries: AssetTreeEntry<Asset>[]): string => {
      const sub = (start: number, parentDepth: number): [string, number] => {
        let html = '';
        let i = start;
        while (i < entries.length && entries[i].depth > parentDepth) {
          const entry = entries[i];
          const depth = entry.depth;
          const hasChildren = i + 1 < entries.length && entries[i + 1].depth > depth;
          if (hasChildren) {
            const [childrenHtml, nextI] = sub(i + 1, depth);
            const isOpen = !p._treeCollapsed.has(entry.item.id);
            html += `<div class="hk-tree-group${isOpen ? ' hk-tree-open' : ''}">
                ${assetCard(p, entry.item, depth, false, entry.item.id)}
                <div class="hk-tree-children">${childrenHtml}</div>
              </div>`;
            i = nextI;
          } else {
            i++;
            html += assetCard(p, entry.item, depth);
          }
        }
        return [html, i];
      };
      const [html] = sub(0, -1);
      return html;
    };
    if (effectiveGroup(p) === 'area') {
      const chunks: Array<{ root: Asset; entries: AssetTreeEntry<Asset>[] }> = [];
      for (let i = 0; i < tree.length; ) {
        const rootEntry = tree[i];
        let j = i + 1;
        while (j < tree.length && tree[j].depth > rootEntry.depth) j++;
        chunks.push({ root: rootEntry.item, entries: tree.slice(i, j) });
        i = j;
      }
      const areaGroups = bucketByKey(
        chunks,
        (c) => c.root.area_id ?? undefined,
        (id) => areaName(p._hass?.areas, id),
        t('section.unassigned'),
        'area',
      );
      return renderGroups(p, areaGroups, (c) => renderEntries(c.entries));
    }
    return renderEntries(tree);
  }
  const assets = [...filtered].sort(cmp);
  return renderGroups(p, groupAssets(p, assets), (asset) => assetCard(p, asset));
}

function taskCard(p: PanelHost, task: Task): string {
  // The danger rail follows the status pill: a buy reminder reads "Low stock" rather
  // than "Overdue" (see `statusChipHtml`), so it must not also carry the red edge that
  // says this work is late.
  const overdue = isOverdue(task) && !isBuyTask(task);
  // The chip opens the appliance the task is about, not the Home Assistant device
  // page behind it — see `deviceChip`. The appliance page's own chip is the one hop
  // on to the device.
  const dev = task.device_id
    ? deviceChip(p, task.device_id, assetForTask(task, p._assets)?.id)
    : '';
  const tag = tagChip(p, task);
  const managed = managedChip(p, task);
  // A completed one-off (do-once, now dormant) shows when it was done instead of a
  // due date.
  const completedOneOff =
    task.recurrence_type === 'one-off' && !task.next_due && !!task.last_completed;
  const dueText = task.next_due
    ? ` · ${escapeHTML(t('form.task.due', { date: formatDate(task.next_due, p._lang()) }))}`
    : completedOneOff
      ? ` · ${escapeHTML(t('form.task.completedOn', { date: formatDate(task.last_completed, p._lang()) }))}`
      : '';
  // How overdue it is rides the right-hand status pill rather than the meta line, so
  // urgency reads at the end of the row instead of buried mid-sentence. `elapsed` is
  // the list row's alone: down a long list the count is what separates a week late
  // from an hour late, where a detail page already shows the date.
  const statusChip = statusChipHtml(task, p._hass, {
    elapsed: true,
    counted: countedProgress(task, p._assets, p._tasks),
  });
  const n = task.completions?.length ?? 0;
  // A monitored task (dormant, not due) has nothing to mark done — its owning
  // integration or the sensor watcher arms it when the condition fires; hide the
  // action. A completed one-off is already done, so it too hides Done. A
  // completion-blocked task (e.g. a synced problem sensor) keeps a *disabled* Done
  // that explains why on click, rather than silently offering no action.
  const monitored = isMonitoredDormant(task);
  // A scan-locked task keeps a *disabled* Done rather than the auto-clear caption:
  // it is still completable, just not from here, so a greyed button that explains
  // itself on tap is the honest affordance.
  const doneAction = monitored || completedOneOff
    ? ''
    : task.managed_by?.completion_blocked
      ? p._blockedDoneInline(task)
      : scanRequired(task)
        ? p._blockedDone('', task)
        : // Tonal, not solid: every row carries a Done, and a page of solid accent
          // buttons leaves the surface with no single primary action.
          `<ha-button ${btnAttrs('secondary')} class="done-btn" data-id="${escapeHTML(task.id)}">${escapeHTML(t('btn.done'))}</ha-button>`;
  // Descriptive chips (device, tag, integration) belong beside the name — they say
  // *what* this task is about, which is part of reading the title. Only the first two
  // are shown, with a "+n" for the rest; every chip stays in the DOM and the overflow
  // is hidden in CSS, so the row's contents remain inspectable and testable.
  //
  // "+n" is a button, not a caption. Most of these chips do something when clicked —
  // a device chip opens the device page, an integration-supplied chip opens its URL —
  // so folding them behind a caption would put an action one navigation away that
  // used to be one click. It unfolds the row in place instead.
  const inlineChips = [dev, tag, ...taskChipsList(task), managed].filter(Boolean);
  const hiddenChips = Math.max(0, inlineChips.length - TASK_CARD_INLINE_CHIPS);
  const chipsOpen = !!task.id && p._chipsExpanded.has(task.id);
  const more = hiddenChips
    ? `<button class="hk-chip-more" data-chips-more="${escapeHTML(task.id)}" aria-expanded="${
        chipsOpen ? 'true' : 'false'
      }" title="${escapeHTML(t('chip.showAll'))}">${chipsOpen ? '−' : `+${hiddenChips}`}</button>`
    : '';
  // While the drawer is editing this task, the row stays lit and undimmed so the
  // thing being edited is visible next to the form editing it.
  const editing = p._edit.open && !!task.id && p._edit.task?.id === task.id;
  // The row opens the task's detail page; "Done" stays as a quick action.
  return `
      <ha-card class="hk-card${overdue ? ' overdue' : ''}${editing ? ' hk-editing' : ''}${
        completedOneOff ? ' hk-task-done' : ''
      }" data-id="${escapeHTML(task.id)}">
        <div class="hk-card-row hk-row-task">
          <div class="grow clickable detail-open" data-detail-kind="task" data-detail-id="${escapeHTML(task.id)}" role="button" tabindex="0">
            <div class="hk-name"><span class="hk-name-text">${escapeHTML(task.name)}</span></div>
            <div class="hk-meta">${escapeHTML(recurrenceSummary(task))}${dueText}${n ? ` · ${escapeHTML(tn('history.count', n))}` : ''}</div>
          </div>
          <div class="hk-chips hk-chips-inline${chipsOpen ? ' hk-chips-open' : ''}">${inlineChips.join('')}${more}</div>
          <span class="hk-row-spacer"></span>
          <div class="hk-status">${statusChip}</div>
          <div class="hk-card-actions">
            ${deferMenu(p, task, doneAction, 'secondary')}
          </div>
        </div>
      </ha-card>`;
}

/**
 * A task as a tile: the name over its status pill, and nothing else.
 *
 * Three to a row on a desktop and two on a phone, so a household sees a whole
 * week of work without scrolling. Everything the list row carries inline — the
 * chips, the meta line, Done and its caret — moves into the action sheet a press
 * opens (see `openActionSheet`), because none of it fits and a tile that offered
 * half of it would be a smaller row rather than a different layout.
 *
 * The tile is one press target, so it announces itself as a button whose label
 * names the task and its status. The left rail colours it the way the row's does.
 */
function taskTile(p: PanelHost, task: Task): string {
  const opts = { elapsed: true, counted: countedProgress(task, p._assets, p._tasks) };
  const urgency = urgencyClass(task);
  const aria = escapeHTML(
    t('layout.cardAria', { name: task.name, status: statusText(task, p._hass, opts) }),
  );
  return `
      <ha-card class="hk-card hk-tile hk-press${urgency ? ` ${urgency}` : ''}" data-id="${escapeHTML(
        task.id,
      )}" role="button" tabindex="0" aria-label="${aria}">
        <div class="hk-name"><span class="hk-name-text">${escapeHTML(task.name)}</span></div>
        <div class="hk-status">${statusChipHtml(task, p._hass, opts)}</div>
      </ha-card>`;
}

/**
 * A task as a board card: a dot, the name, and the due text in a few characters.
 *
 * A column is 220px wide, so this is the densest the panel draws a task. The
 * status pill does not fit beside a name, so urgency moves to the dot and the
 * date to `shortDueLabel`. The full status still reaches a screen reader through
 * the card's own label, which is the same label a tile carries.
 */
function boardCard(p: PanelHost, task: Task): string {
  const opts = { elapsed: true, counted: countedProgress(task, p._assets, p._tasks) };
  const status = statusText(task, p._hass, opts);
  const aria = escapeHTML(t('layout.cardAria', { name: task.name, status }));
  const urgency = urgencyClass(task);
  return `
      <button type="button" class="hk-bcard hk-press${urgency ? ` ${urgency}` : ''}" data-id="${escapeHTML(
        task.id,
      )}" role="button" tabindex="0" aria-label="${aria}">
        <span class="hk-bdot" aria-hidden="true"></span>
        <span class="hk-bname">${escapeHTML(task.name)}</span>
        <span class="hk-bdue">${escapeHTML(shortDueLabel(task))}</span>
      </button>`;
}

/** Open the action sheet for *task*. */
export function openActionSheet(p: PanelHost, task: Task): void {
  p._actionSheet = { open: true, task };
  p._render();
}

/** Close the action sheet. */
export function closeActionSheet(p: PanelHost): void {
  p._actionSheet = { open: false, task: null };
  p._render();
}

/** The icon and the label each sheet row carries. */
const SHEET_ROWS: Record<SheetAction['id'], { icon: string; key: string }> = {
  done: { icon: 'mdi:check-circle-outline', key: 'btn.done' },
  snooze: { icon: 'mdi:clock-outline', key: 'btn.snooze' },
  skip: { icon: 'mdi:skip-next-outline', key: 'btn.skip' },
  dueToday: { icon: 'mdi:calendar-today', key: 'btn.dueToday' },
  open: { icon: 'mdi:open-in-new', key: 'btn.openTask' },
};

/**
 * Build the action sheet for the pressed tile or board card into *host*.
 *
 * The rows are whatever `sheetActions` allows, which is the same set of guards
 * the list row's Done and its deferral caret apply — so a compact layout never
 * offers an action the row withholds. A blocked Done stays on the sheet and
 * explains itself, because "this task cannot be completed here" is what the
 * person pressing it needs to be told.
 */
export function renderActionSheet(p: PanelHost, host: HTMLElement): void {
  const task = p._actionSheet.task;
  if (!task) return;
  const { dialog, body, footer, mount } = makeDialog(task.name, () => {
    if (p._actionSheet.open) closeActionSheet(p);
  });
  body.classList.add('hk-sheet');

  const run = (action: SheetAction): void => {
    if (action.id === 'done') {
      if (action.blocked) p._notifyBlocked(task);
      else void p._complete(task);
      return;
    }
    if (action.id === 'snooze') return openSnooze(p, task);
    if (action.id === 'skip') return openSkip(p, task);
    if (action.id === 'dueToday') return void setDueToday(p, task);
    p._openDetail('task', task.id);
  };

  for (const action of sheetActions(verbsFor(p, task), sheetFlags(task))) {
    const { icon, key } = SHEET_ROWS[action.id];
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `hk-sheet-row${action.blocked ? ' hk-sheet-blocked' : ''}`;
    btn.dataset.action = action.id;
    // Blocked, not disabled: a disabled button is skipped by a screen reader and
    // says nothing on a tap, and the explanation is the whole point of the row.
    if (action.blocked) btn.setAttribute('aria-disabled', 'true');
    btn.innerHTML = `<ha-icon icon="${escapeHTML(icon)}"></ha-icon><span>${escapeHTML(t(key))}</span>`;
    btn.addEventListener('click', () => {
      closeActionSheet(p);
      run(action);
    });
    body.appendChild(btn);
  }

  const cancel = document.createElement('ha-button');
  cancel.setAttribute('slot', 'secondaryAction');
  setBtnWeight(cancel, 'tertiary');
  cancel.textContent = t('btn.cancel');
  cancel.addEventListener('click', () => closeActionSheet(p));
  footer.appendChild(cancel);

  mount();
  host.appendChild(dialog);
}

/**
 * Wire the tiles and the board cards: a press opens the action sheet, a press
 * held past `HOLD_MS` opens the task's page instead.
 *
 * Same timing and the same cancelling pointer events as the dashboard card's own
 * press and hold (`card.ts`). There is no `pointermove` cancel: a finger never
 * holds perfectly still, and a real scroll sends `pointercancel` anyway.
 *
 * `_applyQuery` replaces the whole list, so a timer armed on a card that has
 * since left the DOM would open the page of a task nobody is pressing. The
 * connection check in the timer is what stops that.
 */
export function wirePressCards(p: PanelHost, root: ParentNode): void {
  root.querySelectorAll<HTMLElement>('.hk-press').forEach((card) => {
    let timer: number | undefined;
    let held = false;
    const taskOf = (): Task | undefined => p._tasks.find((x) => x.id === card.dataset.id);
    const cancelTimer = (): void => {
      if (timer !== undefined) window.clearTimeout(timer);
      timer = undefined;
      card.classList.remove('hk-pressing');
    };
    card.addEventListener('pointerdown', () => {
      held = false;
      card.classList.add('hk-pressing');
      timer = window.setTimeout(() => {
        if (!card.isConnected) return;
        held = true;
        card.classList.remove('hk-pressing');
        const task = taskOf();
        if (task) p._openDetail('task', task.id);
      }, HOLD_MS);
    });
    for (const evt of ['pointerup', 'pointerleave', 'pointercancel']) {
      card.addEventListener(evt, cancelTimer);
    }
    const activate = (): void => {
      // The click that ends a hold must not also open the sheet on top of the
      // page the hold just opened.
      if (held) {
        held = false;
        return;
      }
      const task = taskOf();
      if (task) openActionSheet(p, task);
    };
    card.addEventListener('click', activate);
    card.addEventListener('keydown', (e) => {
      const key = (e as KeyboardEvent).key;
      if (key === 'Enter' || key === ' ') {
        e.preventDefault();
        activate();
      }
    });
  });
}

function assetCard(p: PanelHost, x: Asset, depth = 0, isLast = false, toggleId = ''): string {
  const kindChip =
    x.kind === 'virtual'
      ? virtualDeviceChip(p, x)
      // The no-device branch reached `deviceName(devices, undefined)`, which is
      // always '' — so an appliance with no device carried a nameless empty chip.
      // Matches the detail page, which has always rendered nothing here.
      : x.device_id
        ? deviceChip(p, x.device_id)
        : '';
  const title =
    x.name || deviceName(p._hass?.devices, x.device_id) || t('appliance.fallbackName');
  // Split the way a task row splits. What the appliance *is* — its device, where it
  // hangs, whether it is retired — reads beside the name; what it *holds* reads in the
  // status rail, the same column a task's due pill lands in. One grammar for both
  // lists, so a chip sits at the same x whichever tab you are on.
  const qualifiers = [
    kindChip,
    x.parent_asset_id
      ? `<ha-assist-chip label="${escapeHTML(
          '↳ ' + assetAncestry(p, x.parent_asset_id),
        )}"></ha-assist-chip>`
      : '',
    x.archived_at
      ? `<ha-assist-chip class="hk-archived" label="${escapeHTML(t('chip.archived'))}"></ha-assist-chip>`
      : '',
  ].join('');
  const subCount = p._assets.filter((a) => a.parent_asset_id === x.id).length;
  const relCount = x.related_device_ids?.length ?? 0;
  const counts = [
    subCount
      ? `<ha-assist-chip label="${escapeHTML(tn('asset.subdevices', subCount))}"></ha-assist-chip>`
      : '',
    relCount
      ? `<ha-assist-chip label="${escapeHTML(tn('asset.related', relCount))}"></ha-assist-chip>`
      : '',
  ].join('');
  const depthClass = depth > 0 ? ' hk-tree-child' : '';
  const depthStyle = depth > 0 ? ` style="--hk-tree-depth: ${depth}"` : '';
  const chevron = toggleId
    ? `<span class="hk-chevron" data-tree-toggle="${escapeHTML(toggleId)}"></span>`
    : '';
  // In the master pane the list doubles as a picker, so the appliance on screen
  // beside it is marked.
  const selected =
    p._detail?.kind === 'asset' && p._detail.id === x.id ? ' hk-selected' : '';
  return `
      <ha-card class="hk-card${depthClass}${selected}" data-id="${escapeHTML(x.id)}"${depthStyle}>
        ${chevron}
        <div class="hk-card-row hk-row-asset">
          <div class="grow clickable detail-open" data-detail-kind="asset" data-detail-id="${escapeHTML(x.id)}" role="button" tabindex="0">
            <div class="hk-name">${escapeHTML(title)}</div>
            <div class="hk-meta">${escapeHTML(assetSummary(x, p._hass?.areas))}</div>
          </div>
          <div class="hk-chips">${qualifiers}</div>
          <div class="hk-status">${counts}</div>
        </div>
      </ha-card>`;
}

export function assetName(p: PanelHost, assetId: string): string {
  return p._assets.find((a) => a.id === assetId)?.name || assetId;
}

export function assetAncestry(p: PanelHost, assetId: string): string {
  const path: string[] = [];
  const seen = new Set<string>();
  let cur: string | null = assetId;
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    const a = p._assets.find((x) => x.id === cur);
    if (!a) break;
    path.unshift(a.name || cur);
    cur = a.parent_asset_id ?? null;
  }
  return path.join(' › ');
}

/**
 * Wire the list surfaces: the orphan cleanup, the empty state's way back out, the
 * tree's expand/collapse, a row's quick Done (and the caption that stands in for one
 * a source owns), the intro banner's dismiss, and the "+n" chip unfold.
 */
export function wireLists(p: PanelHost, root: ParentNode): void {
  root
    .querySelector<HTMLElement>('#cleanup-orphans-btn')
    ?.addEventListener('click', () => void cleanupOrphans(p));

  // The way out of a filter that matches nothing: clears the text, the scope *and*
  // any active Profile, since any of the three can be what emptied the list.
  root.querySelector<HTMLElement>('#hk-show-all')?.addEventListener('click', () => {
    // Text first. On its own that is a patch, so the common case renders once; a
    // scope or Profile change after it then renders with the text already gone,
    // rather than painting the old query's list on the way through.
    p._setQuery('');
    // The scope pills and the Profile picker belong to the task list. The appliance
    // list reaches this button too, and its own scope is a deliberate choice.
    if (p._view !== 'tasks') return;
    if (activeProfile(p)) p._setProfile('');
    p._setFilter('all');
  });

  // Remember which group sections the user collapsed (no re-render needed). These
  // `<details>` come from `renderGroups`, which only ever runs inside the list — so
  // they are rebuilt whenever the list is, and belong to this pass rather than to
  // `wireControls` beside it.
  root.querySelectorAll<HTMLDetailsElement>('details.hk-group').forEach((d) =>
    d.addEventListener('toggle', () => {
      // A search forces every section open (see `renderGroups`), so while one is
      // running the open state is not a choice anybody made and must not overwrite
      // the choice they made before it.
      if (p._query) return;
      const key = d.dataset.groupKey || '';
      if (d.open) p._collapsed.delete(key);
      else p._collapsed.add(key);
    }),
  );

  // Tree view: expand/collapse parent groups.
  root.querySelectorAll<HTMLElement>('.hk-chevron[data-tree-toggle]').forEach((ch) =>
    ch.addEventListener('click', (e) => {
      e.stopPropagation();
      const group = ch.closest('.hk-tree-group');
      if (group) group.classList.toggle('hk-tree-open');
      const id = ch.dataset.treeToggle;
      if (id) {
        if (p._treeCollapsed.has(id)) p._treeCollapsed.delete(id);
        else p._treeCollapsed.add(id);
        try { localStorage.setItem(LS_TREE_COLLAPSED, JSON.stringify([...p._treeCollapsed])); } catch { /* quota */ }
      }
    }),
  );

  if (p._view === 'tasks') {
    root.querySelectorAll<HTMLElement>('.done-btn').forEach((b) =>
      b.addEventListener('click', () => {
        const task = p._tasks.find((x) => x.id === b.dataset.id);
        if (task) void p._complete(task);
      }),
    );
    // One caret per row, each resolving its own task.
    p._wireDeferMenus(root);
    // Tiles and board cards carry their actions in a sheet instead of on the card.
    if (p._taskLayout !== 'rows') wirePressCards(p, root);
    root.querySelectorAll<HTMLElement>('.hk-intro-dismiss').forEach((b) =>
      b.addEventListener('click', () => {
        p._introDismissed = true;
        p._render();
        if (p._hass) {
          void api.setIntroDismissed(p._hass).catch(() => {
            // best-effort — if this fails the banner simply reappears next load.
          });
        }
      }),
    );
  }
  // A completion-blocked Done (card row or detail) explains why on click rather
  // than completing — its source clears it.
  root.querySelectorAll<HTMLElement>('.done-blocked-wrap').forEach((b) =>
    b.addEventListener('click', () => {
      const task = p._tasks.find((x) => x.id === b.dataset.id);
      if (task) p._notifyBlocked(task);
    }),
  );
  // "+n" unfolds a row's hidden chips in place. Toggling a class on the row rather
  // than re-rendering keeps the list's scroll position and every other row's state.
  root.querySelectorAll<HTMLElement>('.hk-chip-more').forEach((btn) =>
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = btn.dataset.chipsMore;
      if (!id) return;
      const chips = btn.closest('.hk-chips-inline');
      const open = !p._chipsExpanded.has(id);
      if (open) p._chipsExpanded.add(id);
      else p._chipsExpanded.delete(id);
      chips?.classList.toggle('hk-chips-open', open);
      btn.setAttribute('aria-expanded', String(open));
      btn.textContent = open
        ? '−'
        : `+${Math.max(0, (chips?.children.length ?? 1) - 1 - TASK_CARD_INLINE_CHIPS)}`;
    }),
  );
}
