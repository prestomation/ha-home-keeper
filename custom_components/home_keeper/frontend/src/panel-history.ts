/**
 * The completion-history region: the groups a detail page shows, the markup that
 * renders them, and the per-row delete/edit/move wiring — plus the three small
 * DOM helpers (`section`, `collapsibleSection`, `setIcon`) the detail pages and the
 * appliance editor build their chrome from, which came out with it.
 *
 * Everything here is a free function over a `PanelHost` (see `panel-host.ts`): the
 * panel calls `historyBody(this, groups)` where it used to call a method, and the
 * region reaches back through the declared interface rather than the whole class.
 */

import * as api from './api';
import { t, tn } from './i18n';
import { markdownBlock } from './markdown';
import { openCompletionEdit, openMoveCompletion } from './panel-dialogs';
import type { PanelHost } from './panel-host';
import { MDI_DELETE, MDI_EDIT, MDI_MOVE_DATE } from './panel-icons';
import type { HistoryGroup } from './panel-types';
import type { Completion } from './types';
import {
  completionStats,
  escapeHTML,
  formatCost,
  formatDate,
  isSafeImageUrl,
  personName,
  readingUnit,
  relativeDay,
  round1,
  tasksForAsset,
  toast,
} from './utils';

/**
 * Completion groups for the detail page's history section. For a task: its own
 * completions. For an appliance: every completion tied to it — live related
 * tasks (part-derived or device-attached) plus the history archived from tasks
 * deleted while still assigned to it — newest activity first.
 */
export function completionGroupsFor(
  p: PanelHost,
  kind: 'task' | 'asset',
  id: string,
): HistoryGroup[] {
  if (kind === 'task') {
    const task = p._tasks.find((t) => t.id === id);
    if (!task) return [];
    return [{ name: task.name, completions: task.completions || [], taskId: task.id }];
  }
  const asset = p._assets.find((a) => a.id === id);
  if (!asset) return [];
  const groups: HistoryGroup[] = tasksForAsset(asset, p._tasks).map((task) => ({
    name: task.name,
    completions: task.completions || [],
    taskId: task.id,
  }));
  for (const entry of asset.task_history || []) {
    groups.push({
      name: entry.task_name,
      completions: entry.completions || [],
      archived: true,
      assetId: asset.id,
      archivedTaskId: entry.task_id,
    });
  }
  const lastTs = (g: HistoryGroup): number =>
    g.completions.reduce((m, c) => Math.max(m, new Date(c.ts).getTime() || 0), 0);
  groups.sort((a, b) => lastTs(b) - lastTs(a));
  return groups;
}

async function deleteCompletion(p: PanelHost, taskId: string, ts: string): Promise<void> {
  if (!p._hass) return;
  try {
    await api.deleteCompletion(p._hass, taskId, ts);
  } catch (err) {
    console.error('home-keeper: delete completion failed', err);
    toast(p, t('error.actionFailed'));
  }
  await p._refresh();
}

async function deleteArchivedCompletion(
  p: PanelHost,
  assetId: string,
  archivedTaskId: string,
  ts: string,
): Promise<void> {
  if (!p._hass) return;
  try {
    await api.deleteArchivedCompletion(p._hass, assetId, archivedTaskId, ts);
  } catch (err) {
    console.error('home-keeper: delete archived completion failed', err);
    toast(p, t('error.actionFailed'));
  }
  await p._refresh();
}

// ── detail-page chrome ──────────────────────────────────────────────────────

/** A plain section heading — the label above a group of fields in an editor, or above
 *  a card on a detail page. Exported because the regions still in `panel.ts` build
 *  their chrome from it too. */
export function section(title: string): HTMLElement {
  const el = document.createElement('div');
  el.className = 'hk-section';
  el.textContent = title;
  return el;
}

/** A collapsible `<details>` section for the advanced parts of the appliance editor,
 *  so a first appliance isn't a wall of fields. Defaults open when it already holds
 *  entries (editing existing data) and collapsed when empty. Returns the body to
 *  fill; the caller appends the returned `details` to its container. */
export function collapsibleSection(
  p: PanelHost,
  title: string,
  key: string,
  count: number,
): { details: HTMLDetailsElement; body: HTMLElement } {
  const details = document.createElement('details');
  details.className = 'hk-collapsible';
  // Respect a remembered choice; otherwise open when the section already has content.
  details.open = p._assetEdit.openSections?.[key] ?? count > 0;
  details.addEventListener('toggle', () => {
    (p._assetEdit.openSections ??= {})[key] = details.open;
  });
  const summary = document.createElement('summary');
  summary.innerHTML =
    `<span class="hk-section">${escapeHTML(title)}</span>` +
    (count ? `<span class="hk-section-count">${count}</span>` : '') +
    `<ha-icon icon="mdi:chevron-down" class="hk-section-chevron"></ha-icon>`;
  details.appendChild(summary);
  const body = document.createElement('div');
  details.appendChild(body);
  return { details, body };
}

/** Give an ha-icon-button its mdi icon via the native `path` property. */
export function setIcon(button: HTMLElement, path: string): void {
  (button as HTMLElement & { path?: string }).path = path;
}

// ── completion-history rendering (inline in the detail page) ─────────────────

export function historyBody(p: PanelHost, groups: HistoryGroup[]): string {
  const withAny = groups.filter((g) => (g.completions?.length ?? 0) > 0);
  if (!withAny.length) {
    return `<ha-alert alert-type="info">${escapeHTML(t('history.empty'))}</ha-alert>`;
  }
  const multi = withAny.length > 1;
  return withAny.map((g) => historyGroup(p, g, multi)).join('');
}

function historyGroup(p: PanelHost, group: HistoryGroup, showHead: boolean): string {
  // Sort the completion objects (not just Dates) so each row keeps its `ts`
  // string for the per-row delete button.
  const comps = [...(group.completions || [])]
    .filter((c) => !Number.isNaN(new Date(c.ts).getTime()))
    .sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());
  const stats = completionStats(group.completions);
  const sub: string[] = [tn('history.count', stats.count)];
  if (stats.avgIntervalDays) sub.push(t('history.cadence', { days: stats.avgIntervalDays }));
  const archived = group.archived
    ? `<span class="hk-hist-archived">${escapeHTML(t('history.archived'))}</span>`
    : '';
  const head = showHead
    ? `<div class="hk-hist-head">${escapeHTML(group.name)}${archived}
         <span class="hk-hist-sub">${escapeHTML(sub.join(' · '))}</span></div>`
    : `<div class="hk-hist-head"><span class="hk-hist-sub">${escapeHTML(sub.join(' · '))}</span>${archived}</div>`;
  // Encode the deletion target on each trash button: a live task carries
  // `data-del-task`; an archived group carries `data-del-asset` + `data-del-arch`.
  const delAttrs = group.taskId
    ? `data-del-task="${escapeHTML(group.taskId)}"`
    : group.assetId
      ? `data-del-asset="${escapeHTML(group.assetId)}" data-del-arch="${escapeHTML(group.archivedTaskId || '')}"`
      : '';
  // Editing a completion's metadata only applies to a live task (the backend's
  // update_completion works on tasks, not an appliance's archived history).
  const editTask = !group.archived ? group.taskId : undefined;
  // The unit for any meter readings in this group, resolved once rather than per
  // row. An archived group has no live task, so its rows show a bare number.
  const unit = readingUnit(
    group.taskId ? p._tasks.find((x) => x.id === group.taskId) : undefined,
    p._hass,
  );
  const items = comps
    .map((c) => {
      const d = new Date(c.ts);
      const date = formatDate(d, p._lang());
      const editBtn = editTask
        ? `<ha-icon-button class="hk-hist-edit" data-edit-task="${escapeHTML(editTask)}" data-ts="${escapeHTML(c.ts)}" label="${escapeHTML(t('btn.edit'))}"></ha-icon-button>`
        : '';
      // Moving a completion's date only applies to a live task, same as editing
      // its metadata — move_completion doesn't operate on archived history.
      const moveBtn = editTask
        ? `<ha-icon-button class="hk-hist-move" data-move-task="${escapeHTML(editTask)}" data-ts="${escapeHTML(c.ts)}" label="${escapeHTML(t('btn.moveDate'))}"></ha-icon-button>`
        : '';
      return `<li>
          <div class="hk-hist-row">
            <span class="date">${escapeHTML(date)}</span>
            <span class="when">${escapeHTML(relativeDay(d))}</span>
            <span class="hk-hist-actions">${moveBtn}${editBtn}<ha-icon-button class="hk-hist-del" ${delAttrs} data-ts="${escapeHTML(c.ts)}" label="${escapeHTML(t('btn.delete'))}"></ha-icon-button></span>
          </div>
          ${completionMeta(p, c, unit)}
        </li>`;
    })
    .join('');
  return `<div class="hk-hist-group">${head}<ul class="hk-hist-list">${items}</ul></div>`;
}

/**
 * Render a completion's recorded detail (reading / cost / who / note / photo).
 *
 * `unit` is resolved once per history group by the caller rather than looked up
 * here: a `Completion` is a bare history entry and knows nothing about the sensor
 * it came from, and an archived group has no live task to ask at all (its rows then
 * show a bare number, which is still the figure that matters).
 */
function completionMeta(p: PanelHost, c: Completion, unit = ''): string {
  const bits: string[] = [];
  // The meter reading leads: on a usage task it is the number the whole task is
  // measured in, and it is what the cost/who chips are context for.
  if (c.reading != null)
    bits.push(
      escapeHTML(
        t('completion.reading', {
          reading: `${round1(c.reading)}${unit ? ` ${unit}` : ''}`,
        }),
      ),
    );
  if (c.cost != null) bits.push(escapeHTML(formatCost(p._hass, c.cost)));
  if (c.who) bits.push(escapeHTML(t('completion.by', { who: personName(p._hass, c.who) })));
  const line = bits.length
    ? `<span class="hk-hist-chips">${bits.join(' · ')}</span>`
    : '';
  // A completion note renders as Markdown too, so it's a block (not a span) and
  // takes its own line under the cost/who chips.
  const note = c.note
    ? `<div class="hk-hist-note">${markdownBlock(c.note, 'hk-md-compact')}</div>`
    : '';
  // `photo` is caller-supplied (any string via home_keeper/complete_task) and was
  // rendered as a raw href — escapeHTML can't neutralise a `javascript:` URI in an
  // href, so a non-admin could plant a stored-XSS payload an admin clicks. Only
  // render the link/thumbnail when the URL is http(s) or a site-relative path (the
  // shape `ha-picture-upload` produces, e.g. `/api/image/serve/<id>/original`).
  const photo = isSafeImageUrl(c.photo)
    ? `<a href="${escapeHTML(c.photo)}" target="_blank" rel="noopener"><img class="hk-hist-photo" src="${escapeHTML(c.photo)}" alt="${escapeHTML(t('completion.photo'))}" /></a>`
    : '';
  if (!line && !note && !photo) return '';
  return `<div class="hk-hist-meta">${line}${note}${photo}</div>`;
}

/** Set the trash/pencil icons and wire each per-completion delete/edit button. */
export function wireHistory(p: PanelHost, root: ParentNode): void {
  root.querySelectorAll<HTMLElement>('.hk-hist-del').forEach((b) => {
    setIcon(b, MDI_DELETE);
    b.addEventListener('click', () => {
      const ts = b.dataset.ts;
      if (!ts) return;
      if (b.dataset.delTask) void deleteCompletion(p, b.dataset.delTask, ts);
      else if (b.dataset.delAsset)
        void deleteArchivedCompletion(p, b.dataset.delAsset, b.dataset.delArch || '', ts);
    });
  });
  root.querySelectorAll<HTMLElement>('.hk-hist-edit').forEach((b) => {
    setIcon(b, MDI_EDIT);
    b.addEventListener('click', () => {
      const ts = b.dataset.ts;
      const taskId = b.dataset.editTask;
      if (!ts || !taskId) return;
      const task = p._tasks.find((x) => x.id === taskId);
      const comp = task?.completions?.find((c) => c.ts === ts);
      if (task && comp) openCompletionEdit(p, task, comp);
    });
  });
  root.querySelectorAll<HTMLElement>('.hk-hist-move').forEach((b) => {
    setIcon(b, MDI_MOVE_DATE);
    b.addEventListener('click', () => {
      const ts = b.dataset.ts;
      const taskId = b.dataset.moveTask;
      if (!ts || !taskId) return;
      const task = p._tasks.find((x) => x.id === taskId);
      if (task) openMoveCompletion(p, task, ts);
    });
  });
}
