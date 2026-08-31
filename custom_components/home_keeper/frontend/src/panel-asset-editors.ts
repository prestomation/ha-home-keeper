/**
 * The three editors inside the appliance drawer: its documents, its free-form metadata
 * fields, and its parts (each with its own attached file).
 *
 * **They all mutate `_assetEdit.asset` in place.** Every field handler merges into the
 * same object the drawer was opened with, and `_submitAssetForm` reads that object back
 * when the user saves — so nothing here may replace `_assetEdit.asset` or hold a copy of
 * it, or the save writes values the user never sees. (`panel-host.ts` carries the same
 * warning on the field.) Documents are the exception that proves it: once the appliance
 * has an id they are managed live, each through its own backend call, and the working
 * copy is refreshed from the response.
 *
 * Everything is a free function over a `PanelHost` (see `panel-host.ts`); the schema
 * builders and the two subtitle helpers take no host at all, being pure functions of the
 * entry they describe. Uploading is `panel-upload.ts`'s job — this module calls into it
 * and never the other way round.
 */

import * as api from './api';
import {
  documentIcon,
  documentLabel,
  documentTypeLabel,
  formatBytes,
  openDocument,
  openPartFile,
  signedFileKey,
  type SignedFileRef,
} from './documents';
import {
  selBool,
  selDate,
  selNumber,
  selSelect,
  selText,
  selUnit,
  type FormField,
} from './forms';
import { t } from './i18n';
import type { MarkdownPreview } from './markdown';
import { collapsibleSection, section, setIcon } from './panel-history';
import type { PanelHost } from './panel-host';
import { MDI_DELETE, MDI_EDIT, MDI_OPEN_IN_NEW } from './panel-icons';
import { UPLOAD_KEY_DOCUMENT, uploadKeyPart } from './panel-types';
import {
  filePicker,
  renderUploadStatus,
  runUpload,
  setAssetError,
  uploadButtonLabel,
} from './panel-upload';
import type { Asset, AssetDocument, Hass, MetadataEntry, MetadataType, Part } from './types';
import { escapeHTML, isHttpUrl, randomId, setBtnWeight } from './utils';

// The smallest a part quantity that must be *positive* can be. Stock itself may be
// zero (you're out), but "how much a completion uses" and "how much a restock adds"
// can't be — a zero there is a field that quietly does nothing. A number selector
// has no exclusive minimum, so the floor is one step of the stored precision.
const MIN_POSITIVE_QUANTITY = 0.001;

// ── shared row scaffolds ────────────────────────────────────────────────────

/**
 * The card an attached file is shown as: icon, name, a details subtitle, and the
 * actions on the right (Open, an optional Edit, Remove — in that order).
 *
 * One scaffold for an appliance document and for a part's file, which were built side
 * by side and had already drifted in their subtitle handling. What genuinely differs is
 * passed: the icon, what the row is called, and what each action does. *open* is omitted
 * entirely for a row with nothing to open (an unsaved appliance's uploaded file); its
 * `target` may still be undefined, which leaves the anchor on its JS fallback.
 */
function fileCard(
  p: PanelHost,
  spec: {
    icon: string;
    name: string;
    subtitle: string;
    open?: { target: SignedFileRef | string | undefined; fallback: () => void };
    edit?: { label: string; onClick: () => void };
    remove: { label: string; onClick: () => void };
  },
): HTMLElement {
  const card = document.createElement('div');
  card.className = 'hk-doc-card';

  const ic = document.createElement('div');
  ic.className = 'hk-doc-ic';
  const icon = document.createElement('ha-icon');
  icon.setAttribute('icon', spec.icon);
  ic.appendChild(icon);

  const main = document.createElement('div');
  main.className = 'hk-doc-main';
  const name = document.createElement('div');
  name.className = 'hk-doc-name';
  name.textContent = spec.name;
  main.appendChild(name);
  if (spec.subtitle) {
    const sub = document.createElement('div');
    sub.className = 'hk-doc-sub';
    sub.textContent = spec.subtitle;
    main.appendChild(sub);
  }

  const actions = document.createElement('div');
  actions.className = 'hk-doc-actions';
  if (spec.open) actions.appendChild(openFileAnchor(p, spec.open.target, spec.open.fallback));
  if (spec.edit) {
    const edit = document.createElement('ha-icon-button');
    edit.setAttribute('label', spec.edit.label);
    setIcon(edit, MDI_EDIT);
    edit.addEventListener('click', spec.edit.onClick);
    actions.appendChild(edit);
  }
  const del = document.createElement('ha-icon-button');
  del.setAttribute('label', spec.remove.label);
  setIcon(del, MDI_DELETE);
  del.addEventListener('click', spec.remove.onClick);
  actions.appendChild(del);

  card.append(ic, main, actions);
  return card;
}

/**
 * The framed row one metadata entry and one part are both edited in: an index-labelled
 * head and a Remove that asks first. Returns the box for the caller to fill with the
 * entry's own form.
 *
 * *confirmLabel* is a function because the original wording is resolved at click time
 * (a named entry says its name), and *onRemove* drops the entry from whichever list it
 * belongs to — the two things that actually differ between the two editors.
 */
function entryBox(
  p: PanelHost,
  i: number,
  spec: {
    title: string;
    removeLabel: string;
    confirmLabel: () => string;
    onRemove: () => void;
  },
): HTMLElement {
  const box = document.createElement('div');
  box.className = 'hk-part';
  box.dataset.idx = String(i);
  const head = document.createElement('div');
  head.className = 'hk-part-head';
  head.innerHTML = `<span class="label">${escapeHTML(spec.title)}</span>`;
  const del = document.createElement('ha-icon-button');
  del.className = 'part-del';
  del.setAttribute('label', spec.removeLabel);
  setIcon(del, MDI_DELETE);
  del.addEventListener('click', () => {
    p._openConfirmDialog(spec.confirmLabel(), spec.onRemove);
  });
  head.appendChild(del);
  box.appendChild(head);
  return box;
}

// ── documents ───────────────────────────────────────────────────────────────

/** Documents editor: list existing docs with a remove button, plus controls to add
 *  a link or upload a file. Documents are managed live (each its own backend call),
 *  so a file upload needs an already-saved appliance (it must have an id). */
export function renderDocumentsEditor(p: PanelHost, inner: HTMLElement): void {
  inner.appendChild(section(t('section.documents')));
  const docs = p._assetEdit.asset?.documents || [];

  // Existing documents: each is a clear card (icon + name + details) with Open /
  // Edit / Remove actions — except the one being edited, which shows its form.
  docs.forEach((d) => {
    if (d.id && p._assetEdit.editingDocId === d.id) renderDocumentEdit(p, inner, d);
    else renderDocumentCard(p, inner, d);
  });

  renderDocumentAdd(p, inner);
}

/** One existing document as a read row: icon, name, a details subtitle, and the
 *  Open (link/signed-file URL) / Edit / Remove actions. */
function renderDocumentCard(p: PanelHost, inner: HTMLElement, d: AssetDocument): void {
  // Open is only meaningful for a link with a URL, or a file already saved (it owns
  // a blob keyed by its id — a brand-new asset's links have no file to open).
  const canOpen = d.kind === 'file' ? Boolean(d.id) : Boolean(d.url);
  // A real link for the same reason the detail page's rows are — a `window.open`
  // after the async sign never fires in the iOS app's WKWebView.
  const assetId = p._assetEdit.asset?.id;
  const target: SignedFileRef | string | undefined =
    d.kind === 'file'
      ? assetId && d.id
        ? { kind: 'document', assetId, id: d.id }
        : undefined
      : d.url;
  inner.appendChild(
    fileCard(p, {
      icon: documentIcon(d),
      name: documentLabel(d),
      subtitle: documentSubtitle(d),
      open: canOpen ? { target, fallback: () => openDocumentFallback(p, d) } : undefined,
      edit: {
        label: t('btn.edit'),
        onClick: () => {
          p._assetEdit.editingDocId = d.id;
          p._render();
        },
      },
      remove: {
        label: t('btn.removeDocument'),
        onClick: () => void removeDocument(p, d),
      },
    }),
  );
}

/** The name + URL a link document is described by. The same grid serves the add form
 *  and an existing link's inline editor, which is why it is written once. */
function documentSchema(): FormField[] {
  return [
    {
      name: '',
      type: 'grid',
      schema: [
        { name: 'doc_name', selector: selText() },
        { name: 'doc_url', selector: selText() },
      ],
    },
  ];
}

/** Inline editor for one document: a link edits name + URL; a file (upload-only) edits
 *  only its display name. Save commits, Cancel discards. */
function renderDocumentEdit(p: PanelHost, inner: HTMLElement, d: AssetDocument): void {
  const box = document.createElement('div');
  box.className = 'hk-part hk-doc-edit';
  const isLink = d.kind === 'link';
  const draft = { name: d.name || '', url: d.kind === 'link' ? d.url ?? '' : '' };
  const schema: FormField[] = isLink ? documentSchema() : [{ name: 'doc_name', selector: selText() }];
  const data = isLink ? { doc_name: draft.name, doc_url: draft.url } : { doc_name: draft.name };
  box.appendChild(
    p._makeForm(schema, data, (value) => {
      if ('doc_name' in value) draft.name = String(value.doc_name ?? '');
      if ('doc_url' in value) draft.url = String(value.doc_url ?? '');
    }),
  );

  const row = document.createElement('div');
  row.className = 'hk-doc-edit-actions';
  const save = document.createElement('ha-button');
  setBtnWeight(save, 'primary');
  save.textContent = t('btn.save');
  save.addEventListener('click', () =>
    void updateDocument(p, d, isLink ? { name: draft.name, url: draft.url } : { name: draft.name }),
  );
  const cancel = document.createElement('ha-button');
  setBtnWeight(cancel, 'tertiary');
  cancel.textContent = t('btn.cancel');
  cancel.addEventListener('click', () => {
    p._assetEdit.editingDocId = undefined;
    p._render();
  });
  row.append(save, cancel);
  box.appendChild(row);
  inner.appendChild(box);
}

/** The "add a document" area: a name + URL link form (always available, even before
 *  the appliance is saved) and — once saved — a file upload control. */
function renderDocumentAdd(p: PanelHost, inner: HTMLElement): void {
  const assetId = p._assetEdit.asset?.id;
  const add = document.createElement('div');
  add.className = 'hk-doc-add';
  const title = document.createElement('div');
  title.className = 'hk-doc-add-title';
  title.textContent = t('doc.addHeading');
  add.appendChild(title);

  const draft: { name: string; url: string } = { name: '', url: '' };
  add.appendChild(
    p._makeForm(documentSchema(), { doc_name: '', doc_url: '' }, (value) => {
      draft.name = String(value.doc_name ?? '');
      draft.url = String(value.doc_url ?? '');
    }),
  );

  const seedRow = document.createElement('div');
  seedRow.className = 'hk-meta-seeds';
  const addLink = document.createElement('ha-button');
  setBtnWeight(addLink, 'secondary');
  addLink.textContent = t('btn.addLink');
  addLink.addEventListener('click', () => void addLinkDocument(p, draft.name, draft.url));
  seedRow.appendChild(addLink);

  // A file can only be uploaded once the appliance exists (its id keys the blob).
  if (assetId) {
    const upload = document.createElement('ha-button');
    setBtnWeight(upload, 'secondary');
    upload.textContent = uploadButtonLabel(p, UPLOAD_KEY_DOCUMENT, t('btn.uploadFile'));
    const picker = filePicker(p, upload, (file) => void uploadDocument(p, file));
    seedRow.append(upload, picker);
  }
  add.appendChild(seedRow);
  // Progress / failure for this control, right where the user pressed the button.
  renderUploadStatus(p, add, UPLOAD_KEY_DOCUMENT);

  if (!assetId) {
    const hint = document.createElement('div');
    hint.className = 'hk-meta';
    hint.textContent = t('doc.saveFirstHint');
    add.appendChild(hint);
  }
  inner.appendChild(add);
}

/** Human-readable details line for a document card: a link shows its URL; a file shows
 *  filename · size · type (e.g. "manual.pdf · 1.2 MB · PDF"). */
function documentSubtitle(d: AssetDocument): string {
  if (d.kind === 'link') return d.url || '';
  const parts: string[] = [];
  if (d.filename) parts.push(d.filename);
  const size = formatBytes(d.size);
  if (size) parts.push(size);
  const type = documentTypeLabel(d.content_type);
  if (type) parts.push(type);
  return parts.join(' · ');
}

/**
 * The editor's "Open" affordance: an anchor styled like the icon-buttons beside it,
 * so activating it is a native navigation rather than a scripted one (the same reason
 * the detail page's document rows are anchors — see `documents.ts`). It carries the
 * icon *itself* rather than wrapping an `ha-icon-button`: nesting one interactive
 * control inside another leaves it to the browser whether the click reaches the link,
 * and "it depends on the browser" is precisely the bug being fixed here.
 *
 * *target* is the stored URL of a link document, a `SignedFileRef` for an uploaded
 * file (the href is stamped on by `_signFiles` once minted — the anchor carries the
 * cache key meanwhile), or undefined when neither is available. *fallback* covers the
 * window before a signed href lands, and stands down as soon as there is one.
 */
function openFileAnchor(
  p: PanelHost,
  target: SignedFileRef | string | undefined,
  fallback: () => void,
): HTMLAnchorElement {
  const a = document.createElement('a');
  a.className = 'hk-doc-open';
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.title = t('btn.openDocument');
  a.setAttribute('aria-label', a.title);
  if (typeof target === 'string') {
    // Set as a property, so the raw URL (not the HTML-escaped `safeHref` form) lands
    // on the anchor — same validation, no double-escaping of `&` in a query string.
    if (isHttpUrl(target)) a.href = target;
  } else if (target) {
    const key = signedFileKey(target);
    a.dataset.sign = key;
    const href = p._signedFiles.getByKey(key);
    if (href) a.href = href;
  }
  a.addEventListener('click', (e) => {
    if (a.getAttribute('href')) return; // native tap — don't double-open
    e.preventDefault();
    fallback();
  });
  const icon = document.createElement('ha-svg-icon');
  setIcon(icon, MDI_OPEN_IN_NEW);
  a.appendChild(icon);
  return a;
}

/** Open a document from the editor: a link opens its URL; a file opens via a signed
 *  URL. A link needs no asset id (it carries its own URL), so an unsaved asset's
 *  links still open. Fallback only — `openFileAnchor` is the primary path. */
function openDocumentFallback(p: PanelHost, d: AssetDocument): void {
  if (p._hass) void openDocument(p._hass, p._assetEdit.asset?.id ?? '', d);
}

/** Append the live document list onto the in-progress edit copy and re-render. */
function setEditDocuments(p: PanelHost, asset: Asset): void {
  if (p._assetEdit.asset) p._assetEdit.asset.documents = asset.documents || [];
  p._render();
}

/**
 * The envelope all three document mutations share.
 *
 * A saved appliance persists documents through the service; a brand-new one collects
 * them on the working copy so they ride along in the create payload. *done* runs once
 * the change has stuck, on either path — never after a failed call, which is what keeps
 * a rejected edit's form open on its error.
 */
async function mutateDocuments(
  p: PanelHost,
  op: {
    local: () => void;
    remote: (hass: Hass, assetId: string) => Promise<Asset>;
    done?: () => void;
  },
): Promise<void> {
  const assetId = p._assetEdit.asset?.id;
  if (!assetId) {
    op.local();
    op.done?.();
    p._render();
    return;
  }
  if (!p._hass) return;
  try {
    const asset = await op.remote(p._hass, assetId);
    op.done?.();
    setEditDocuments(p, asset);
  } catch (err) {
    setAssetError(p, String((err as { message?: string })?.message || err));
    p._render();
  }
}

async function addLinkDocument(p: PanelHost, name: string, url: string): Promise<void> {
  if (!url.trim()) return;
  await mutateDocuments(p, {
    local: () => {
      const list = [...(p._assetEdit.asset?.documents || [])];
      list.push({ id: randomId(), kind: 'link', name, url });
      p._assetEdit.asset!.documents = list;
    },
    remote: (hass, assetId) => api.addAssetDocument(hass, assetId, { name, url }),
  });
}

async function updateDocument(
  p: PanelHost,
  doc: AssetDocument,
  changes: { name: string; url?: string },
): Promise<void> {
  if (!doc.id) return;
  const docId = doc.id;
  await mutateDocuments(p, {
    local: () => {
      const list = [...(p._assetEdit.asset?.documents || [])];
      const idx = list.findIndex((d) => d.id === doc.id);
      if (idx >= 0) {
        const merged: AssetDocument = { ...list[idx], name: changes.name };
        if (merged.kind === 'link' && changes.url !== undefined) merged.url = changes.url;
        list[idx] = merged;
        p._assetEdit.asset!.documents = list;
      }
    },
    remote: (hass, assetId) => api.updateAssetDocument(hass, assetId, docId, changes),
    done: () => {
      p._assetEdit.editingDocId = undefined;
    },
  });
}

async function removeDocument(p: PanelHost, doc: AssetDocument): Promise<void> {
  if (!doc.id) return;
  const docId = doc.id;
  if (p._assetEdit.editingDocId === doc.id) p._assetEdit.editingDocId = undefined;
  await mutateDocuments(p, {
    local: () => {
      p._assetEdit.asset!.documents = (p._assetEdit.asset?.documents || []).filter(
        (d) => d.id !== doc.id,
      );
    },
    remote: (hass, assetId) => api.removeAssetDocument(hass, assetId, docId),
  });
}

async function uploadDocument(p: PanelHost, file: File): Promise<void> {
  const assetId = p._assetEdit.asset?.id;
  if (!p._hass || !assetId) return;
  const documentId = randomId();
  const hass = p._hass;
  const asset = await runUpload(p, UPLOAD_KEY_DOCUMENT, file, (opts) =>
    api.uploadAssetDocument(hass, assetId, documentId, file, undefined, opts),
  );
  if (asset) setEditDocuments(p, asset);
}

// ── metadata ────────────────────────────────────────────────────────────────

/** Schema for one free-form metadata entry. The value control swaps by type, and
 *  a `date` entry adds a "track as sensor" toggle (opt-in automation). */
function metadataSchema(m: MetadataEntry): FormField[] {
  const valueSelector = m.type === 'date' ? selDate() : selText();
  const fields: FormField[] = [
    {
      name: '',
      type: 'grid',
      schema: [
        {
          name: 'type',
          selector: selSelect([
            { value: 'text', label: t('opt.meta.text') },
            { value: 'link', label: t('opt.meta.link') },
            { value: 'date', label: t('opt.meta.date') },
          ]),
        },
        { name: 'label', selector: selText() },
      ],
    },
    { name: 'value', selector: valueSelector },
  ];
  if (m.type === 'date') fields.push({ name: 'track', selector: selBool() });
  return fields;
}

export function renderMetadataEditor(p: PanelHost, inner: HTMLElement): void {
  const entries = p._assetEdit.asset?.metadata || [];
  const { details, body } = collapsibleSection(p, t('section.metadata'), 'metadata', entries.length);
  inner.appendChild(details);
  entries.forEach((m, i) => {
    const box = entryBox(p, i, {
      title: t('section.meta_n', { n: i + 1 }),
      removeLabel: t('btn.removeField'),
      confirmLabel: () =>
        m.label
          ? t('confirm.removeNamed', { name: m.label })
          : t('confirm.removeField', { n: i + 1 }),
      onRemove: () => {
        const list = p._assetEdit.asset?.metadata || [];
        p._assetEdit.asset!.metadata = list.filter((_, j) => j !== i);
      },
    });

    const form = p._makeForm(
      metadataSchema(m),
      {
        type: m.type ?? 'text',
        label: m.label ?? '',
        value: m.value ?? '',
        track: Boolean(m.track),
      },
      (value) => {
        const prevType = p._assetEdit.asset?.metadata?.[i]?.type;
        const newType = (value.type as MetadataType) ?? 'text';
        const updated: MetadataEntry = {
          id: m.id,
          type: newType,
          label: String(value.label ?? ''),
          // A date control emits selector-shaped strings; text/link emit text.
          value: value.value != null ? String(value.value) : '',
          // `track` only applies to dates — drop it otherwise so it can't strand.
          track: newType === 'date' ? Boolean(value.track) : undefined,
        };
        const list = [...(p._assetEdit.asset?.metadata || [])];
        list[i] = updated;
        p._assetEdit.asset!.metadata = list;
        // Re-render when the type changes so the value control (and the date
        // "track" toggle) swaps to match.
        if (newType !== prevType) p._render();
      },
    );
    box.appendChild(form);

    if (m.type === 'date') {
      const note = document.createElement('div');
      note.className = 'hk-meta';
      note.textContent = t('meta.trackHint');
      box.appendChild(note);
    }
    body.appendChild(box);
  });

  // Quick-add seeds for the common fields (each prelabeled, right type), plus a
  // generic blank entry — they're all just entries in the list.
  const seeds: { label: string; type: MetadataType }[] = [
    { label: t('meta.seed.serial'), type: 'text' },
    { label: t('meta.seed.warranty_expiry'), type: 'date' },
    { label: t('meta.seed.purchase_date'), type: 'date' },
    { label: t('meta.seed.install_date'), type: 'date' },
    { label: t('meta.seed.warranty_provider'), type: 'text' },
    { label: t('meta.seed.vendor'), type: 'text' },
    { label: t('meta.seed.product_link'), type: 'link' },
    { label: t('meta.seed.notes'), type: 'text' },
  ];
  const addEntry = (entry: MetadataEntry): void => {
    const list = [...(p._assetEdit.asset?.metadata || [])];
    list.push(entry);
    p._assetEdit.asset!.metadata = list;
    p._render();
  };
  const seedRow = document.createElement('div');
  seedRow.className = 'hk-meta-seeds';
  for (const s of seeds) {
    const b = document.createElement('ha-button');
    setBtnWeight(b, 'secondary');
    b.textContent = s.label;
    b.addEventListener('click', () => addEntry({ type: s.type, label: s.label, value: '' }));
    seedRow.appendChild(b);
  }
  const custom = document.createElement('ha-button');
  setBtnWeight(custom, 'secondary');
  custom.textContent = t('btn.addField');
  custom.addEventListener('click', () => addEntry({ type: 'text', label: '', value: '' }));
  seedRow.appendChild(custom);
  body.appendChild(seedRow);
}

// ── parts ───────────────────────────────────────────────────────────────────

function partSchema(part: Part): FormField[] {
  const isWear = part.type === 'wear';
  const base: FormField[] = [
    {
      name: '',
      type: 'grid',
      schema: [
        { name: 'part_name', selector: selText() },
        { name: 'part_number', selector: selText() },
        {
          name: 'type',
          selector: selSelect([
            { value: 'consumable', label: t('opt.part.consumable') },
            { value: 'wear', label: t('opt.part.wear') },
          ]),
        },
      ],
    },
    {
      name: '',
      type: 'grid',
      schema: [
        { name: 'vendor', selector: selText() },
        { name: 'cost', selector: selNumber(0) },
      ],
    },
    { name: 'part_url', selector: selText() },
    // Free-form notes about this part (rendered as Markdown on the appliance's
    // detail page) — the field has always existed in the stored model but had no
    // editor until now.
    { name: 'notes', selector: selText(true) },
    // Spare quantities are decimal (`'any'`): a part measured in millilitres or
    // topped up a third of a bottle at a time is as valid as one counted in whole
    // filters. `stock_unit` is the label those numbers are shown with.
    {
      name: '',
      type: 'grid',
      schema: [
        { name: 'stock', selector: selNumber(0, 'any') },
        { name: 'reorder_at', selector: selNumber(0, 'any') },
        { name: 'stock_unit', selector: selText() },
      ],
    },
  ];
  // How much one completion draws down. Only meaningful once the part is tracking
  // stock at all — with nothing to draw from, the field would promise nothing.
  if (part.stock != null) {
    base.push({ name: 'consume_quantity', selector: selNumber(MIN_POSITIVE_QUANTITY, 'any') });
  }
  // Auto-buy: only meaningful once a reorder threshold is set (that's what defines
  // "low"). When enabled, offer the restock quantity added on completing the reminder.
  if (part.reorder_at != null) {
    base.push({ name: 'create_buy_task', selector: selBool() });
    if (part.create_buy_task) {
      base.push({
        name: 'restock_quantity',
        selector: selNumber(MIN_POSITIVE_QUANTITY, 'any'),
      });
    }
  }
  if (isWear) {
    base.push({
      name: '',
      type: 'grid',
      schema: [
        { name: 'replace_interval', selector: selNumber(1) },
        { name: 'replace_unit', selector: selUnit() },
      ],
    });
    // Let the user record when the part was last replaced so the derived
    // maintenance task's clock starts from the real date instead of "now".
    base.push({ name: 'last_replaced', selector: selDate() });
  }
  return base;
}

export function renderPartsEditor(p: PanelHost, inner: HTMLElement): void {
  const parts = p._assetEdit.asset?.parts || [];
  const { details, body } = collapsibleSection(p, t('section.parts'), 'parts', parts.length);
  inner.appendChild(details);
  parts.forEach((part, i) => {
    const box = entryBox(p, i, {
      title: t('section.part_n', { n: i + 1 }),
      removeLabel: t('btn.removePart'),
      confirmLabel: () =>
        part.name
          ? t('confirm.removeNamed', { name: part.name })
          : t('confirm.removePart', { n: i + 1 }),
      onRemove: () => {
        const list = p._assetEdit.asset?.parts || [];
        p._assetEdit.asset!.parts = list.filter((_, j) => j !== i);
      },
    });

    // Declared before the form so its value-changed handler can feed it; attached
    // below, after the form, so it renders directly under the part's fields.
    let partNotePreview: MarkdownPreview | null = null;
    const form = p._makeForm(
      partSchema(part),
      {
        part_name: part.name ?? '',
        part_number: part.part_number ?? '',
        type: part.type ?? 'consumable',
        vendor: part.vendor ?? '',
        cost: part.cost ?? undefined,
        part_url: part.url ?? '',
        notes: part.notes ?? '',
        stock: part.stock ?? undefined,
        reorder_at: part.reorder_at ?? undefined,
        stock_unit: part.stock_unit ?? '',
        consume_quantity: part.consume_quantity ?? undefined,
        create_buy_task: part.create_buy_task ?? false,
        restock_quantity: part.restock_quantity ?? undefined,
        replace_interval: part.replace_interval ?? undefined,
        replace_unit: part.replace_unit ?? 'months',
        last_replaced: part.last_replaced ?? undefined,
      },
      (value) => {
        const prevPart = p._assetEdit.asset?.parts?.[i];
        const prevType = prevPart?.type;
        // These fields gate which others render (see partSchema): the reorder
        // threshold reveals the auto-buy toggle, and the toggle reveals the restock
        // quantity. Re-render when one of them flips so the dependent field appears.
        const prevHasReorder = prevPart?.reorder_at != null;
        const prevBuy = Boolean(prevPart?.create_buy_task);
        // Tracking stock at all is what reveals the per-completion amount.
        const prevTracksStock = prevPart?.stock != null;
        partNotePreview?.update(String(value.notes ?? ''));
        const updated: Part = {
          id: part.id,
          // The last-replaced date is only editable for wear items; preserve any
          // existing value when the part is a consumable (no field shown).
          last_replaced:
            value.type === 'wear'
              ? value.last_replaced
                ? String(value.last_replaced)
                : null
              : (part.last_replaced ?? null),
          name: String(value.part_name ?? ''),
          part_number: String(value.part_number ?? ''),
          type: (value.type as Part['type']) ?? 'consumable',
          vendor: String(value.vendor ?? ''),
          cost: value.cost != null && value.cost !== '' ? Number(value.cost) : null,
          url: String(value.part_url ?? '').trim(),
          notes: String(value.notes ?? ''),
          stock: value.stock != null && value.stock !== '' ? Number(value.stock) : null,
          reorder_at:
            value.reorder_at != null && value.reorder_at !== ''
              ? Number(value.reorder_at)
              : null,
          // What the numbers above are counted in ("ml", "bottles"), and how much
          // one completion takes off. Both free of a value means the part behaves
          // exactly as parts did before units existed: whole spares, one per use.
          stock_unit: String(value.stock_unit ?? '').trim(),
          consume_quantity:
            value.consume_quantity != null && value.consume_quantity !== ''
              ? Number(value.consume_quantity)
              : null,
          // Auto-buy a low spare. Only exposed once a reorder threshold is set (the
          // field is hidden otherwise, so value.create_buy_task is then undefined →
          // off, which is correct — no threshold means no "low" to act on).
          create_buy_task: Boolean(value.create_buy_task),
          restock_quantity:
            value.restock_quantity != null && value.restock_quantity !== ''
              ? Number(value.restock_quantity)
              : null,
          replace_interval:
            value.type === 'wear' && value.replace_interval
              ? Number(value.replace_interval)
              : null,
          replace_unit:
            value.type === 'wear' && value.replace_interval
              ? (value.replace_unit as Part['replace_unit'])
              : null,
          // Not editable in this form (upload-only — see renderPartFile); carry
          // the current known values forward so the in-progress client copy stays
          // accurate between saves. The server ignores whatever this sends anyway
          // and always restores the stored values (see assets._merge_parts), but
          // without this the local UI would show "no file" the moment any other
          // field on this part changes, even though nothing was actually lost.
          file_name: part.file_name ?? null,
          file_content_type: part.file_content_type ?? null,
          file_size: part.file_size ?? null,
        };
        const list = [...(p._assetEdit.asset?.parts || [])];
        list[i] = updated;
        p._assetEdit.asset!.parts = list;
        const nowHasReorder = updated.reorder_at != null;
        if (
          value.type !== prevType ||
          nowHasReorder !== prevHasReorder ||
          (updated.stock != null) !== prevTracksStock ||
          Boolean(updated.create_buy_task) !== prevBuy
        )
          p._render();
      },
    );
    box.appendChild(form);
    partNotePreview = p._attachNotePreview(box, String(part.notes ?? ''));
    renderPartFile(p, box, part, i);

    if (part.type === 'wear') {
      const note = document.createElement('div');
      note.className = 'hk-meta';
      note.textContent = t('part.wearHint');
      box.appendChild(note);
    }
    body.appendChild(box);
  });

  const add = document.createElement('ha-button');
  setBtnWeight(add, 'secondary');
  add.id = 'a-add-part';
  add.textContent = t('btn.addPart');
  add.addEventListener('click', () => {
    const list = [...(p._assetEdit.asset?.parts || [])];
    list.push({ name: '', type: 'consumable' });
    p._assetEdit.asset!.parts = list;
    p._render();
  });
  body.appendChild(add);
}

/** A part's single attached file: a card (icon, filename · size · type, Open /
 *  Remove) when one is attached; otherwise an "Attach file" upload button — only
 *  once both the appliance and this part row are saved (a part gets its id from
 *  the backend, so a brand-new unsaved part has none yet to upload against). */
function renderPartFile(p: PanelHost, box: HTMLElement, part: Part, i: number): void {
  const assetId = p._assetEdit.asset?.id;
  if (part.file_name) {
    box.appendChild(
      fileCard(p, {
        icon: 'mdi:paperclip',
        name: part.file_name,
        subtitle: partFileSubtitle(part),
        // Same native-anchor treatment as an uploaded document (see `openFileAnchor`).
        open: {
          target: assetId && part.id ? { kind: 'part', assetId, id: part.id } : undefined,
          fallback: () => openPartFileFallback(p, part),
        },
        remove: {
          label: t('btn.removePartFile'),
          onClick: () => void removePartFile(p, part, i),
        },
      }),
    );
    return;
  }
  if (!assetId || !part.id) return;
  const key = uploadKeyPart(part.id);
  const upload = document.createElement('ha-button');
  setBtnWeight(upload, 'secondary');
  upload.textContent = uploadButtonLabel(p, key, t('btn.attachFile'));
  const picker = filePicker(p, upload, (file) => void uploadPartFile(p, part, i, file));
  const row = document.createElement('div');
  row.className = 'hk-meta-seeds';
  row.append(upload, picker);
  box.appendChild(row);
  renderUploadStatus(p, box, key);
}

/** Details line for a part's attached file: filename · size · type. */
function partFileSubtitle(part: Part): string {
  const parts: string[] = [];
  const size = formatBytes(part.file_size ?? undefined);
  if (size) parts.push(size);
  const type = documentTypeLabel(part.file_content_type ?? undefined);
  if (type) parts.push(type);
  return parts.join(' · ');
}

function openPartFileFallback(p: PanelHost, part: Part): void {
  const assetId = p._assetEdit.asset?.id;
  if (p._hass && assetId) void openPartFile(p._hass, assetId, part);
}

async function uploadPartFile(p: PanelHost, part: Part, i: number, file: File): Promise<void> {
  const assetId = p._assetEdit.asset?.id;
  if (!p._hass || !assetId || !part.id) return;
  const hass = p._hass;
  const partId = part.id;
  const updated = await runUpload(p, uploadKeyPart(partId), file, (opts) =>
    api.uploadPartFile(hass, assetId, partId, file, undefined, opts),
  );
  if (!updated) return;
  const list = [...(p._assetEdit.asset?.parts || [])];
  list[i] = {
    ...list[i],
    file_name: updated.file_name,
    file_content_type: updated.file_content_type,
    file_size: updated.file_size,
  };
  p._assetEdit.asset!.parts = list;
  p._render();
}

async function removePartFile(p: PanelHost, part: Part, i: number): Promise<void> {
  const assetId = p._assetEdit.asset?.id;
  if (!p._hass || !assetId || !part.id) return;
  try {
    await api.removePartFile(p._hass, assetId, part.id);
    const list = [...(p._assetEdit.asset?.parts || [])];
    list[i] = { ...list[i], file_name: null, file_content_type: null, file_size: null };
    p._assetEdit.asset!.parts = list;
    p._render();
  } catch (err) {
    setAssetError(p, String((err as { message?: string })?.message || err));
    p._render();
  }
}
