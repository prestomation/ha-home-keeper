/**
 * The list-controls region: the row above every list (scope pills, saved-Profile
 * picker, Group by, the appliance flat/tree switch, Add/Export), the two primitives
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
  statusBucket,
  taskAreaId,
  taskMatchesQuery,
  type Group,
} from './card-filter';
import { t } from './i18n';
import type { PanelHost } from './panel-host';
import {
  PANEL_BUCKETS,
  type AssetFilter,
  type AssetView,
  type GroupBy,
  type TaskFilter,
} from './panel-types';
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
  const actions = `
      <span class="hk-controls-spacer"></span>
      ${onTasks ? '' : `<ha-button ${btnAttrs('secondary')} id="export-btn">${escapeHTML(t('btn.exportInventory'))}</ha-button>`}
      <ha-button ${btnAttrs('primary')} id="add-btn" class="hk-add-btn">${escapeHTML(addLabel)}</ha-button>`;
  return `<div class="hk-controls">${filterControl}${assetFilterControl}${searchControl(p)}${viewControl}${profileControl(p)}${groupControl}${actions}</div>`;
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

// ── list bucketing ──────────────────────────────────────────────────────────
/**
 * Whether *task* belongs in the given scope-filter pill. Extracted from
 * `tasksList` so the pill's count and the list it filters to are computed by the
 * same predicate — a count that disagreed with the list it promises would be worse
 * than no count at all. Takes no `PanelHost`: it is a pure function of the task.
 */
export function scopeMatches(task: Task, scope: TaskFilter, now = Date.now()): boolean {
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
  return true;
}

/** How many tasks each scope pill would show, for the counts rendered on them. */
function filterCounts(p: PanelHost, now = Date.now()): Record<TaskFilter, number> {
  const counts = { all: 0, overdue: 0, soon: 0, shopping: 0 };
  // The text filter is part of what the list shows, so it is part of what a pill
  // promises. Left out, a pill reads "Overdue 12" above a list of three.
  const tasks = p._query
    ? p._tasks.filter((task) =>
        taskMatchesQuery(task, p._query, p._hass?.devices, p._hass?.areas),
      )
    : p._tasks;
  for (const task of tasks) {
    for (const scope of ['all', 'overdue', 'soon', 'shopping'] as TaskFilter[]) {
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
      bucket: 'overdue' | 'shopping' | 'soon' | 'later' | 'monitored' | 'completed' | 'none';
      label: string;
    }[] = [
      { bucket: 'overdue', label: t('chip.overdue') },
      { bucket: 'shopping', label: t('filter.shopping') },
      { bucket: 'soon', label: t('filter.soon') },
      { bucket: 'later', label: t('section.later') },
      { bucket: 'monitored', label: t('section.monitored') },
      { bucket: 'none', label: t('section.noSchedule') },
      { bucket: 'completed', label: t('section.completed') },
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
  // Applied to each group's item container (and the ungrouped fallback below) —
  // the minimal task grid uses this to lay a group's cards out as a 2-column
  // grid instead of the default stacked rows. Every other caller leaves it unset.
  itemsClass = '',
): string {
  if (groups.length === 1 && !groups[0].label) {
    return itemsClass
      ? `<div class="${escapeHTML(itemsClass)}">${groups[0].items.map(renderItem).join('')}</div>`
      : groups[0].items.map(renderItem).join('');
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
 * Wire the control row: Add/Export, the pill segments and their dropdown twins, the
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

  root.getElementById('export-btn')?.addEventListener('click', () => p._exportInventory());

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
