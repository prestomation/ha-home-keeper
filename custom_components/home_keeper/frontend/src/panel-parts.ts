/**
 * The Parts mode of the Appliances tab: every part of every appliance in one list, so
 * a user need not open each appliance. This module draws the list and wires its stock
 * steppers. The rules for what it lists, counts, sorts and groups are in
 * `parts-overview.ts`, and the controls above it are in `panel-controls.ts`.
 *
 * It is one markup for every width. The stylesheet turns the table rows into cards on
 * a phone. A non-admin gets the same rows with no stepper (`_readOnly`), because the
 * backend gates `adjust_part_stock`.
 */

import { t } from './i18n';
import { seg } from './panel-controls';
import { stockStepper, wireStockSteppers } from './panel-detail';
import type { PanelHost } from './panel-host';
import {
  buyTaskForPart,
  collectParts,
  countParts,
  filterParts,
  groupParts,
  isLowPart,
  partMatchesQuery,
  replaceTaskForPart,
  useTaskForPart,
  type PartRow,
} from './parts-overview';
import {
  assetTitle,
  countedProgress,
  dueLabel,
  escapeHTML,
  formatQuantity,
  safeHref,
  useCountLabel,
} from './utils';

/** The 6 column headings, in the order of the cells of a row. */
function head(): string {
  const cell = (cls: string, key: string): string =>
    `<span class="hk-pt-h ${cls}">${escapeHTML(t(key))}</span>`;
  return `<div class="hk-pt-head" aria-hidden="true">
      ${cell('hk-pt-part', 'field.part_name')}${cell('hk-pt-type', 'field.type')}
      ${cell('hk-pt-stock', 'field.stock')}${cell('hk-pt-reorder', 'field.reorder_at')}
      ${cell('hk-pt-status', 'group.status')}${cell('hk-pt-next', 'detail.nextDue')}
    </div>`;
}

/** What the Next column says: the due date of a wear item, or its use count. */
function nextText(p: PanelHost, row: PartRow): string {
  const id = row.part.id as string;
  const useTask = useTaskForPart(p._tasks, row.asset.id, id);
  if (useTask) {
    const progress = countedProgress(useTask, p._assets, p._tasks);
    if (progress) return useCountLabel(progress.count, progress.target, progress.noun);
  }
  const task = replaceTaskForPart(p._tasks, row.asset.id, id);
  return task ? dueLabel(task, new Date(), p._hass) : '';
}

function row(p: PanelHost, r: PartRow, readOnly: boolean): string {
  const { part, asset } = r;
  const id = part.id as string;
  const low = isLowPart(part);
  const counted = part.stock != null;
  const onHand = counted ? formatQuantity(part.stock as number, part.stock_unit) : '';
  const chip = (label: string, cls = ''): string =>
    `<ha-assist-chip class="${cls}" label="${escapeHTML(label)}"></ha-assist-chip>`;

  const sub: string[] = [];
  if (part.part_number) sub.push(part.part_number);
  if (part.vendor) sub.push(part.vendor);
  if (part.cost != null) sub.push(String(part.cost));
  const subLine = sub.length
    ? `<div class="hk-pt-sub">${escapeHTML(sub.join(' · '))}</div>`
    : '';

  const href = p._hrefFor({
    view: 'appliances',
    detail: { kind: 'asset', id: asset.id, tab: 'parts', part: id },
  });
  const name = `<a class="hk-part-link hk-pt-name" href="${safeHref(href)}" data-asset-id="${escapeHTML(
    asset.id,
  )}" data-part-id="${escapeHTML(id)}">${escapeHTML(part.name)}</a>`;

  // The stepper is the stock control of the appliance page, so a change is one
  // `adjust_part_stock` call. A view-only user gets the number as text.
  let stock = '<span class="hk-pt-none">–</span>';
  if (counted) {
    stock = readOnly
      ? chip(t('part.inStock', { n: onHand }), low ? 'hk-overdue' : '')
      : stockStepper(part, low, onHand, { assetId: asset.id, lowWord: false });
    if (part.reorder_at != null && part.reorder_at > 0) {
      const pct = Math.max(0, Math.min(100, ((part.stock as number) / (part.reorder_at * 2)) * 100));
      stock +=
        `<div class="hk-meter hk-part-meter hk-pt-meter${low ? ' low' : ''}" role="progressbar"` +
        ` aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(pct)}"` +
        ` aria-label="${escapeHTML(t('part.inStock', { n: onHand }))}">` +
        `<span style="width:${pct.toFixed(1)}%"></span></div>`;
    }
  }

  const status = !counted
    ? chip(t('parts.filter.uncounted'))
    : low
      ? chip(t('chip.lowStock'), 'hk-overdue')
      : chip(t('parts.status.ok'));
  // A low part links its Buy task, when it has one.
  const buyTask = low ? buyTaskForPart(p._tasks, asset.id, id) : undefined;
  const buy = buyTask
    ? `<a class="hk-part-link hk-pt-buy" href="${safeHref(
        p._hrefFor({ view: 'tasks', detail: { kind: 'task', id: buyTask.id } }),
      )}" data-open-task="${escapeHTML(buyTask.id)}" aria-label="${escapeHTML(
        t('parts.buyAria', { part: part.name }),
      )}">${escapeHTML(t('parts.buy'))}</a>`
    : '';

  const reorder =
    part.reorder_at != null
      ? escapeHTML(formatQuantity(part.reorder_at, part.stock_unit))
      : '<span class="hk-pt-none">–</span>';
  const next = nextText(p, r);
  const cell = (cls: string, label: string, html: string): string =>
    `<div class="hk-pt-cell ${cls}" data-label="${escapeHTML(label)}">${html}</div>`;
  return `<div class="hk-pt-row${low ? ' low' : ''}" data-part-row="${escapeHTML(id)}">
      <div class="hk-pt-cell hk-pt-part"><div class="hk-pt-title">${name}</div>
        <div class="hk-pt-sub hk-pt-asset">${escapeHTML(r.title)}</div>${subLine}</div>
      ${cell('hk-pt-type', t('field.type'), `<span class="hk-part-badge">${escapeHTML(t(`opt.part.${part.type}`))}</span>`)}
      ${cell('hk-pt-stock', t('field.stock'), stock)}
      ${cell('hk-pt-reorder', t('field.reorder_at'), reorder)}
      ${cell('hk-pt-status', t('group.status'), `${status}${buy}`)}
      ${cell('hk-pt-next', t('detail.nextDue'), next ? escapeHTML(next) : '<span class="hk-pt-none">–</span>')}
    </div>`;
}

/**
 * The body of the Parts mode: the filter chips with their counts, then the groups.
 * The counts follow the Archived scope and the search box, not the chip.
 */
export function partsBody(p: PanelHost): string {
  const archived = p._assetFilter === 'archived';
  const devices = p._hass?.devices;
  const scoped = collectParts(p._assets, archived, (a) => assetTitle(a, devices));
  if (!scoped.length) {
    const text = archived ? t('parts.archivedEmpty') : t('parts.empty');
    return `<ha-alert alert-type="info">${escapeHTML(text)}</ha-alert>`;
  }
  const searched = p._query ? scoped.filter((r) => partMatchesQuery(r, p._query)) : scoped;
  const counts = countParts(searched);
  const chips = `<div class="hk-control hk-pt-filters">${seg(
    'partsFilter',
    p._partsFilter,
    [
      { value: 'all', label: t('filter.all'), count: counts.all },
      { value: 'low', label: t('chip.lowStock'), count: counts.low },
      { value: 'wear', label: t('parts.filter.wear'), count: counts.wear },
      { value: 'uncounted', label: t('parts.filter.uncounted'), count: counts.uncounted },
    ],
    t('parts.filter.label'),
  )}</div>`;
  const shown = filterParts(searched, p._partsFilter);
  if (!shown.length) {
    return `${chips}<ha-alert alert-type="info">${escapeHTML(t('parts.noMatch'))}</ha-alert>`;
  }
  const readOnly = p._readOnly();
  const groups = groupParts(shown, p._partsGroup, p._partsSort, {
    wear: t('opt.part.wear'),
    consumable: t('opt.part.consumable'),
  });
  const body = groups
    .map(
      (g) => `<section class="hk-pt-group" data-group="${escapeHTML(g.key)}">
          <h3 class="hk-eyebrow hk-pt-group-title">${escapeHTML(g.label)}</h3>
          ${g.rows.map((r) => row(p, r, readOnly)).join('')}
        </section>`,
    )
    .join('');
  return `${chips}<ha-card class="hk-pt-card"><div class="hk-parts-view hk-pt-by-${escapeHTML(
    p._partsGroup,
  )}">${head()}${body}</div></ha-card>`;
}

/** Make each stock stepper of the list live. */
export function wirePartsView(p: PanelHost, root: ParentNode): void {
  if (!p._partsView) return;
  wireStockSteppers(
    p,
    root,
    (id) => p._assets.find((a) => a.id === id),
    '.hk-parts-view .hk-stock[data-part]',
  );
}
