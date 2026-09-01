/**
 * The detail page region: the full page a task or an appliance opens on, the sections
 * an appliance's sub-tabs switch between (parts, related tasks, documents, about,
 * sub-devices, history), the small row/link/id primitives they are built from, and
 * the wiring that makes a detail page live.
 *
 * `wireDetail` owns the whole detail branch of `_hydrate`, early return included: it
 * answers *whether the panel's hydration stops here*. A task page is a page of its
 * own and stops; an appliance page is rendered beside the appliance list and carries
 * on into the list wiring — which is why the shared handlers (`.detail-open`, the
 * device chips) must not be wired from both places for one render.
 *
 * `link`, `row`, `idRow` and `wirePartIcons` take no `PanelHost`: they are pure
 * functions of their arguments (or of the DOM they are handed).
 */

import { openDocument, openPartFile, documentIcon, documentLabel, signedFileKey } from './documents';
import { t, tn } from './i18n';
import { markdownBlock } from './markdown';
import {
  areaChip,
  deviceChip,
  isManagedOrphan,
  managedChip,
  sourceOwnedTask,
  tagChip,
  taskChipsHtml,
  virtualDeviceChip,
  wireDeviceChips,
} from './panel-chips';
import { openConfirmDialog } from './panel-dialogs';
import { completionGroupsFor, historyBody, wireHistory } from './panel-history';
import type { PanelHost } from './panel-host';
import { MDI_CONSUMABLE, MDI_OPEN_IN_NEW_ICON, MDI_WEAR } from './panel-icons';
import { assetAncestry } from './panel-lists';
import { consumableLinkLabel } from './panel-task-form';
import type { Asset, Task } from './types';
import {
  ASSET_TABS,
  areaName,
  assetSummary,
  btnAttrs,
  copyText,
  deviceName,
  dueLabel,
  escapeHTML,
  formatDate,
  formatDateTime,
  formatQuantity,
  isOverdue,
  navigateTo,
  recurrenceSummary,
  round1,
  safeFileHref,
  safeHref,
  scanRequired,
  tasksForAsset,
  toast,
  type AssetTab,
} from './utils';

export function detailView(p: PanelHost): string {
  const d = p._detail;
  if (!d) return '';
  if (d.kind === 'task') {
    const task = p._tasks.find((x) => x.id === d.id);
    if (!task) return `<ha-alert alert-type="warning">${escapeHTML(t('detail.gone'))}</ha-alert>`;
    return taskDetail(p, task);
  }
  const asset = p._assets.find((x) => x.id === d.id);
  if (!asset) return `<ha-alert alert-type="warning">${escapeHTML(t('detail.gone'))}</ha-alert>`;
  return assetDetail(p, asset);
}

/** Render a URL as a clickable anchor that opens in the browser (new tab). A
 *  non-http(s) value is shown as inert text (no href) — defence-in-depth against a
 *  `javascript:` URI that escapeHTML can't neutralise in an href. */
function link(url: string): string {
  const safe = escapeHTML(url);
  const href = safeHref(url);
  return href
    ? `<a href="${href}" target="_blank" rel="noopener">${safe}</a>`
    : `<span>${safe}</span>`;
}

/** One label/value row, omitted entirely when the value is empty. */
function row(label: string, value?: string | null, isHtml = false): string {
  if (value == null || value === '') return '';
  return `<div class="hk-detail-row"><span class="k">${escapeHTML(label)}</span><span class="v">${
    isHtml ? value : escapeHTML(value)
  }</span></div>`;
}

/**
 * A detail row carrying an object's id, with a button that copies it.
 *
 * Every `home_keeper.*` service identifies its target by this id, and until now it
 * appeared nowhere in the UI — so anyone automating against the services had to dig
 * a uuid out of a `list_tasks` response first. The services take the object's *name*
 * too, which covers most cases; the id is what settles the rest, where two things
 * share a name and only the id says which one you mean.
 */
function idRow(id: string | null | undefined, compact = false): string {
  if (!id) return '';
  const copy = `<ha-icon-button class="hk-copy" data-copy="${escapeHTML(
    id,
  )}" label="${escapeHTML(t('btn.copyId'))}" title="${escapeHTML(
    t('btn.copyId'),
  )}"><ha-icon icon="mdi:content-copy"></ha-icon></ha-icon-button>`;
  // Parts and documents are already dense rows, and an id is a footnote on them:
  // the compact form drops the label and the divider and tucks the id under the
  // name, so the list keeps its shape. A task or appliance page has a details card
  // with room for a labelled row like any other field.
  if (compact) {
    return `<div class="hk-id-inline"><code>${escapeHTML(id)}</code>${copy}</div>`;
  }
  return `<div class="hk-detail-row hk-id-row"><span class="k">${escapeHTML(
    t('detail.id'),
  )}</span><span class="v"><code>${escapeHTML(id)}</code>${copy}</span></div>`;
}

/** A human-readable line for a sensor task's binding, with live progress when the
 *  bound entity's current value is known: usage shows "consumed / target (entity)";
 *  threshold shows "entity: current (cmp value)"; state shows "entity: current
 *  (= wanted)". Falls back to the binding alone when the reading is unavailable. */
function sensorProgress(p: PanelHost, task: Task): string {
  const s = task.sensor;
  if (!s) return '';
  const state = p._hass?.states?.[s.entity_id];
  const raw = state
    ? s.attribute
      ? (state.attributes?.[s.attribute] as unknown)
      : state.state
    : undefined;
  const entity = s.entity_id;
  // State mode compares strings, so it must read `raw` before the numeric coercion
  // below turns a perfectly good `on` into NaN.
  if (s.mode === 'state') {
    const cond = `= ${s.state ?? ''}`;
    return raw == null || raw === ''
      ? `${entity} (${cond})`
      : `${entity}: ${String(raw)} (${cond})`;
  }
  const reading = raw == null || raw === '' ? NaN : Number(raw);
  if (s.mode === 'threshold') {
    const cond = `${s.comparison ?? ''} ${s.value ?? ''}`.trim();
    return Number.isNaN(reading)
      ? `${entity} (${cond})`
      : `${entity}: ${reading} (${cond})`;
  }
  // usage / meter
  const target = s.target ?? 0;
  const unit = s.unit ? ` ${s.unit}` : '';
  if (!Number.isNaN(reading) && s.baseline != null) {
    const consumed = Math.max(0, reading - s.baseline);
    return t('sensor.usageProgress', {
      consumed: `${round1(consumed)}${unit}`,
      target: `${target}${unit}`,
      entity,
    });
  }
  return t('sensor.usageTarget', { target: `${target}${unit}`, entity });
}

/** The meter's fill as an accessible bar, plus the time-backstop line when the
 *  task carries one. Rendered as HTML under the sensor row on the detail page:
 *  "how far through the interval am I" is the whole state of a usage task, and a
 *  bar reads it at a glance in a way "120 of 300 used" does not. Empty for a
 *  threshold or state task (neither has an interval to be partway through) or when
 *  the bound entity has no numeric reading. */
function sensorProgressBar(p: PanelHost, task: Task): string {
  const s = task.sensor;
  // Allowlist usage rather than excluding threshold: a mode added later must not
  // silently inherit the meter bar and render "0 of 0".
  if (!s || s.mode !== 'usage') return '';
  const parts: string[] = [];
  const state = p._hass?.states?.[s.entity_id];
  const raw = state ? (s.attribute ? state.attributes?.[s.attribute] : state.state) : undefined;
  const reading = raw == null || raw === '' ? NaN : Number(raw);
  const target = Number(s.target) || 0;
  if (!Number.isNaN(reading) && s.baseline != null && target > 0) {
    const consumed = Math.max(0, reading - s.baseline);
    const pct = Math.max(0, Math.min(100, (consumed / target) * 100));
    const label = t('sensor.usageRemaining', {
      remaining: `${round1(target - consumed)}${s.unit ? ` ${s.unit}` : ''}`,
    });
    parts.push(
      `<div class="hk-meter" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(
        pct,
      )}" aria-label="${escapeHTML(label)}"><span style="width:${pct.toFixed(1)}%"></span></div>` +
        `<div class="hk-meter-note">${escapeHTML(label)}</div>`,
    );
  }
  if (s.also_every) {
    const every = `${s.also_every.interval} ${t(`opt.unit.${s.also_every.unit}`)}`;
    parts.push(
      `<div class="hk-meter-note">${escapeHTML(
        s.combinator === 'all'
          ? t('sensor.backstopAll', { every })
          : t('sensor.backstopAny', { every }),
      )}</div>`,
    );
  }
  return parts.join('');
}

function historySection(p: PanelHost, kind: 'task' | 'asset', id: string): string {
  const groups = completionGroupsFor(p, kind, id);
  return `
      <div class="hk-section">${escapeHTML(t('btn.history'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner hk-hist-body">${historyBody(p, groups)}</div></ha-card>`;
}

function taskDetail(p: PanelHost, task: Task): string {
  const overdue = isOverdue(task);
  const statusChip = overdue
    ? `<ha-assist-chip class="hk-overdue" label="${escapeHTML(t('chip.overdue'))}"></ha-assist-chip>`
    : `<ha-assist-chip label="${escapeHTML(dueLabel(task, undefined, p._hass))}"></ha-assist-chip>`;
  const dev = task.device_id ? deviceChip(p, task.device_id) : '';
  // The task's *effective* area — its own, else its device's — so the page explains
  // which "Group by → Area" section the task lands in. When it's inherited, the
  // device chip sits right beside it and shows where it came from.
  const area = areaChip(p, task);
  const tag = tagChip(p, task);
  const managed = managedChip(p, task);
  const taskChips = taskChipsHtml(task);
  const mb = task.managed_by;

  // Source-owned tasks (reconciler-derived wear parts, synced problem sensors) are
  // managed by their source; the panel offers no edit/delete for them. A *manual*
  // consumable link (part.manual) is user-owned, so it stays editable/deletable.
  const sourceOwned = sourceOwnedTask(task);
  const orphaned = isManagedOrphan(p, task);
  // Duplicate opens the *create* form prefilled with a copy of this task — the answer
  // to a row of near-identical tasks that differ by a sensor and a name (#279). A task
  // Home Keeper doesn't own can't be copied, but it keeps a greyed button that says so
  // when pressed rather than silently missing one, the same treatment a
  // completion-blocked Done gets.
  //
  // Secondary, the same weight as Edit: the two are peer actions on this task, both
  // non-destructive and both opening the same drawer, so drawing one quieter would
  // rank them. It also keeps the live button plainly distinct from the greyed one —
  // at tertiary weight, "Duplicate" as bare text and "Duplicate" disabled differ only
  // by the shade of the label, which is not a difference anyone should have to squint
  // for. The row still reads at three weights (#262): Done fills, Edit and Duplicate
  // are tonal, Delete recedes to red text.
  //
  // `d-dup` must keep its `d-` prefix: `_openerKeyFor` reads it to hand the keyboard
  // back to this button when the drawer closes.
  const dupBtn = p._canDuplicate(task)
    ? `<ha-button ${btnAttrs('secondary')} class="d-dup">${escapeHTML(t('btn.duplicate'))}</ha-button>`
    : p._blockedDuplicate(task);
  // Say why Edit and Delete are missing rather than just omitting them. Withholding
  // both silently left a wear-part task's page reading "<task name> / Done" and
  // nothing else, which looks like a surface that forgot to render — the managed
  // path a few lines below has always explained itself.
  //
  // Only when nothing else on the page already does. A synced problem sensor carries
  // its owner's own `completion_prompt` ("Synced from binary_sensor.x — it clears
  // when the originating integration resolves it"), which says the same thing with
  // the specifics; adding a generic line above it would just be saying it twice.
  let manage =
    sourceOwned && !mb?.completion_prompt
      ? `<span class="hk-managed-info">${escapeHTML(t('managed.sourceOwned'))}</span>`
      : '';
  // A source-owned task offers no Edit and no Delete, but it still gets the greyed
  // Duplicate: "you can't copy this either, and here is why" is information the
  // sourceOwned caption above doesn't carry.
  manage = `${dupBtn}${manage}`;
  if (!sourceOwned) {
    const editBtn = `<ha-button ${btnAttrs('secondary')} class="d-edit">${escapeHTML(t('btn.edit'))}</ha-button>`;
    // Deletion protection only holds while the owner is present. Once orphaned
    // (owner uninstalled/disabled), the Delete button returns so the user can
    // clean the task up — otherwise "delete it from X instead" points nowhere.
    const deleteBtn =
      mb?.deletion_protected && !orphaned
        ? `<span class="hk-managed-info">${escapeHTML(t('managed.deleteBlocked', { name: mb.display_name }))}</span>`
        : `<ha-button ${btnAttrs('danger')} class="d-del">${escapeHTML(t('btn.delete'))}</ha-button>`;
    // "Edit in X" deep link when config_entry_id resolves to a loaded domain.
    const domain = mb?.config_entry_id ? p._entryDomains[mb.config_entry_id] : null;
    const openInBtn = domain && !orphaned
      ? `<ha-button ${btnAttrs('tertiary')} class="d-open-in" data-domain="${escapeHTML(domain)}">${escapeHTML(t('btn.openInIntegration', { name: mb!.display_name }))}</ha-button>`
      : '';
    // Duplicate sits between Edit and Delete: it is a non-destructive sibling of Edit,
    // and putting a benign action past a destructive one reads badly.
    manage = `${editBtn}${dupBtn}${deleteBtn}${openInBtn}`;
  }

  // When orphaned, explain why deletion is now allowed; otherwise show the
  // managing integration's optional completion hint.
  const completionHint =
    orphaned && mb
      ? `<div class="hk-managed-prompt">${escapeHTML(t('managed.orphanCleanup', { name: mb.display_name }))}</div>`
      : mb?.completion_prompt
        ? `<div class="hk-managed-prompt">${escapeHTML(mb.completion_prompt)}</div>`
        : '';

  const dormantTriggered = task.recurrence_type === 'triggered' && !task.next_due;
  const completedOneOff =
    task.recurrence_type === 'one-off' && !task.next_due && !!task.last_completed;
  const due = dormantTriggered
    ? t('due.monitored')
    : completedOneOff
      ? t('form.task.completedOn', { date: formatDateTime(task.last_completed, p._lang()) })
      : task.next_due
        ? formatDateTime(task.next_due, p._lang())
        : t('due.none');
  // Nothing to mark done while dormant — the integration arms it when the
  // monitored condition fires (e.g. a battery goes low) — or once a one-off is
  // already completed. A completion-blocked task (a synced problem sensor) keeps a
  // *disabled* Done that, on click, explains its source clears it (the managed
  // completion prompt also shows below).
  // A scan-locked task lands on the same disabled-Done treatment: the tap explains
  // that the tag is the way in.
  const doneBtn = dormantTriggered || completedOneOff
    ? ''
    : mb?.completion_blocked || scanRequired(task)
      ? p._blockedDone('d-done-blocked-wrap', task, 'primary')
      : `<ha-button ${btnAttrs('primary')} class="d-done">${escapeHTML(t('btn.done'))}</ha-button>`;
  // Notes get an inline editor right on the detail page: they're long-form prose
  // that renders as Markdown, so authoring deserves a full-width box with a live
  // preview rather than one cramped row among the schedule fields. (For a
  // problem-sensor task it's the *only* way in — its full edit dialog is
  // suppressed — and the note persists across the mirror being cleared, re-armed,
  // even deleted and recreated, so it's there next time the problem fires.) A note
  // its owning integration has locked stays read-only.
  const notesEditable = !(mb?.locked_fields ?? []).includes('notes');
  const notes = p._notesCardBody(
    { kind: 'task', id: task.id },
    task.notes || '',
    notesEditable,
    task.source?.problem_sensor ? t('note.placeholder') : t('note.placeholderMd'),
  );
  return `
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">
        <div class="hk-detail-title">${escapeHTML(task.name)}</div>
        <div class="hk-chips">${statusChip}${dev}${area}${tag}${taskChips}${managed}</div>
        <div class="hk-detail-actions">
          ${doneBtn}
          ${manage}
        </div>
        ${completionHint}
      </div></ha-card>
      <div class="hk-section">${escapeHTML(t('detail.schedule'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">
        ${row(t('field.recurrence_type'), recurrenceSummary(task))}
        ${task.recurrence_type === 'sensor' ? row(t('field.sensor_entity_id'), sensorProgress(p, task)) : ''}
        ${task.recurrence_type === 'sensor' ? sensorProgressBar(p, task) : ''}
        ${row(t('detail.nextDue'), due)}
        ${row(t('field.consumable_link'), consumableLinkLabel(p, task), true)}
        ${idRow(task.id)}
      </div></ha-card>
      <div class="hk-section">${escapeHTML(t('field.notes'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">${notes}</div></ha-card>
      ${historySection(p, 'task', task.id)}`;
}

function assetDetail(p: PanelHost, asset: Asset): string {
  const kindChip =
    asset.kind === 'virtual'
      ? virtualDeviceChip(p, asset)
      : asset.device_id
        ? deviceChip(p, asset.device_id)
        : '';
  const parentChip = asset.parent_asset_id
    ? `<ha-assist-chip label="${escapeHTML(
        '↳ ' + assetAncestry(p, asset.parent_asset_id),
      )}"></ha-assist-chip>`
    : '';
  const title =
    asset.name || deviceName(p._hass?.devices, asset.device_id) || t('appliance.fallbackName');
  const cost = asset.cost != null ? String(asset.cost) : '';
  // Structured (HA-wired) fields first, then the free-form metadata entries.
  const meta = (asset.metadata || [])
    .map((m) =>
      m.value ? row(m.label, m.type === 'link' ? link(m.value) : m.value, m.type === 'link') : '',
    )
    .join('');
  const details = [
    row(t('field.manufacturer'), asset.manufacturer),
    row(t('field.model'), asset.model),
    row(t('field.serial_number'), asset.serial_number),
    row(t('field.area_id'), areaName(p._hass?.areas, asset.area_id)),
    row(t('field.cost'), cost),
    meta,
    idRow(asset.id),
  ].join('');
  const detailsCard = details
    ? `<div class="hk-section">${escapeHTML(t('detail.about'))}</div>
         <ha-card class="hk-detail-card"><div class="hk-detail-inner">${details}</div></ha-card>`
    : '';
  const archived = Boolean(asset.archived_at);
  const archiveOrRestoreBtn = archived
    ? `<ha-button ${btnAttrs('secondary')} class="d-restore">${escapeHTML(t('btn.restore'))}</ha-button>`
    : `<ha-button ${btnAttrs('secondary')} class="d-archive">${escapeHTML(t('btn.archive'))}</ha-button>`;
  const archivedNote = archived
    ? `<div class="hk-managed-prompt">${escapeHTML(
        t('detail.archivedOn', { date: formatDate(asset.archived_at, p._lang()) }),
      )}</div>`
    : '';
  // Seven stacked sections made an appliance a page you scrolled rather than read,
  // and the section you wanted was rarely the first one. They become sub-tabs, each
  // a URL of its own so Back leaves a sub-tab like any other destination. The
  // section builders are unchanged — only one of them renders at a time.
  const bodies: Record<AssetTab, string> = {
    parts: partsSection(p, asset),
    tasks: relatedTasksSection(p, asset),
    documents: documentsSection(p, asset),
    details: `${detailsCard}${p._assetNotesSection(asset)}`,
    related: subdevicesSection(p, asset),
    history: historySection(p, 'asset', asset.id),
  };
  const tab = p._assetTab();
  // An empty section still gets its tab: a tab that came and went with its contents
  // would move every other tab under the cursor as an appliance gains a document.
  const body =
    bodies[tab] ||
    `<ha-alert alert-type="info">${escapeHTML(t('appliance.tabEmpty'))}</ha-alert>`;
  return `
      <ha-card class="hk-detail-card hk-asset-head"><div class="hk-detail-inner">
        <div class="hk-detail-title">${escapeHTML(title)}</div>
        <div class="hk-chips">${kindChip}${parentChip}</div>
        ${archivedNote}
        <div class="hk-detail-actions">
          <ha-button ${btnAttrs('primary')} class="d-edit">${escapeHTML(t('btn.edit'))}</ha-button>
          ${archiveOrRestoreBtn}
          <ha-button ${btnAttrs('danger')} class="d-del">${escapeHTML(t('btn.delete'))}</ha-button>
        </div>
      </div>
      <nav class="hk-subtabs" aria-label="${escapeHTML(asset.name)}">${assetSubtabs(p, asset, tab)}</nav>
      </ha-card>
      <div class="hk-subtab-body">${body}</div>`;
}

/** The appliance detail's sub-tab strip, each tab carrying how much it holds. */
function assetSubtabs(p: PanelHost, asset: Asset, current: AssetTab): string {
  const counts: Record<AssetTab, number | null> = {
    parts: asset.parts?.length ?? 0,
    tasks: tasksForAsset(asset, p._tasks).length,
    documents: asset.documents?.length ?? 0,
    details: null,
    related: p._assets.filter((a) => a.parent_asset_id === asset.id).length +
      (asset.related_device_ids?.length ?? 0),
    history: completionGroupsFor(p, 'asset', asset.id).length,
  };
  // Short labels: six tabs and their counts have to fit a strip that is already
  // sharing the row with the appliance list. The sections themselves keep their
  // fuller headings ("Parts & wear items"), which is where the room for them is.
  const labels: Record<AssetTab, string> = {
    parts: t('tab.parts'),
    tasks: t('tab.tasks'),
    documents: t('tab.documents'),
    details: t('detail.about'),
    related: t('tab.related'),
    history: t('btn.history'),
  };
  return ASSET_TABS.map((tab) => {
    const n = counts[tab];
    const count = n ? `<span class="hk-subtab-count">${escapeHTML(String(n))}</span>` : '';
    return `<button class="hk-subtab${tab === current ? ' active' : ''}" data-tab="${tab}"
        ${tab === current ? 'aria-current="page"' : ''}>${escapeHTML(labels[tab])}${count}</button>`;
  }).join('');
}

/** The appliance's documents (manuals/warranties/receipts). Both kinds render as a
 *  real anchor that opens in a new tab: an external link uses its own URL, an
 *  uploaded file a **pre-signed** one (`_signFiles` mints it and fills the `href` in;
 *  the `data-sign` key says which file the anchor points at). Never a JS-only handler
 *  — see the `documents.ts` header for why (issue #164). */
function documentsSection(p: PanelHost, asset: Asset): string {
  const docs = asset.documents || [];
  if (!docs.length) return '';
  const rows = docs
    .map((d) => {
      const name = escapeHTML(documentLabel(d));
      // Decorative: the anchor's text already names the document, and `pointer-events:
      // none` keeps the glyph from being anything a tap could land on *instead* of the
      // link.
      const open = `<ha-icon class="hk-doc-ext" icon="${MDI_OPEN_IN_NEW_ICON}" aria-hidden="true"></ha-icon>`;
      let inner: string;
      if (d.kind === 'file') {
        // The signed href may not be minted yet on a first paint; until it lands the
        // anchor keeps `tabindex` + the JS fallback wired in `wireDetailActions`.
        const key = signedFileKey({ kind: 'document', assetId: asset.id, id: d.id || '' });
        const href = p._signedFiles.getByKey(key);
        inner = `<a class="hk-doc-file" tabindex="0" data-sign="${escapeHTML(key)}" data-doc="${escapeHTML(
          d.id || '',
        )}"${href ? ` href="${safeFileHref(href)}"` : ''} target="_blank" rel="noopener noreferrer" title="${name}">${name}${open}</a>`;
      } else {
        // A link with no usable URL renders as plain text rather than an anchor to
        // nowhere: now that these *look* clickable, an empty href would reload the
        // panel on tap, which is worse than obviously-inert text.
        const href = safeHref(d.url);
        inner = href
          ? `<a class="hk-doc-file" href="${href}" target="_blank" rel="noopener noreferrer" title="${name}">${name}${open}</a>`
          : name;
      }
      return `<div class="hk-detail-row hk-doc-row"><span class="k"><ha-icon
          icon="${documentIcon(d)}"></ha-icon></span><span class="v">${inner}${idRow(
            d.id,
            true,
          )}</span></div>`;
    })
    .join('');
  return `<div class="hk-section">${escapeHTML(t('section.documents'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">${rows}</div></ha-card>`;
}

function partsSection(p: PanelHost, asset: Asset): string {
  const parts = asset.parts || [];
  if (!parts.length) return '';
  const chip = (label: string, cls = ''): string =>
    `<ha-assist-chip class="${cls}" label="${escapeHTML(label)}"></ha-assist-chip>`;
  const rows = parts
    .map((part) => {
      const isWear = part.type === 'wear';
      // Subtitle: the descriptive, identity bits (part number, vendor, cost).
      const sub: string[] = [];
      if (part.part_number) sub.push(part.part_number);
      if (part.vendor) sub.push(part.vendor);
      if (part.cost != null) sub.push(String(part.cost));
      const subLine = sub.length
        ? `<div class="hk-part-sub">${escapeHTML(sub.join(' · '))}</div>`
        : '';
      // The status a part is read for — how often it is replaced, when it last was,
      // and how many spares are left — is the same three questions for every part,
      // so each gets a fixed cell. On a wide screen the cells line up into columns
      // and the list becomes a table that can be scanned down; narrow, they fall
      // back to the wrapped chip row they have always been. A part that can't answer
      // one of the three still emits its cell, or the columns would not align.
      const cadence =
        isWear && part.replace_interval && part.replace_unit
          ? chip(
              t('part.every', {
                n: part.replace_interval,
                unit: t(`opt.unit.${part.replace_unit}`),
              }),
            )
          : '';
      const replaced = isWear
        ? chip(
            part.last_replaced
              ? t('part.replacedOn', { date: part.last_replaced })
              : t('part.neverReplaced'),
          )
        : '';
      const low = part.stock != null && part.reorder_at != null && part.stock <= part.reorder_at;
      let spares = '';
      if (part.stock != null) {
        // "In stock: 250 ml" — the unit rides with the number wherever stock is
        // shown, so a measured part never reads as a bare count of somethings.
        const onHand = formatQuantity(part.stock, part.stock_unit);
        spares = low
          ? chip(t('part.lowStock', { n: onHand }), 'hk-overdue')
          : chip(t('part.inStock', { n: onHand }));
        // What one completion takes off, when it isn't the plain single spare.
        if (part.consume_quantity != null) {
          spares += chip(t('part.perUse', { n: formatQuantity(part.consume_quantity, part.stock_unit) }));
        }
        // A bar for how much of the reorder point is left: "1 of 2" is a number to
        // work out, a half-empty amber bar is a glance. Only where a reorder point
        // says what "enough" means.
        if (part.reorder_at != null && part.reorder_at > 0) {
          const pct = Math.max(0, Math.min(100, (part.stock / (part.reorder_at * 2)) * 100));
          spares +=
            `<div class="hk-meter hk-part-meter${low ? ' low' : ''}" role="progressbar"` +
            ` aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(pct)}"` +
            ` aria-label="${escapeHTML(t('part.inStock', { n: formatQuantity(part.stock, part.stock_unit) }))}">` +
            `<span style="width:${pct.toFixed(1)}%"></span></div>`;
        }
      }
      const chipRow =
        cadence || replaced || spares
          ? `<div class="hk-part-chips">
                 <div class="hk-part-cell hk-part-cadence">${cadence}</div>
                 <div class="hk-part-cell hk-part-replaced">${replaced}</div>
                 <div class="hk-part-cell hk-part-spares">${spares}</div>
               </div>`
          : '';
      const badge = `<span class="hk-part-badge">${escapeHTML(t(`opt.part.${part.type}`))}</span>`;
      const name = part.url
        ? `<a href="${safeHref(part.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(part.name)}</a>`
        : escapeHTML(part.name);
      // An attached file (receipt/spec sheet/photo) opens via a **pre-signed** URL
      // filled in by `_signFiles`, the same native-anchor pattern asset documents use.
      const fileKey = signedFileKey({ kind: 'part', assetId: asset.id, id: part.id || '' });
      const fileHref = p._signedFiles.getByKey(fileKey);
      const fileLink = part.file_name
        ? `<a class="hk-part-file" tabindex="0" data-sign="${escapeHTML(
            fileKey,
          )}" data-part="${escapeHTML(part.id || '')}"${
            fileHref ? ` href="${safeFileHref(fileHref)}"` : ''
          } target="_blank" rel="noopener noreferrer" title="${escapeHTML(
            part.file_name,
          )}"><ha-icon icon="mdi:paperclip" aria-hidden="true"></ha-icon></a>`
        : '';
      // A part's notes render as Markdown like every other note, but read-only:
      // parts are edited as a whole in the appliance's parts editor, so letting one
      // field be edited inline while its siblings aren't would be inconsistent.
      const partNotes = part.notes
        ? `<div class="hk-part-notes">${markdownBlock(part.notes, 'hk-md-compact')}</div>`
        : '';
      return `
          <div class="hk-part-row ${isWear ? 'wear' : 'consumable'}">
            <div class="hk-part-ic">
              <ha-svg-icon data-mdi="${isWear ? 'wear' : 'consumable'}"></ha-svg-icon>
            </div>
            <div class="grow">
              <div class="hk-part-name">${name}${badge}${fileLink}</div>
              ${subLine}
              ${chipRow}
              ${partNotes}
              ${idRow(part.id, true)}
            </div>
          </div>`;
    })
    .join('');
  return `
      <div class="hk-section">${escapeHTML(t('section.parts'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner hk-parts">${rows}</div></ha-card>`;
}

/** Set the mdi `path` on each part-row icon (ha-svg-icon takes a property). */
function wirePartIcons(root: ShadowRoot): void {
  root.querySelectorAll<HTMLElement>('.hk-part-ic ha-svg-icon').forEach((el) => {
    (el as HTMLElement & { path?: string }).path =
      el.dataset.mdi === 'wear' ? MDI_WEAR : MDI_CONSUMABLE;
  });
}

function relatedTasksSection(p: PanelHost, asset: Asset): string {
  const tasks = tasksForAsset(asset, p._tasks);
  if (!tasks.length) return '';
  const rows = tasks
    .map((task) => {
      const overdue = isOverdue(task);
      const chip = overdue
        ? `<ha-assist-chip class="hk-overdue" label="${escapeHTML(t('chip.overdue'))}"></ha-assist-chip>`
        : `<ha-assist-chip label="${escapeHTML(dueLabel(task, undefined, p._hass))}"></ha-assist-chip>`;
      return `
          <div class="hk-rel detail-open" data-detail-kind="task" data-detail-id="${escapeHTML(
            task.id,
          )}" role="button" tabindex="0">
            <div class="grow"><div class="hk-name">${escapeHTML(task.name)}</div>
              <div class="hk-meta">${escapeHTML(recurrenceSummary(task))}</div></div>
            <div class="hk-chips">${chip}</div>
          </div>`;
    })
    .join('');
  return `
      <div class="hk-section">${escapeHTML(t('detail.relatedTasks'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">${rows}</div></ha-card>`;
}

function subdevicesSection(p: PanelHost, asset: Asset): string {
  const subs = p._assets.filter((a) => a.parent_asset_id === asset.id);
  if (!subs.length) return '';
  const rows = subs
    .map((sub) => {
      const title =
        sub.name || deviceName(p._hass?.devices, sub.device_id) || t('appliance.fallbackName');
      return `
          <div class="hk-rel detail-open" data-detail-kind="asset" data-detail-id="${escapeHTML(
            sub.id,
          )}" role="button" tabindex="0">
            <div class="grow"><div class="hk-name">${escapeHTML(title)}</div>
              <div class="hk-meta">${escapeHTML(assetSummary(sub, p._hass?.areas))}</div></div>
          </div>`;
    })
    .join('');
  return `
      <div class="hk-section">${escapeHTML(tn('asset.subdevices', subs.length))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">${rows}</div></ha-card>`;
}

// ── hydration ───────────────────────────────────────────────────────────────

/**
 * Wire a detail page, and answer whether the panel's hydration is finished.
 *
 * A task detail is a page of its own and stops here, so the wiring it shares with the
 * list views happens now rather than after — hence the `true`.
 *
 * An appliance detail keeps going: it is rendered beside the appliance list, so it
 * needs the top tabs, the list controls and the list rows too. Crucially it must NOT
 * wire the shared handlers twice — a second `.detail-open` listener pushed two history
 * entries per click, so Back out of a task opened from an appliance landed back on the
 * same task.
 */
export function wireDetail(p: PanelHost, root: ShadowRoot): boolean {
  if (p._detail) {
    root.getElementById('back-btn')?.addEventListener('click', () => p._closeDetail());
    wireDetailActions(p, root);
    wirePartIcons(root);
    wireHistory(p, root);
    root.querySelectorAll<HTMLElement>('.hk-subtab').forEach((b) =>
      b.addEventListener('click', () => {
        const tab = b.dataset.tab;
        if (tab && (ASSET_TABS as readonly string[]).includes(tab)) {
          p._setAssetTab(tab as AssetTab);
        }
      }),
    );
    // Both kinds of detail page carry an id row with a copy button.
    wireCopyButtons(p, root);
    if (p._detail.kind !== 'asset') {
      wireDetailOpeners(p, root);
      wireDeviceChips(root);
      return true;
    }
  }
  return false;
}

/** Wire every id row's copy button. One pass covers the task and appliance
 *  pages plus the part and document rows, which all render the same row. */
function wireCopyButtons(p: PanelHost, root: ShadowRoot): void {
  root.querySelectorAll<HTMLElement>('.hk-copy[data-copy]').forEach((el) => {
    el.addEventListener('click', () => {
      const id = el.dataset.copy;
      if (!id) return;
      // Report what actually happened: over plain HTTP the clipboard API is absent
      // and the fallback can still fail, and claiming a copy that never landed
      // leaves the user pasting whatever was there before.
      void copyText(id).then((ok) => {
        toast(p, ok ? t('toast.idCopied') : t('toast.copyFailed'));
      });
    });
  });
}

/** Wire every `.detail-open` row to open its object's detail page. */
export function wireDetailOpeners(p: PanelHost, root: ShadowRoot): void {
  root.querySelectorAll<HTMLElement>('.detail-open').forEach((el) => {
    const go = (): void => {
      const kind = el.dataset.detailKind;
      const id = el.dataset.detailId;
      if ((kind === 'task' || kind === 'asset') && id) p._openDetail(kind, id);
    };
    el.addEventListener('click', go);
    el.addEventListener('keydown', (e) => {
      const key = (e as KeyboardEvent).key;
      if (key === 'Enter' || key === ' ') {
        e.preventDefault();
        go();
      }
    });
  });
}

/** Wire the detail page's Done / Edit / Delete / Open-in buttons. */
function wireDetailActions(p: PanelHost, root: ShadowRoot): void {
  const d = p._detail;
  if (!d) return;
  // The `.d-del` variant used to be forced here, because `destructive` never
  // reflected into a colour. `variant` is a real reactive attribute on ha-button,
  // so `btnAttrs('danger')` in the markup does it — and does it for *every* match,
  // which this querySelector (singular) never did.
  if (d.kind === 'task') {
    const task = p._tasks.find((x) => x.id === d.id);
    if (!task) return;
    root.querySelector('.d-done')?.addEventListener('click', () => void p._complete(task));
    root
      .querySelector('.d-done-blocked-wrap')
      ?.addEventListener('click', () => p._notifyBlocked(task));
    root.querySelector('.d-edit')?.addEventListener('click', () => p._openEdit(task));
    root.querySelector('.d-dup')?.addEventListener('click', () => p._openDuplicate(task));
    // A greyed Duplicate is a span carrying the tap (a disabled button swallows
    // clicks), so keyboard activation has to be wired by hand — a `role="button"`
    // that only answers the mouse is worse than no button at all.
    const dupBlocked = root.querySelector<HTMLElement>('.d-dup-blocked');
    if (dupBlocked) {
      const explain = (): void => p._notifyNoDuplicate(task);
      dupBlocked.addEventListener('click', explain);
      dupBlocked.addEventListener('keydown', (e) => {
        const key = (e as KeyboardEvent).key;
        if (key === 'Enter' || key === ' ') {
          e.preventDefault();
          explain();
        }
      });
    }
    p._wireNoteEditor(root, { kind: 'task', id: task.id });
    root.querySelector('.d-del')?.addEventListener('click', () => {
      openConfirmDialog(p, t('confirm.deleteTask', { name: task.name }), () => {
        // The detail is about to vanish: replace it with its list so Forward
        // can't return to a deleted task.
        p._navigate({ view: 'tasks', detail: null }, true);
        void p._delete(task);
      });
    });
    // "Edit in X" deep link: navigate to the managing integration's config page
    // (same helper the Companions "Configure" button uses).
    root.querySelectorAll<HTMLElement>('.d-open-in').forEach((btn) => {
      btn.addEventListener('click', () => {
        const domain = btn.dataset.domain;
        if (domain) navigateTo(`/config/integrations/integration/${domain}`);
      });
    });
    return;
  }
  const asset = p._assets.find((x) => x.id === d.id);
  if (!asset) return;
  root.querySelector('.d-edit')?.addEventListener('click', () => p._openEditAsset(asset));
  p._wireNoteEditor(root, { kind: 'asset', id: asset.id });
  root.querySelector('.d-archive')?.addEventListener('click', () => void p._archiveAsset(asset));
  root.querySelector('.d-restore')?.addEventListener('click', () => void p._restoreAsset(asset));
  root.querySelector('.d-del')?.addEventListener('click', () => {
    const name =
      asset.name || deviceName(p._hass?.devices, asset.device_id) || t('appliance.fallbackName');
    openConfirmDialog(p, t('confirm.deleteAsset', { name }), () => {
      // The detail is about to vanish: replace it with its list so Forward
      // can't return to a deleted appliance.
      p._navigate({ view: 'appliances', detail: null }, true);
      void p._deleteAsset(asset);
    });
  });
  // Uploaded files (asset documents and part attachments) open via a short-lived
  // signed URL carried on the anchor's `href` — `_signFiles` mints it right after
  // this render. These handlers are the **fallback** for the window before that
  // lands (and for a sign that failed outright); once the anchor has an href the
  // browser's native navigation owns the click, so they stand down.
  const fallback = (el: HTMLElement, open: () => void): void => {
    const run = (e: Event): void => {
      if (el.getAttribute('href')) return; // native tap — don't double-open
      e.preventDefault();
      open();
    };
    el.addEventListener('click', run);
    el.addEventListener('keydown', (e) => {
      if ((e as KeyboardEvent).key === 'Enter' || (e as KeyboardEvent).key === ' ') run(e);
    });
  };
  root.querySelectorAll<HTMLElement>('a.hk-doc-file[data-doc]').forEach((el) => {
    fallback(el, () => {
      const doc = asset.documents?.find((x) => x.id === el.dataset.doc);
      if (doc && p._hass) void openDocument(p._hass, asset.id, doc);
    });
  });
  root.querySelectorAll<HTMLElement>('a.hk-part-file[data-part]').forEach((el) => {
    fallback(el, () => {
      const part = asset.parts?.find((x) => x.id === el.dataset.part);
      if (part && p._hass) void openPartFile(p._hass, asset.id, part);
    });
  });
}
