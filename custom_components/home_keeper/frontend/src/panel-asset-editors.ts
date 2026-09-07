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
  type FormField,
  type HaFormElement,
  mergePartForm,
  metadataBaseSchema,
  metadataDependentSchema,
  partBaseSchema,
  partDependentKey,
  partDependentSchema,
  partFormData,
  partSummaryLine,
  pickFormData,
  selText,
} from './forms';
import { t } from './i18n';
import type { MarkdownPreview } from './markdown';
import { openConfirmDialog } from './panel-dialogs';
import { collapsibleSection, section, setIcon } from './panel-history';
import type { PanelHost } from './panel-host';
import { MDI_CONSUMABLE, MDI_DELETE, MDI_EDIT, MDI_OPEN_IN_NEW, MDI_WEAR } from './panel-icons';
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
  // `hk-entry`, not `hk-part`: a part row is a `details.hk-part` now, and the suite
  // finds parts by that class — a custom field wearing it would be counted as one.
  const box = document.createElement('div');
  box.className = 'hk-entry';
  box.dataset.idx = String(i);
  const head = document.createElement('div');
  head.className = 'hk-entry-head';
  head.innerHTML = `<span class="label">${escapeHTML(spec.title)}</span>`;
  const del = document.createElement('ha-icon-button');
  del.className = 'part-del';
  del.setAttribute('label', spec.removeLabel);
  setIcon(del, MDI_DELETE);
  del.addEventListener('click', () => {
    openConfirmDialog(p, spec.confirmLabel(), spec.onRemove);
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
  box.className = 'hk-entry hk-doc-edit';
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

    // Two forms, so choosing a type never rebuilds the label being typed into: the
    // base form (type + label) keeps its shape, and only the dependent form (the value
    // control, and a date's "track" toggle) has its schema swapped in place.
    const current = (): MetadataEntry => p._assetEdit.asset?.metadata?.[i] ?? m;
    const data = (entry: MetadataEntry): Record<string, unknown> => ({
      type: entry.type ?? 'text',
      label: entry.label ?? '',
      value: entry.value ?? '',
      track: Boolean(entry.track),
    });
    const note = document.createElement('div');
    note.className = 'hk-meta';
    note.textContent = t('meta.trackHint');
    let dep: HaFormElement;
    const merge = (value: Record<string, unknown>): void => {
      const prev = current();
      const newType = 'type' in value ? ((value.type as MetadataType) ?? 'text') : (prev.type ?? 'text');
      const updated: MetadataEntry = {
        id: m.id,
        type: newType,
        label: 'label' in value ? String(value.label ?? '') : (prev.label ?? ''),
        // A date control emits selector-shaped strings; text/link emit text.
        value: 'value' in value ? (value.value != null ? String(value.value) : '') : (prev.value ?? ''),
        // `track` only applies to dates — drop it otherwise so it can't strand.
        track:
          newType === 'date'
            ? Boolean('track' in value ? value.track : prev.track)
            : undefined,
      };
      const list = [...(p._assetEdit.asset?.metadata || [])];
      list[i] = updated;
      p._assetEdit.asset!.metadata = list;
      // The value control (and the date "track" toggle) swap to match the type — on
      // the dependent form only, in place, never through a render.
      if (newType !== prev.type) {
        const schema = metadataDependentSchema(updated);
        dep.schema = schema;
        dep.data = pickFormData(data(updated), schema);
        note.hidden = newType !== 'date';
      }
    };
    const base = p._makeForm(metadataBaseSchema(), pickFormData(data(m), metadataBaseSchema()), merge);
    dep = p._makeForm(metadataDependentSchema(m), pickFormData(data(m), metadataDependentSchema(m)), merge);
    box.append(base, dep);
    note.hidden = m.type !== 'date';
    box.appendChild(note);
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

/**
 * Which part row is expanded. `undefined` (nothing chosen yet) opens a lone part —
 * a new appliance's first part, say — and leaves a longer list folded so the drawer
 * fits on a phone; `null` is a deliberate "all closed". Never past the end: a part
 * removed from under the index closes the list rather than opening a stranger.
 */
function openPartIndex(p: PanelHost, count: number): number {
  const chosen = p._assetEdit.openPart;
  if (chosen === null) return -1;
  if (chosen !== undefined) return chosen < count ? chosen : -1;
  return count === 1 ? 0 : -1;
}

/**
 * Bring *el* into view inside the drawer's own scroller, under its sticky head.
 * `scrollIntoView` on its own would park the row behind the head; the sheet on a
 * phone has the same head. Falls back to a plain `scrollIntoView` (or nothing, in
 * jsdom) when the row is not inside a drawer.
 */
function revealInDrawer(p: PanelHost, el: HTMLElement): void {
  const scroller = el.closest<HTMLElement>('.hk-drawer-sticky');
  if (!scroller || typeof scroller.scrollBy !== 'function') {
    if (typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'start' });
    return;
  }
  const head = scroller.querySelector<HTMLElement>('.hk-drawer-head');
  const top =
    el.getBoundingClientRect().top -
    scroller.getBoundingClientRect().top -
    (head?.offsetHeight ?? 0) -
    8;
  if (Math.abs(top) < 2) return;
  // A drawer that has just opened sits at its top: land on the row rather than
  // animate the whole form past the reader. From anywhere else — Add part appending
  // a row below the one being read — a smooth move says where the row went.
  scroller.scrollBy({ top, behavior: scroller.scrollTop === 0 ? 'auto' : p._scrollBehavior() });
}

export function renderPartsEditor(p: PanelHost, inner: HTMLElement): void {
  const parts = p._assetEdit.asset?.parts || [];
  const { details, body } = collapsibleSection(p, t('section.parts'), 'parts', parts.length);
  inner.appendChild(details);
  const openIdx = openPartIndex(p, parts.length);
  parts.forEach((part, i) => body.appendChild(partBox(p, body, part, i, i === openIdx)));

  const add = document.createElement('ha-button');
  setBtnWeight(add, 'secondary');
  add.id = 'a-add-part';
  add.textContent = t('btn.addPart');
  add.addEventListener('click', () => {
    const list = [...(p._assetEdit.asset?.parts || [])];
    list.push({ name: '', type: 'consumable' });
    p._assetEdit.asset!.parts = list;
    // The new row opens on its own and takes the keyboard: it is the one thing the
    // click asked for, and a folded blank row would have to be found and opened.
    p._assetEdit.openPart = list.length - 1;
    p._assetEdit.revealPart = 'focus';
    p._render();
  });
  body.appendChild(add);

  // One-shot: the Parts tab's Edit / Add part, and the button above, ask for the
  // opened row to be on screen (and, for a new part, under the cursor). Consumed
  // here so an unrelated render later never scrolls the drawer again.
  const reveal = p._assetEdit.revealPart;
  if (reveal && openIdx >= 0) {
    p._assetEdit.revealPart = undefined;
    const target = body.querySelector<HTMLElement>(`details.hk-part[data-idx="${openIdx}"]`);
    const form = target?.querySelector<HTMLElement>('ha-form');
    const later =
      typeof requestAnimationFrame === 'function'
        ? requestAnimationFrame
        : (fn: () => void): void => void setTimeout(fn, 0);
    later(() => {
      if (!target?.isConnected) return;
      revealInDrawer(p, target);
      if (reveal === 'focus' && form) p._focus(form);
      // The selectors inside an ha-form load lazily and grow the rows above the
      // target after the first frame; one late correction puts the row back where
      // the first pass aimed.
      setTimeout(() => {
        if (target.isConnected) revealInDrawer(p, target);
      }, 300);
    });
  }
}

/**
 * One part in the editor: a `details` whose summary names the part and says what a
 * reader most often comes back for (stock, reorder point, interval), and whose body
 * is the part's two forms, its note preview, its attached file and its Remove. Only
 * one part is open at a time, so the drawer never grows past one form (issue #296).
 *
 * Keeps `.hk-part` and `data-idx`: the e2e suite and the capture harnesses find
 * parts by them.
 */
function partBox(
  p: PanelHost,
  list: HTMLElement,
  part: Part,
  i: number,
  open: boolean,
): HTMLDetailsElement {
  const box = document.createElement('details');
  box.className = 'hk-part hk-part-acc';
  box.dataset.idx = String(i);
  if (part.id) box.dataset.partId = part.id;

  const summary = document.createElement('summary');
  summary.className = 'hk-part-head';
  summary.innerHTML =
    '<ha-svg-icon class="hk-part-acc-ic"></ha-svg-icon>' +
    '<span class="hk-part-acc-text"><span class="hk-part-acc-name"></span>' +
    '<span class="hk-part-badge"></span><span class="hk-part-acc-sum"></span></span>' +
    '<ha-icon icon="mdi:chevron-down" class="hk-section-chevron"></ha-icon>';
  box.appendChild(summary);
  const icon = summary.querySelector<HTMLElement>('.hk-part-acc-ic')!;
  const nameEl = summary.querySelector<HTMLElement>('.hk-part-acc-name')!;
  const badge = summary.querySelector<HTMLElement>('.hk-part-badge')!;
  const sum = summary.querySelector<HTMLElement>('.hk-part-acc-sum')!;
  const updateSummary = (x: Part): void => {
    const wear = x.type === 'wear';
    box.classList.toggle('wear', wear);
    setIcon(icon, wear ? MDI_WEAR : MDI_CONSUMABLE);
    nameEl.textContent = x.name || t('section.part_n', { n: i + 1 });
    badge.textContent = t(`opt.part.${x.type ?? 'consumable'}`);
    sum.textContent = partSummaryLine(x);
    sum.hidden = !sum.textContent;
  };
  updateSummary(part);

  const bodyEl = document.createElement('div');
  bodyEl.className = 'hk-part-body';
  box.appendChild(bodyEl);

  // Two forms per part (see `partBaseSchema`): the base one is built once and never
  // has its schema touched, so the box being typed in survives; the dependent one
  // has its schema reassigned in place when a gate flips. Nothing here calls
  // `_render()` from a keystroke — that was the iOS jump.
  let notePreview: MarkdownPreview | null = null;
  let depKey = partDependentKey(part);
  let dep: HaFormElement;
  const wearHint = document.createElement('div');
  wearHint.className = 'hk-meta';
  wearHint.textContent = t('part.wearHint');
  const merge = (value: Record<string, unknown>): void => {
    const all = [...(p._assetEdit.asset?.parts || [])];
    const next = mergePartForm(all[i] ?? part, value);
    all[i] = next;
    p._assetEdit.asset!.parts = all;
    if ('notes' in value) notePreview?.update(next.notes ?? '');
    updateSummary(next);
    wearHint.hidden = next.type !== 'wear';
    const key = partDependentKey(next);
    if (key !== depKey) {
      depKey = key;
      const schema = partDependentSchema(next);
      dep.schema = schema;
      dep.data = pickFormData(partFormData(next), schema);
      dep.style.display = schema.length ? '' : 'none';
    }
  };
  const baseSchema = partBaseSchema();
  const base = p._makeForm(baseSchema, pickFormData(partFormData(part), baseSchema), merge);
  // An id, so the panel's focus restore can find this form again after a render
  // that had to happen (a file upload, a removed part) — see `_focusKey`.
  base.id = `hk-part-form-${i}`;
  bodyEl.appendChild(base);
  notePreview = p._attachNotePreview(bodyEl, String(part.notes ?? ''));
  const depSchema = partDependentSchema(part);
  dep = p._makeForm(depSchema, pickFormData(partFormData(part), depSchema), merge);
  dep.className = 'hk-part-dep';
  if (!depSchema.length) dep.style.display = 'none';
  bodyEl.appendChild(dep);
  wearHint.hidden = part.type !== 'wear';
  bodyEl.appendChild(wearHint);
  renderPartFile(p, bodyEl, part, i);

  // Remove sits at the foot of the open row, not in its summary: a button inside a
  // `summary` toggles the row as well as firing, and the browsers disagree on which
  // happens first.
  const foot = document.createElement('div');
  foot.className = 'hk-part-foot';
  const del = document.createElement('ha-button');
  setBtnWeight(del, 'danger');
  del.className = 'part-del';
  del.textContent = t('btn.removePart');
  del.addEventListener('click', () => {
    const name = p._assetEdit.asset?.parts?.[i]?.name;
    openConfirmDialog(
      p,
      name ? t('confirm.removeNamed', { name }) : t('confirm.removePart', { n: i + 1 }),
      () => {
        const all = p._assetEdit.asset?.parts || [];
        p._assetEdit.asset!.parts = all.filter((_, j) => j !== i);
        const chosen = p._assetEdit.openPart;
        if (chosen != null) {
          if (chosen === i) p._assetEdit.openPart = null;
          else if (chosen > i) p._assetEdit.openPart = chosen - 1;
        }
      },
    );
  });
  foot.appendChild(del);
  bodyEl.appendChild(foot);

  box.open = open;
  box.addEventListener('toggle', () => {
    if (box.open) {
      p._assetEdit.openPart = i;
      // One at a time. Closing a sibling fires its own toggle, which lands in the
      // branch below with a different index and changes nothing.
      list.querySelectorAll<HTMLDetailsElement>('details.hk-part[open]').forEach((other) => {
        if (other !== box) other.open = false;
      });
    } else if (p._assetEdit.openPart === i) {
      p._assetEdit.openPart = null;
    }
  });
  return box;
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
