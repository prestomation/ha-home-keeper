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
import { DAY_MS, bucketByKey, isBuyTask, profileMatches } from './card-filter';
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
  renderGroups,
  scopeMatches,
} from './panel-controls';
import type { PanelHost } from './panel-host';
import { TASK_CARD_INLINE_CHIPS } from './panel-styles';
import { LS_TREE_COLLAPSED } from './panel-types';
import type { Asset, Task } from './types';
import {
  areaName,
  assetSummary,
  btnAttrs,
  buildAssetTree,
  deviceName,
  dueLabel,
  escapeHTML,
  formatDate,
  isOverdue,
  recurrenceSummary,
  scanRequired,
  toast,
  type AssetTreeEntry,
} from './utils';

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
      p._filter === 'all' && !activeProfile(p)
        ? ''
        : `<ha-button slot="action" ${btnAttrs('secondary')} id="hk-show-all">${escapeHTML(
            t('tasks.showAll'),
          )}</ha-button>`;
    return `${intro}<ha-alert alert-type="info">${escapeHTML(t('tasks.noMatch'))}${showAll}</ha-alert>`;
  }
  return `${intro}${orphanBanner(p)}${renderGroups(p, groupTasks(p, tasks, now), (task) =>
    taskCard(p, task),
  )}`;
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
  const filtered = p._assets.filter((a) => Boolean(a.archived_at) === archived);
  if (!filtered.length) {
    const emptyKey = archived ? 'appliances.archivedEmpty' : 'appliances.noMatch';
    return `<ha-alert alert-type="info">${escapeHTML(t(emptyKey))}</ha-alert>`;
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
  // An auto-created buy reminder is minted as a one-off with no due date, and a
  // dateless one-off is due *now* — so it is technically overdue from the moment a
  // part goes low, and "Overdue by 3 days" on it means "low for 3 days". Reading it
  // as late work is what put these rows beside genuinely late maintenance, so the
  // row drops the danger treatment and says what is actually true: low stock. It is
  // still overdue everywhere that counts tasks, so no count moves.
  const buy = isBuyTask(task);
  const overdue = isOverdue(task) && !buy;
  const dev = task.device_id ? deviceChip(p, task.device_id) : '';
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
  // For an overdue task, append *how* overdue it is — a bare date hides urgency. Use
  // whole elapsed days (floor), and only once at least one full day has passed: a
  // task overdue by mere hours reads as "Overdue" alone rather than an inflated
  // "1 day overdue".
  const overdueDays = task.next_due
    ? Math.floor((Date.now() - new Date(task.next_due).getTime()) / DAY_MS)
    : 0;
  // How overdue it is now rides the right-hand status pill rather than the meta line,
  // so urgency reads at the end of the row instead of buried mid-sentence. Under a
  // full day it stays the bare "Overdue" — "1 day overdue" would overstate it.
  const statusChip = buy
    ? `<ha-assist-chip class="hk-shopping" label="${escapeHTML(t('chip.lowStock'))}"></ha-assist-chip>`
    : overdue
      ? `<ha-assist-chip class="hk-overdue" label="${escapeHTML(
          overdueDays >= 1 ? tn('due.overdue_by', overdueDays) : t('chip.overdue'),
        )}"></ha-assist-chip>`
      : `<ha-assist-chip label="${escapeHTML(dueLabel(task, undefined, p._hass))}"></ha-assist-chip>`;
  const n = task.completions?.length ?? 0;
  // A dormant triggered task (monitored, not due) has nothing to mark done — its
  // owning integration arms it when the condition fires; hide the action. A
  // completed one-off is already done, so it too hides Done. A completion-blocked
  // task (e.g. a synced problem sensor) keeps a *disabled* Done that explains why
  // on click, rather than silently offering no action.
  const dormantTriggered = task.recurrence_type === 'triggered' && !task.next_due;
  // A scan-locked task keeps a *disabled* Done rather than the auto-clear caption:
  // it is still completable, just not from here, so a greyed button that explains
  // itself on tap is the honest affordance.
  const doneAction = dormantTriggered || completedOneOff
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
            ${doneAction}
          </div>
        </div>
      </ha-card>`;
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
  const subCount = p._assets.filter((a) => a.parent_asset_id === x.id).length;
  const relCount = x.related_device_ids?.length ?? 0;
  const extra = [
    subCount
      ? `<ha-assist-chip label="${escapeHTML(tn('asset.subdevices', subCount))}"></ha-assist-chip>`
      : '',
    relCount
      ? `<ha-assist-chip label="${escapeHTML(tn('asset.related', relCount))}"></ha-assist-chip>`
      : '',
    x.parent_asset_id
      ? `<ha-assist-chip label="${escapeHTML(
          '↳ ' + assetAncestry(p, x.parent_asset_id),
        )}"></ha-assist-chip>`
      : '',
    x.archived_at
      ? `<ha-assist-chip class="hk-archived" label="${escapeHTML(t('chip.archived'))}"></ha-assist-chip>`
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
        <div class="hk-card-row">
          <div class="grow clickable detail-open" data-detail-kind="asset" data-detail-id="${escapeHTML(x.id)}" role="button" tabindex="0">
            <div class="hk-name">${escapeHTML(title)}</div>
            <div class="hk-meta">${escapeHTML(assetSummary(x, p._hass?.areas))}</div>
            <div class="hk-chips">${kindChip}${extra}</div>
          </div>
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
export function wireLists(p: PanelHost, root: ShadowRoot): void {
  root
    .getElementById('cleanup-orphans-btn')
    ?.addEventListener('click', () => void cleanupOrphans(p));

  // The way out of a filter that matches nothing: clears the scope *and* any active
  // Profile, since either can be what emptied the list.
  root.getElementById('hk-show-all')?.addEventListener('click', () => {
    if (activeProfile(p)) p._setProfile('');
    p._setFilter('all');
  });

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
