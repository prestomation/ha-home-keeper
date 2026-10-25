/**
 * The spend totals of the task list (#460, #488), and the records of the open total.
 *
 * The totals come from `home_keeper/get_spend`, which sums the cost on each
 * completion (see the backend `cost_summary.py`). The cost sensors give the same
 * numbers. A total is a toggle button: it opens a list of its records, and each
 * record opens the history of its task. The purchases total opens the appliance list.
 *
 * Above the list, the totals are a compact strip of 1 line. A phone hides that strip
 * and shows the spend button in the list bar instead. The button opens the full
 * strip in a sheet.
 *
 * The open total and the open sheet are panel state, as a collapsed group is. They
 * are not a location, so they are not in the URL. Everything is a free function over
 * a `PanelHost`.
 */

import { t, tn } from './i18n';
import type { PanelHost } from './panel-host';
import type { SpendRecord, SpendSummary } from './types';
import { spendButtonText } from './list-bar';
import { escapeHTML, formatCost, formatDate, personName } from './utils';

/** The key of the all-time total. A window total is `w<days>`. */
export const SPEND_ALL = 'all';

/** The records of total *key*: the window records, or every record for all time. */
export function spendRecordsFor(spend: SpendSummary, key: string): SpendRecord[] {
  if (key === SPEND_ALL) return spend.records;
  const win = spend.windows.find((w) => `w${w.days}` === key);
  if (!win) return [];
  const start = new Date(win.since).getTime();
  return spend.records.filter((r) => new Date(r.ts).getTime() >= start);
}

/**
 * Whether the strip shows. It needs the option on (the default) and something to
 * show: a household that records no cost sees no strip of zeros.
 */
export function showSpend(p: PanelHost): boolean {
  const spend = p._spend;
  if (!spend || p._options?.cost_summary_panel === false) return false;
  return spend.records.length > 0 || spend.purchases.count > 0;
}

/** Where a strip is drawn: the full strip in the sheet, or the compact one above the list. */
type StripKind = 'full' | 'compact';

/** The id of the records list of a strip, which the totals name in `aria-controls`. */
function recordsId(kind: StripKind): string {
  return kind === 'full' ? 'hk-spend-records' : 'hk-spend-strip-records';
}

function totalButton(
  p: PanelHost,
  kind: StripKind,
  key: string,
  label: string,
  total: number,
  count: number,
): string {
  const open = p._spendOpen === key;
  const countCell =
    kind === 'full' ? `<span class="hk-spend-count">${escapeHTML(tn('spend.records', count))}</span>` : '';
  return `
      <button type="button" class="hk-spend-total${open ? ' open' : ''}" data-spend="${escapeHTML(
        key,
      )}" aria-pressed="${open}" aria-controls="${recordsId(kind)}">
        <span class="hk-spend-label">${escapeHTML(label)}</span>
        <span class="hk-spend-value">${escapeHTML(formatCost(p._hass, total))}</span>
        ${countCell}
      </button>`;
}

function recordRow(p: PanelHost, r: SpendRecord): string {
  const lang = p._lang();
  // A deleted task has no page of its own. Its appliance keeps the history.
  const target = r.archived && r.asset_id ? `asset:${r.asset_id}` : `task:${r.task_id}`;
  const name = r.task_name || t('spend.unnamed');
  const who = r.who ? personName(p._hass, r.who) : '';
  return `
        <li class="hk-spend-row">
          <span class="hk-spend-date">${escapeHTML(formatDate(r.ts, lang))}</span>
          <a href="#" class="hk-spend-task" data-spend-open="${escapeHTML(target)}">${escapeHTML(
            name,
          )}</a>
          ${r.archived ? `<span class="hk-spend-tag">${escapeHTML(t('spend.deleted'))}</span>` : ''}
          <span class="hk-spend-who">${escapeHTML(who)}</span>
          <span class="hk-spend-cost">${escapeHTML(formatCost(p._hass, r.cost))}</span>
        </li>`;
}

function recordList(p: PanelHost, spend: SpendSummary, label: string, kind: StripKind): string {
  const records = spendRecordsFor(spend, p._spendOpen);
  const body = records.length
    ? `<ul class="hk-spend-list">${records.map((r) => recordRow(p, r)).join('')}</ul>`
    : `<div class="hk-spend-empty">${escapeHTML(t('spend.empty'))}</div>`;
  return `
      <div class="hk-spend-records" id="${recordsId(kind)}">
        <div class="hk-spend-records-head">${escapeHTML(label)}</div>
        ${body}
      </div>`;
}

/**
 * A strip of totals and the records of the open total. Empty when {@link showSpend}
 * says no. The full strip is the content of the spend sheet. The compact strip is the
 * 1 line above the list: it leaves out the help text and the record counts.
 */
export function spendStrip(p: PanelHost, kind: StripKind = 'full'): string {
  if (!showSpend(p)) return '';
  const spend = p._spend as SpendSummary;
  const totals: { key: string; label: string; total: number; count: number }[] = [
    ...spend.windows.map((w) => ({
      key: `w${w.days}`,
      label: tn('spend.window', w.days),
      total: w.total,
      count: w.count,
    })),
    {
      key: SPEND_ALL,
      label: t('spend.all_time'),
      total: spend.all_time.total,
      count: spend.all_time.count,
    },
  ];
  const open = totals.find((x) => x.key === p._spendOpen);
  const purchasesCount =
    kind === 'full'
      ? `<span class="hk-spend-count">${escapeHTML(tn('spend.appliances', spend.purchases.count))}</span>`
      : '';
  const purchases = `
      <button type="button" class="hk-spend-total hk-spend-purchases" data-spend-purchases>
        <span class="hk-spend-label">${escapeHTML(t('spend.purchases'))}</span>
        <span class="hk-spend-value">${escapeHTML(formatCost(p._hass, spend.purchases.total))}</span>
        ${purchasesCount}
      </button>`;
  const head =
    kind === 'full'
      ? `<div class="hk-spend-head">
          <span class="hk-spend-heading">${escapeHTML(t('spend.heading'))}</span>
          <span class="hk-spend-help">${escapeHTML(t('spend.help'))}</span>
        </div>`
      : `<span class="hk-spend-heading">${escapeHTML(t('spend.heading'))}</span>`;
  return `
      <section class="hk-spend${kind === 'compact' ? ' hk-spend-compact' : ''}" aria-label="${escapeHTML(
        t('spend.heading'),
      )}">
        ${head}
        <div class="hk-spend-totals">
          ${totals.map((x) => totalButton(p, kind, x.key, x.label, x.total, x.count)).join('')}
          ${purchases}
        </div>
        ${open ? recordList(p, spend, open.label, kind) : ''}
      </section>`;
}

/**
 * The spend button of the list bar: the total of the first period in whole units,
 * and the full total, period and heading as its name. All time stands in when no
 * period is set. Empty when {@link showSpend} says no.
 */
export function spendButton(p: PanelHost): string {
  if (!showSpend(p)) return '';
  const spend = p._spend as SpendSummary;
  const win = spend.windows[0];
  const total = win ? win.total : spend.all_time.total;
  const period = win ? tn('spend.window', win.days) : t('spend.all_time');
  const { icon, text } = spendButtonText(total, p._hass?.config?.currency, p._lang());
  const name = t('spend.button', {
    heading: t('spend.heading'),
    window: period,
    total: formatCost(p._hass, total),
  });
  return `<button type="button" class="hk-spend-btn" id="hk-spend-btn" data-spend-btn
      aria-haspopup="dialog" aria-expanded="${p._spendSheet}"${
    p._spendSheet ? ' aria-controls="hk-spend-sheet"' : ''
  }
      aria-label="${escapeHTML(name)}" title="${escapeHTML(name)}"><ha-icon icon="${escapeHTML(
        icon,
      )}"></ha-icon><span class="hk-spend-btn-text">${escapeHTML(text)}</span></button>`;
}

/**
 * The spend sheet: the full strip in a modal dialog over the task list, with a scrim
 * and a Close button. Empty while the sheet is closed. The panel makes the rest of
 * the page inert and handles Escape (`_syncSpendSheet`).
 */
export function spendSheet(p: PanelHost): string {
  if (!p._spendSheet || !showSpend(p)) return '';
  return `
      <div class="hk-spend-scrim" data-spend-close></div>
      <section class="hk-spend-sheet" id="hk-spend-sheet" role="dialog" aria-modal="true"
        aria-labelledby="hk-spend-sheet-title" tabindex="-1">
        <div class="hk-spend-sheet-head">
          <h2 class="hk-spend-sheet-title" id="hk-spend-sheet-title">${escapeHTML(t('spend.heading'))}</h2>
          <button type="button" class="hk-spend-sheet-close" data-spend-close aria-label="${escapeHTML(
            t('btn.close'),
          )}"><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        ${spendStrip(p, 'full')}
      </section>`;
}

/** Make the totals, the record links, the spend button and the sheet live. */
export function wireSpend(p: PanelHost, root: ParentNode): void {
  root.querySelectorAll<HTMLElement>('.hk-spend-total[data-spend]').forEach((b) =>
    b.addEventListener('click', () => {
      const key = b.dataset.spend ?? '';
      p._spendOpen = p._spendOpen === key ? '' : key;
      p._render();
    }),
  );
  root.querySelectorAll<HTMLElement>('[data-spend-purchases]').forEach((b) =>
    b.addEventListener('click', () => {
      // A route change leaves the task list, so the sheet does not come back with it.
      p._spendSheet = false;
      p._navigate({ view: 'appliances', detail: null });
    }),
  );
  root.querySelectorAll<HTMLElement>('[data-spend-open]').forEach((a) =>
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const [kind, ...rest] = (a.dataset.spendOpen ?? '').split(':');
      const id = rest.join(':');
      if (!id) return;
      p._spendSheet = false;
      if (kind === 'asset') {
        p._navigate({ view: 'appliances', detail: { kind: 'asset', id, tab: 'history' } });
      } else {
        p._navigate({ view: 'tasks', detail: { kind: 'task', id, tab: 'history' } });
      }
    }),
  );
  root
    .querySelectorAll<HTMLElement>('[data-spend-btn]')
    .forEach((b) => b.addEventListener('click', () => p._openSpendSheet()));
  root
    .querySelectorAll<HTMLElement>('[data-spend-close]')
    .forEach((b) => b.addEventListener('click', () => p._closeSpendSheet()));
}
