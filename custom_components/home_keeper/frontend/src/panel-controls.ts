/**
 * The list-controls region: the row above every list (scope pills, saved-Profile
 * picker, Group by, the appliance flat/tree switch, Add), the two primitives
 * it is built from (`seg`, `menuControl`), and the grouping glue that turns the
 * chosen options into the buckets a list renders — plus the one wiring pass that
 * makes the row live.
 *
 * The bucketing primitives themselves (`statusBucket`, `bucketByKey`) live in
 * `card-filter.ts`, shared with the dashboard card; what is here is the panel's own
 * use of them — which groups exist, in what order, and under what headings.
 *
 * `seg`, `menuControl` and `scopeMatches` take no `PanelHost`: they are pure
 * functions of their arguments. The rest read the panel's live control state
 * (`_view`, `_groupBy`, `_filter`, the saved Profiles) through the declared seam.
 */

import {
  bucketByKey,
  isBuyTask,
  isUseTask,
  profileMatches,
  statusBucket,
  taskAreaId,
  taskMatchesQuery,
  type Group,
} from './card-filter';
import { t } from './i18n';
import { activeListChips, type ListChip } from './list-bar';
import type { PanelHost } from './panel-host';
import {
  PANEL_BUCKETS,
  TASK_FILTERS,
  type AssetFilter,
  type AssetView,
  type GroupBy,
  type TaskFilter,
} from './panel-types';
import { spendButton } from './panel-spend';
import { TASK_LAYOUTS, boardColumnLabel, parseTaskLayout } from './task-layout';
import type { Asset, Profile, Task } from './types';
import {
  areaName,
  btnAttrs,
  deviceName,
  escapeHTML,
  groupableDeviceId,
  isOverdue,
} from './utils';

// ── list controls (filter + group-by) ───────────────────────────────────────
/** Group-by resolved for the active view (appliances only support area/none). */
export function effectiveGroup(p: PanelHost): GroupBy {
  const taskOnlyGroups: GroupBy[] = ['status', 'device', 'integration'];
  if (p._view === 'appliances' && taskOnlyGroups.includes(p._groupBy)) {
    return 'none';
  }
  return p._groupBy;
}

export function controls(p: PanelHost): string {
  const onTasks = p._view === 'tasks';
  const groupOpts: { value: GroupBy; label: string }[] = onTasks
    ? [
        { value: 'status', label: t('group.status') },
        { value: 'area', label: t('group.area') },
        { value: 'device', label: t('group.device') },
        { value: 'integration', label: t('group.integration') },
        { value: 'none', label: t('group.none') },
      ]
    : [
        { value: 'area', label: t('group.area') },
        { value: 'none', label: t('group.none') },
      ];
  // Group-by is a refinement, not a primary filter, and it has five options — as a
  // visible segment it dominated the row and pushed everything else onto a second
  // line. A dropdown states the current grouping in the same width as its label,
  // which is what lets the whole control row be one line.
  const groupControl = menuControl(
    'group',
    t('group.by'),
    effectiveGroup(p),
    groupOpts,
  );
  // The layout picker sits beside Group by, because the two answer the same kind
  // of question: Group by chooses how the list is divided, Layout chooses how a
  // task inside it is drawn. Tasks only — the appliance list has one layout.
  const layoutControl = onTasks
    ? menuControl(
        'layout',
        t('layout.label'),
        p._taskLayout,
        TASK_LAYOUTS.map((value) => ({ value, label: t(`layout.${value}`) })),
      )
    : '';
  // One box for the pair, so a row that wraps moves both together. When a Profile
  // menu shares the row, the Layout menu would otherwise wrap alone to the next
  // line, away from the Group by it belongs beside.
  const menuPair = layoutControl
    ? `<div class="hk-menu-pair">${groupControl}${layoutControl}</div>`
    : groupControl;
  // A saved Profile, when picked, drives the status/label/area/device filter, so
  // the inline all/overdue/soon segment is hidden while one is active.
  const profile = activeProfile(p);
  // Counts ride the scope pills so "how much is overdue" is answered before anyone
  // has to click. Only meaningful without a Profile, which is also the only time
  // these pills are shown.
  const counts = onTasks && !profile ? filterCounts(p) : null;
  const filterControl =
    onTasks && !profile
      ? `<div class="hk-control">${seg(
          'filter',
          p._filter,
          [
            { value: 'all', label: t('filter.all'), count: counts?.all },
            { value: 'overdue', label: t('filter.overdue'), count: counts?.overdue },
            { value: 'soon', label: t('filter.soon'), count: counts?.soon },
            { value: 'shopping', label: t('filter.shopping'), count: counts?.shopping },
            { value: 'counted', label: t('filter.counted'), count: counts?.counted },
          ],
          // Not `group.by`: these pills choose *what is listed*, and the Group by
          // dropdown sitting beside them chooses how it is arranged. Naming both
          // "Group by" left a screen reader with two different controls under one
          // name, and no way to tell which one it had landed on.
          t('filter.label'),
        )}</div>`
      : '';
  const assetFilterControl =
    p._view === 'appliances'
      ? `<div class="hk-control">${seg(
          'assetFilter',
          p._assetFilter,
          [
            { value: 'active', label: t('filter.active') },
            { value: 'archived', label: t('filter.archived') },
          ],
          // Likewise: "Appliances" named the tab this segment sits on, not the
          // choice it offers, which is which appliances are listed.
          t('filter.label'),
        )}</div>`
      : '';
  const viewControl =
    p._view === 'appliances'
      ? `<div class="hk-control">
            <span class="hk-seg-label">${escapeHTML(t('view.label'))}</span>
            ${seg(
              'assetView',
              p._assetView,
              [
                { value: 'flat', label: t('view.flat') },
                { value: 'tree', label: t('view.tree') },
              ],
              t('view.label'),
            )}
          </div>`
      : '';
  // One row: scope pills lead, the refinements (Profile, Group by, appliance view)
  // sit to the right behind a spacer, and the single primary action closes it. The
  // comp's rule is one primary button per surface, so Add moves in here from the
  // old full-width action bar above the list.
  // Search sits with the two segments above rather than with the refinements after
  // it: all three answer "what is listed", while View, Profile and Group by answer
  // how what is listed is arranged. The pills keep the lead, because their counts
  // answer "how much is overdue" before anyone has to type anything.
  const addLabel = onTasks ? t('btn.addTask') : t('btn.addAppliance');
  // Print labels opens a checklist of what the list shows (`panel-labels.ts`). It is
  // secondary: Add stays the 1 primary action of the row.
  // A view-only user can add a task but not an appliance: only the task services
  // are open to every user.
  const addBtn =
    !onTasks && p._readOnly()
      ? ''
      : `<ha-button ${btnAttrs('primary')} id="add-btn" class="hk-add-btn">${escapeHTML(addLabel)}</ha-button>`;
  const actions = `
      <span class="hk-controls-spacer"></span>
      <ha-button ${btnAttrs('secondary')} id="labels-btn" class="hk-labels-btn">${escapeHTML(
        t('labels.printButton'),
      )}</ha-button>
      ${addBtn}`;
  if (onTasks) return taskBar(p, { filterControl, menuPair, addBtn });
  return `<div class="hk-controls">${filterControl}${assetFilterControl}${searchControl(p)}${viewControl}${profileControl(p)}${menuPair}${actions}</div>`;
}

/**
 * The Tasks tab's controls (#488), in 2 parts.
 *
 * - The list bar stays at the top of the screen while the list scrolls. It holds
 *   Search, the Filters button, the spend button and Add, and under them a chip for
 *   each active filter. A sentinel above it tells the panel when the bar is pinned.
 * - The filter controls follow it: the scope pills, the Profile, Group by, Layout and
 *   Print labels. A phone folds them behind the Filters button.
 *
 * The stylesheet decides what each width shows (see the list bar rules in
 * `panel-styles.ts`). A desktop shows the controls at all times, and shows the
 * Filters button and the chips only while the bar is pinned. Add stays in the bar,
 * so the phone's floating Add button is never folded away.
 */
function taskBar(
  p: PanelHost,
  parts: { filterControl: string; menuPair: string; addBtn: string },
): string {
  const chips = listChips(p);
  return `
      <div class="hk-listbar-sentinel" aria-hidden="true"></div>
      <div class="hk-listbar"${p._barStuck ? ' data-stuck' : ''}>
        <div class="hk-listbar-row">
          ${searchControl(p)}
          ${filtersButton(p, chips.length)}
          ${spendButton(p)}
          ${parts.addBtn}
        </div>
        <div class="hk-active-filters" role="group" aria-label="${escapeHTML(
          t('filter.activeGroup'),
        )}">${chipsHtml(chips)}</div>
      </div>
      <div class="hk-controls hk-list-controls" id="hk-list-controls"${p._controlsOpen ? ' data-open' : ''}>
        ${parts.filterControl}${profileControl(p)}${parts.menuPair}
        <span class="hk-controls-spacer"></span>
        <ha-button ${btnAttrs('secondary')} id="labels-btn" class="hk-labels-btn">${escapeHTML(
          t('labels.printButton'),
        )}</ha-button>
      </div>`;
}

/** The active filters of the task list, as chips. */
function listChips(p: PanelHost): ListChip[] {
  return activeListChips({
    filter: p._filter,
    profileName: activeProfile(p)?.name ?? null,
    query: p._query,
  });
}

/**
 * The Filters button. With active filters, a badge shows their count, and the name
 * says it in words, because the badge is hidden from a screen reader.
 */
function filtersButton(p: PanelHost, active: number): string {
  return `<button type="button" class="hk-filters-btn" id="hk-filters-btn" data-controls-toggle
      aria-expanded="${p._controlsOpen}" aria-controls="hk-list-controls"${filtersName(
        active,
      )}><ha-icon icon="mdi:filter-variant"></ha-icon><span class="hk-filters-label">${escapeHTML(
        t('filter.toggle'),
      )}</span>${filtersBadge(active)}</button>`;
}

function filtersName(active: number): string {
  return active ? ` aria-label="${escapeHTML(t('filter.toggleCount', { n: active }))}"` : '';
}

function filtersBadge(active: number): string {
  return active ? `<span class="hk-filters-badge" aria-hidden="true">${active}</span>` : '';
}

/** 1 chip with a clear button for each active filter, then Clear all for 2 or more. */
function chipsHtml(chips: ListChip[]): string {
  const items = chips.map(
    (c) => `<span class="hk-filter-chip"><span class="hk-filter-chip-text">${escapeHTML(
      c.label,
    )}</span><button type="button" class="hk-filter-chip-clear" data-clear-filter="${c.key}" aria-label="${escapeHTML(
      t('filter.clearOne', { name: c.label }),
    )}"><ha-icon icon="mdi:close"></ha-icon></button></span>`,
  );
  if (chips.length > 1) {
    items.push(
      `<button type="button" class="hk-filter-clear-all" data-clear-filter="all">${escapeHTML(
        t('filter.clearAll'),
      )}</button>`,
    );
  }
  return items.join('');
}

/** Make the chips' clear buttons live. */
function wireChips(p: PanelHost, root: ParentNode): void {
  root.querySelectorAll<HTMLElement>('[data-clear-filter]').forEach((b) =>
    b.addEventListener('click', () => {
      const key = b.dataset.clearFilter;
      if (key === 'scope' || key === 'profile' || key === 'query' || key === 'all') {
        p._clearListFilter(key);
      }
    }),
  );
}

/**
 * Put the chips and the count of the Filters button back after the search text
 * changed, without a new control row. The counterpart to `patchFilterCounts`: the
 * search box being typed in stays as it is.
 */
export function patchListBar(p: PanelHost, root: ParentNode): void {
  const box = root.querySelector<HTMLElement>('.hk-listbar .hk-active-filters');
  const btn = root.querySelector<HTMLElement>('#hk-filters-btn');
  if (!box || !btn) return;
  const chips = listChips(p);
  box.innerHTML = chipsHtml(chips);
  wireChips(p, box);
  btn.querySelector('.hk-filters-badge')?.remove();
  btn.insertAdjacentHTML('beforeend', filtersBadge(chips.length));
  if (chips.length) btn.setAttribute('aria-label', t('filter.toggleCount', { n: chips.length }));
  else btn.removeAttribute('aria-label');
}

/**
 * The text filter both lists share.
 *
 * Shaped like `menuControl` beside it — a caption and a value inside one bordered
 * chip — so the row keeps one height and one vocabulary. Three things about it are
 * load-bearing:
 *
 * - The `value` comes from panel state, so a render the query did not ask for (a
 *   Done press on a narrowed row, opening a form) does not empty the box.
 * - The `id` is what `_focusKey`'s `#<id>` fallback finds after such a render.
 * - The clear button is always in the DOM and toggled with `hidden`, so patching the
 *   list never inserts or removes a node next to the box being typed in. The
 *   browser's own clear button on `type="search"` cannot do this job: Firefox does
 *   not draw one, it cannot take the theme's colours, and it carries no name for a
 *   screen reader. `type` stays `search` for the phone keyboard it asks for.
 */
function searchControl(p: PanelHost): string {
  const label = t('filter.search');
  return `<label class="hk-control hk-search">
            <span class="hk-seg-label">${escapeHTML(label)}</span>
            <input id="hk-search" class="hk-search-input" type="search" autocomplete="off"
              spellcheck="false" enterkeyhint="search" aria-label="${escapeHTML(label)}"
              value="${escapeHTML(p._query)}">
            <ha-icon-button class="hk-search-clear" label="${escapeHTML(
              t('filter.clearSearch'),
            )}"${p._query ? '' : ' hidden'}><ha-icon icon="mdi:close"></ha-icon></ha-icon-button>
          </label>`;
}

/** The saved Profile currently selected for the list filter, or null. */
export function activeProfile(p: PanelHost): Profile | null {
  if (p._view !== 'tasks' || !p._profile) return null;
  const profiles = p._options?.profiles ?? [];
  return profiles.find((x) => x.id === p._profile) ?? null;
}

/** A dropdown to filter the task list by a saved Profile (Tasks tab only). */
function profileControl(p: PanelHost): string {
  if (p._view !== 'tasks') return '';
  const profiles = p._options?.profiles ?? [];
  if (!profiles.length) return '';
  const opt = (value: string, label: string) =>
    `<option value="${escapeHTML(value)}"${value === p._profile ? ' selected' : ''}>${escapeHTML(
      label,
    )}</option>`;
  const options = [
    opt('', t('filter.profileNone')),
    ...profiles.map((x) => opt(x.id, x.name)),
  ].join('');
  return `
      <label class="hk-control hk-menu">
        <span class="hk-seg-label">${escapeHTML(t('filter.profile'))}</span>
        <select class="hk-profile-select hk-menu-select" aria-label="${escapeHTML(
          t('filter.profile'),
        )}" data-profile-filter>${options}</select>
      </label>`;
}

/** A compact labelled dropdown, styled as the control row's "Label  Value ▾" button.
 *  Shares the segmented controls' `data-seg` vocabulary so one handler in `wireControls`
 *  routes both shapes to the same setters. */
function menuControl(
  name: string,
  labelText: string,
  current: string,
  options: { value: string; label: string }[],
): string {
  const opts = options
    .map(
      (o) =>
        `<option value="${escapeHTML(o.value)}"${o.value === current ? ' selected' : ''}>${escapeHTML(
          o.label,
        )}</option>`,
    )
    .join('');
  return `
      <label class="hk-control hk-menu">
        <span class="hk-seg-label">${escapeHTML(labelText)}</span>
        <select class="hk-menu-select" aria-label="${escapeHTML(
          labelText,
        )}" data-seg-select="${escapeHTML(name)}">${opts}</select>
      </label>`;
}

/** A pill-style segmented toggle; the active option carries the `active` class.
 *  An option may carry a `count`, rendered as a trailing figure inside the button —
 *  after the label, so a text-matched selector still finds the option by its name.
 *
 *  Each button states its own pressed-ness: which one is selected was otherwise
 *  carried by fill and font weight alone, which is nothing to a screen reader and
 *  nothing to someone who cannot separate the hues. */
function seg(
  name: string,
  current: string,
  options: { value: string; label: string; count?: number }[],
  groupLabel?: string,
): string {
  const btns = options
    .map((o) => {
      const count =
        o.count === undefined ? '' : `<span class="hk-seg-count">${escapeHTML(String(o.count))}</span>`;
      // A scope holding nothing is dimmed, so the row says where there is something
      // to see before you spend a click finding out. Deliberately still pressable:
      // "is my shopping list really empty?" is a fair question, and the answer is
      // that scope's empty state — which now carries its own way back out. The
      // selected pill is never dimmed, so the one you are standing on stays solid
      // when completing the last task empties it under you.
      const isCurrent = o.value === current;
      const empty = o.count === 0 && !isCurrent;
      return `<button class="hk-seg-btn${isCurrent ? ' active' : ''}${
        empty ? ' hk-seg-empty' : ''
      }" aria-pressed="${isCurrent ? 'true' : 'false'}" data-seg-val="${escapeHTML(
        o.value,
      )}">${escapeHTML(o.label)}${count}</button>`;
    })
    .join('');
  return `<div class="hk-seg" role="group" aria-label="${escapeHTML(
    groupLabel || name,
  )}" data-seg="${escapeHTML(name)}">${btns}</div>`;
}

/**
 * The tasks that the task list shows, in store order: the active Profile, else the
 * status pill, then the search box. The list and the QR label picker both read it,
 * so a picker never offers a task that the list hides.
 */
export function listedTasks(p: PanelHost, now = Date.now()): Task[] {
  const profile = activeProfile(p);
  // A saved Profile replaces the inline filter: status + labels/areas/devices.
  let tasks = profile
    ? p._tasks.filter((task) =>
        profileMatches(task, profile.filter, p._hass?.devices, p._hass?.areas, now),
      )
    : p._tasks.filter((task) => scopeMatches(task, p._filter, now));
  // The text filter narrows whichever of the two chose the set, rather than replacing
  // it: a Profile plus a word is how a household finds one task among its own.
  if (p._query) {
    tasks = tasks.filter((task) =>
      taskMatchesQuery(task, p._query, p._hass?.devices, p._hass?.areas),
    );
  }
  return tasks;
}

// ── list bucketing ──────────────────────────────────────────────────────────
/**
 * Whether *task* belongs in the given scope-filter pill. Extracted from
 * `tasksList` so the pill's count and the list it filters to are computed by the
 * same predicate — a count that disagreed with the list it promises would be worse
 * than no count at all. Takes no `PanelHost`: it is a pure function of the task.
 */
export function scopeMatches(task: Task, scope: TaskFilter, now = Date.now()): boolean {
  // A switched-off task belongs to no pill but All. Its `next_due` is frozen where it
  // was — switching a task off never moves the date — so the clock keeps running
  // against a task that fires no announcement, leaves no to-do item and holds no
  // entities. Counted in Overdue, a pool task switched off for the winter would climb
  // past a hundred days late above a list of work nobody can do. All keeps it, so a
  // task turned off by a service call is still findable from the panel that cannot
  // turn one off.
  if (task.enabled === false) return scope === 'all';
  // A buy reminder is overdue by the clock — it is minted with no due date, and a
  // dateless one-off is due now — but it is not *late work*, and this pill is the
  // panel's word for late work. Counting it here put "Overdue 13" above a list whose
  // own section headings read Overdue 10 and Shopping 3, and clicking the pill drew a
  // Shopping section under a heading that says Overdue. Shopping already has the pill
  // beside this one, so nothing is hidden by leaving it out of this one.
  //
  // Scoped to the pill deliberately. A Profile's `status: overdue` still selects buy
  // reminders, because `exclude_shopping` is the opt-out b6 shipped for that and a
  // household may be relying on those notifications; the per-task `_overdue` binary
  // sensor likewise stays on, since an automation may key off it. This is a view
  // control, and it is the only one of the three that had a Shopping twin to defer to.
  if (scope === 'overdue') return isOverdue(task) && !isBuyTask(task);
  if (scope === 'soon') return statusBucket(task, now, PANEL_BUCKETS) === 'soon';
  if (scope === 'shopping') return isBuyTask(task);
  // A use task is never overdue and never due soon (it has no due date at all), so
  // without a pill of its own the only scope that lists it is All. This is the pill
  // that answers "what am I counting?".
  if (scope === 'counted') return isUseTask(task);
  return true;
}

/** How many tasks each scope pill would show, for the counts rendered on them. */
function filterCounts(p: PanelHost, now = Date.now()): Record<TaskFilter, number> {
  const counts = { all: 0, overdue: 0, soon: 0, shopping: 0, counted: 0 };
  // The text filter is part of what the list shows, so it is part of what a pill
  // promises. Left out, a pill reads "Overdue 12" above a list of three.
  const tasks = p._query
    ? p._tasks.filter((task) =>
        taskMatchesQuery(task, p._query, p._hass?.devices, p._hass?.areas),
      )
    : p._tasks;
  for (const task of tasks) {
    for (const scope of TASK_FILTERS) {
      if (scopeMatches(task, scope, now)) counts[scope]++;
    }
  }
  return counts;
}

/**
 * Put the current counts back on the scope pills without rebuilding the control row.
 *
 * The counterpart to `_applyQuery`'s list patch: the buttons themselves are left
 * standing, so their listeners survive and the keyboard does not move. Only the
 * figure and the dimming change, by the same rules `seg` applies when it draws them.
 */
export function patchFilterCounts(p: PanelHost, root: ParentNode): void {
  // The pills are drawn on the tasks list, and not while a Profile is driving it.
  if (p._view !== 'tasks' || activeProfile(p)) return;
  const counts = filterCounts(p);
  root.querySelectorAll<HTMLElement>('.hk-seg[data-seg="filter"] .hk-seg-btn').forEach((btn) => {
    const scope = btn.dataset.segVal as TaskFilter | undefined;
    if (!scope || !(scope in counts)) return;
    const n = counts[scope];
    const cell = btn.querySelector('.hk-seg-count');
    if (cell) cell.textContent = String(n);
    // Mirrors `seg`: the selected pill is never dimmed, so the one being stood on
    // stays solid when a query empties it underneath.
    btn.classList.toggle('hk-seg-empty', n === 0 && !btn.classList.contains('active'));
  });
}

export function groupTasks(p: PanelHost, tasks: Task[], now = Date.now()): Group<Task>[] {
  const group = effectiveGroup(p);
  if (group === 'status') {
    const order: {
      bucket:
        | 'overdue'
        | 'shopping'
        | 'counted'
        | 'soon'
        | 'later'
        | 'monitored'
        | 'completed'
        | 'disabled'
        | 'none';
      label: string;
    }[] = [
      { bucket: 'overdue', label: t('chip.overdue') },
      { bucket: 'shopping', label: t('filter.shopping') },
      // Above Soon rather than below it: a use task is something you tap today, so it
      // belongs with the sections you act on, not with the ones you read.
      { bucket: 'counted', label: t('filter.counted') },
      { bucket: 'soon', label: t('filter.soon') },
      { bucket: 'later', label: t('section.later') },
      { bucket: 'monitored', label: t('section.monitored') },
      { bucket: 'none', label: t('section.noSchedule') },
      { bucket: 'completed', label: t('section.completed') },
      // Last, below even Completed. A switched-off task is the one section with
      // nothing to do in it: the rows are here so a service call aimed at the wrong
      // task leaves something findable, not because they need attention.
      { bucket: 'disabled', label: t('section.disabled') },
    ];
    return order
      .map(({ bucket, label }) => ({
        key: `status:${bucket}`,
        label,
        items: tasks.filter((task) => statusBucket(task, now, PANEL_BUCKETS) === bucket),
      }))
      .filter((g) => g.items.length);
  }
  if (group === 'area') {
    return bucketByKey(
      tasks,
      (task) => taskAreaId(task, p._hass?.devices),
      (id) => areaName(p._hass?.areas, id),
      t('section.unassigned'),
      'area',
    );
  }
  if (group === 'device') {
    return bucketByKey(
      tasks,
      // A device with no name to head a section with — gone from the registry, or
      // present but nameless — sends its tasks to "No device" rather than under a
      // bare id or an empty heading.
      (task) => groupableDeviceId(p._hass?.devices, task.device_id),
      (id) => deviceName(p._hass?.devices, id),
      t('section.noDevice'),
      'device',
    );
  }
  if (group === 'integration') {
    return bucketByKey(
      tasks,
      (task) => task.managed_by?.display_name ?? undefined,
      (name) => name,
      t('section.standalone'),
      'integration',
    );
  }
  return [{ key: '', label: '', items: tasks }];
}

export function groupAssets(p: PanelHost, assets: Asset[]): Group<Asset>[] {
  if (effectiveGroup(p) === 'area') {
    return bucketByKey(
      assets,
      (a) => a.area_id ?? undefined,
      (id) => areaName(p._hass?.areas, id),
      t('section.unassigned'),
      'area',
    );
  }
  return [{ key: '', label: '', items: assets }];
}

/** Render groups as collapsible sections, or bare items when ungrouped. */
export function renderGroups<T>(
  p: PanelHost,
  groups: Group<T>[],
  renderItem: (item: T) => string,
  // Applied to each group's item container, and to the wrapper the ungrouped
  // fallback below grows to hold it. The tile layout passes `hk-tiles` to lay a
  // group out as a grid instead of a stack. Every other caller leaves it unset.
  itemsClass = '',
): string {
  if (groups.length === 1 && !groups[0].label) {
    const items = groups[0].items.map(renderItem).join('');
    return itemsClass ? `<div class="${escapeHTML(itemsClass)}">${items}</div>` : items;
  }
  return groups
    .map((g) => {
      // A search opens every section it drew. Two of them start collapsed —
      // "Monitored" and "Completed" — and a monitored companion task is exactly what
      // the reader is most often hunting for, so a match landing behind a shut
      // heading would fail at the one job this filter has. The set is read, never
      // written, so each section closes again the moment the box is cleared.
      const open = p._query || !p._collapsed.has(g.key) ? 'open' : '';
      // `data-bucket` lets the header take the section's status colour (Overdue reads
      // red) without the label text having to carry that meaning on its own. The rule
      // and the collapse caption are decorative: the whole summary is the hit target,
      // so they are hidden from assistive tech rather than announced twice.
      const bucket = g.key.startsWith('status:') ? g.key.slice('status:'.length) : '';
      return `
        <details class="hk-group" data-group-key="${escapeHTML(g.key)}" data-bucket="${escapeHTML(bucket)}" ${open}>
          <summary class="hk-group-head">
            <span class="hk-group-title">${escapeHTML(g.label)}</span>
            <span class="hk-group-count">${g.items.length}</span>
            <span class="hk-group-rule" aria-hidden="true"></span>
            <span class="hk-group-toggle" aria-hidden="true"></span>
          </summary>
          <div class="hk-group-body${itemsClass ? ` ${escapeHTML(itemsClass)}` : ''}">${g.items.map(renderItem).join('')}</div>
        </details>`;
    })
    .join('');
}

/**
 * Render groups as board columns: one column per group, side by side.
 *
 * The board follows Group by, so the columns are whatever the list is already
 * divided into — status sections, areas, devices, integrations. Every column is
 * open: a board is read across, and a shut column would leave a gap where a
 * heading is. The collapse memory `renderGroups` keeps is therefore ignored here
 * rather than shared, and stays untouched for the rows and tiles layouts.
 *
 * Group by none makes one unlabelled group, which becomes one column headed
 * "All" (see `boardColumnLabel`).
 */
export function renderBoard<T>(
  groups: Group<T>[],
  renderItem: (item: T) => string,
): string {
  const cols = groups
    .map((g) => {
      // The same `data-bucket` a group head carries, so a board head takes the
      // status colour from the one rule set instead of a second copy of it.
      const bucket = g.key.startsWith('status:') ? g.key.slice('status:'.length) : '';
      return `
        <section class="hk-board-col" data-group-key="${escapeHTML(g.key)}" data-bucket="${escapeHTML(bucket)}">
          <div class="hk-board-head">
            <span class="hk-group-title">${escapeHTML(boardColumnLabel(g.label))}</span>
            <span class="hk-group-count">${g.items.length}</span>
          </div>
          <div class="hk-board-body">${g.items.map(renderItem).join('')}</div>
        </section>`;
    })
    .join('');
  return `<div class="hk-board">${cols}</div>`;
}

/**
 * Wire the control row: Add, the pill segments and their dropdown twins, the
 * saved-Profile picker, and the text filter.
 *
 * The per-group collapse memory is *not* here, although the segments it sits beside
 * are. `renderGroups` emits those `<details>` into the list, and the list is rebuilt
 * on its own by `_applyQuery` — so they are wired by `wireLists`, which is the pass
 * that runs again when they are replaced.
 */
export function wireControls(p: PanelHost, root: ShadowRoot): void {
  root.getElementById('add-btn')?.addEventListener('click', () => {
    if (p._view === 'tasks') p._openCreate();
    else p._openCreateAsset();
  });
  // The task list bar: the Filters button and the chips of the active filters.
  root.getElementById('hk-filters-btn')?.addEventListener('click', () => p._toggleControls());
  const chipBox = root.querySelector('.hk-listbar .hk-active-filters');
  if (chipBox) wireChips(p, chipBox);
  // Filter / group-by segmented controls.
  root.querySelectorAll<HTMLElement>('.hk-seg-btn').forEach((b) =>
    b.addEventListener('click', () => {
      const segName = (b.closest('.hk-seg') as HTMLElement | null)?.dataset.seg;
      const val = b.dataset.segVal;
      if (!val) return;
      if (segName === 'group') p._setGroupBy(val as GroupBy);
      else if (segName === 'filter') p._setFilter(val as TaskFilter);
      else if (segName === 'assetFilter') p._setAssetFilter(val as AssetFilter);
      else if (segName === 'assetView') p._setAssetView(val as AssetView);
    }),
  );
  // The dropdown-shaped controls (currently Group by) speak the same `data-seg`
  // vocabulary as the pill segments, so both shapes route to the same setters.
  root.querySelectorAll<HTMLSelectElement>('select[data-seg-select]').forEach((s) =>
    s.addEventListener('change', () => {
      const segName = s.dataset.segSelect;
      const val = s.value;
      if (segName === 'group') p._setGroupBy(val as GroupBy);
      else if (segName === 'filter') p._setFilter(val as TaskFilter);
      else if (segName === 'assetFilter') p._setAssetFilter(val as AssetFilter);
      else if (segName === 'assetView') p._setAssetView(val as AssetView);
      else if (segName === 'layout') p._setTaskLayout(parseTaskLayout(val));
    }),
  );
  // Saved-Profile filter dropdown.
  root
    .querySelector<HTMLSelectElement>('select[data-profile-filter]')
    ?.addEventListener('change', (e) => p._setProfile((e.target as HTMLSelectElement).value));

  // The text filter.
  const search = root.querySelector<HTMLInputElement>('.hk-search-input');
  if (search) {
    // `input` rather than `keyup`, so a paste registers too. The composition guard is
    // for the languages that compose a character from several keystrokes: without it a
    // half-typed pinyin syllable filters the list out from under the person typing it.
    let composing = false;
    search.addEventListener('compositionstart', () => {
      composing = true;
    });
    search.addEventListener('compositionend', () => {
      composing = false;
      p._setQuery(search.value);
    });
    search.addEventListener('input', () => {
      if (!composing) p._setQuery(search.value);
    });
    // Escape clears the box instead of leaving the panel, matching what Escape does
    // in every other search field the reader uses.
    search.addEventListener('keydown', (e) => {
      if ((e as KeyboardEvent).key !== 'Escape') return;
      e.preventDefault();
      e.stopPropagation();
      p._setQuery('');
    });
  }
  root.querySelector<HTMLElement>('.hk-search-clear')?.addEventListener('click', (e) => {
    // The button sits inside the <label>, which would otherwise re-fire the click on
    // the input it labels.
    e.preventDefault();
    p._setQuery('');
    p._focus(search);
  });
}
