/**
 * The spend totals above the task list (#460), and the records of the open total.
 *
 * The totals come from `home_keeper/get_spend`, which sums the cost on each
 * completion (see the backend `cost_summary.py`). The cost sensors give the same
 * numbers. A total is a toggle button: it opens a list of its records under the
 * strip, and each record opens the history of its task. The purchases total opens
 * the appliance list.
 *
 * The open total is panel state, as a collapsed group is. It is not a location, so it
 * is not in the URL. Everything is a free function over a `PanelHost`.
 */

import { t, tn } from './i18n';
import type { PanelHost } from './panel-host';
import type { SpendRecord, SpendSummary } from './types';
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

function totalButton(
  p: PanelHost,
  key: string,
  label: string,
  total: number,
  count: number,
): string {
  const open = p._spendOpen === key;
  return `
      <button type="button" class="hk-spend-total${open ? ' open' : ''}" data-spend="${escapeHTML(
        key,
      )}" aria-pressed="${open}" aria-controls="hk-spend-records">
        <span class="hk-spend-label">${escapeHTML(label)}</span>
        <span class="hk-spend-value">${escapeHTML(formatCost(p._hass, total))}</span>
        <span class="hk-spend-count">${escapeHTML(tn('spend.records', count))}</span>
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

function recordList(p: PanelHost, spend: SpendSummary, label: string): string {
  const records = spendRecordsFor(spend, p._spendOpen);
  const body = records.length
    ? `<ul class="hk-spend-list">${records.map((r) => recordRow(p, r)).join('')}</ul>`
    : `<div class="hk-spend-empty">${escapeHTML(t('spend.empty'))}</div>`;
  return `
      <div class="hk-spend-records" id="hk-spend-records">
        <div class="hk-spend-records-head">${escapeHTML(label)}</div>
        ${body}
      </div>`;
}

/** The strip, and the records of the open total. Empty when {@link showSpend} says no. */
export function spendStrip(p: PanelHost): string {
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
  const purchases = `
      <button type="button" class="hk-spend-total hk-spend-purchases" data-spend-purchases>
        <span class="hk-spend-label">${escapeHTML(t('spend.purchases'))}</span>
        <span class="hk-spend-value">${escapeHTML(formatCost(p._hass, spend.purchases.total))}</span>
        <span class="hk-spend-count">${escapeHTML(tn('spend.appliances', spend.purchases.count))}</span>
      </button>`;
  return `
      <section class="hk-spend" aria-label="${escapeHTML(t('spend.heading'))}">
        <div class="hk-spend-head">
          <span class="hk-spend-heading">${escapeHTML(t('spend.heading'))}</span>
          <span class="hk-spend-help">${escapeHTML(t('spend.help'))}</span>
        </div>
        <div class="hk-spend-totals">
          ${totals.map((x) => totalButton(p, x.key, x.label, x.total, x.count)).join('')}
          ${purchases}
        </div>
        ${open ? recordList(p, spend, open.label) : ''}
      </section>`;
}

/** Make the totals and the record links live. */
export function wireSpend(p: PanelHost, root: ParentNode): void {
  root.querySelectorAll<HTMLElement>('.hk-spend-total[data-spend]').forEach((b) =>
    b.addEventListener('click', () => {
      const key = b.dataset.spend ?? '';
      p._spendOpen = p._spendOpen === key ? '' : key;
      p._render();
    }),
  );
  root
    .querySelector<HTMLElement>('[data-spend-purchases]')
    ?.addEventListener('click', () => p._navigate({ view: 'appliances', detail: null }));
  root.querySelectorAll<HTMLElement>('[data-spend-open]').forEach((a) =>
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const [kind, ...rest] = (a.dataset.spendOpen ?? '').split(':');
      const id = rest.join(':');
      if (!id) return;
      if (kind === 'asset') {
        p._navigate({ view: 'appliances', detail: { kind: 'asset', id, tab: 'history' } });
      } else {
        p._navigate({ view: 'tasks', detail: { kind: 'task', id, tab: 'history' } });
      }
    }),
  );
}
