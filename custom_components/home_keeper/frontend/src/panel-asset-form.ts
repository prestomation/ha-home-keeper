/**
 * The appliance edit drawer: the identity/reference/notes/related fields, and the
 * three editors (`panel-asset-editors.ts`) it hosts between them.
 *
 * Only the two pure-ish helpers the form needs live here — the parents an appliance
 * may be nested under, and the make/model/serial a linked Home Assistant device can
 * fill in. The form's *lifecycle* (open, close, submit) stays on the panel, for the
 * same reason the task form's does; note that everything below writes into
 * `_assetEdit.asset` **in place**, which is what `p._submitAssetForm` later reads.
 *
 * Free functions over a `PanelHost` (see `panel-host.ts`); the drawer's top bar comes
 * from `panel-task-form.ts`, since both drawers wear the same one.
 */

import {
  assetIdentitySchema,
  selDevice,
  selText,
  structuredDetailsSchema,
} from './forms';
import { t } from './i18n';
import type { MarkdownPreview } from './markdown';
import {
  renderDocumentsEditor,
  renderMetadataEditor,
  renderPartsEditor,
} from './panel-asset-editors';
import { section } from './panel-history';
import type { PanelHost } from './panel-host';
import { drawerHead } from './panel-task-form';
import { errorAlert, setAssetError } from './panel-upload';
import type { Asset } from './types';

/**
 * The appliances this one may be nested under: every virtual appliance except itself
 * and its own descendants (which would make a cycle). An existing-device appliance is
 * never offered — it nests natively through the device registry instead.
 */
function eligibleParents(p: PanelHost, x: Partial<Asset>): { value: string; label: string }[] {
  const banned = new Set<string>();
  if (x.id) {
    banned.add(x.id);
    const childrenOf = (pid: string): void => {
      for (const a of p._assets) {
        if (a.parent_asset_id === pid && !banned.has(a.id)) {
          banned.add(a.id);
          childrenOf(a.id);
        }
      }
    };
    childrenOf(x.id);
  }
  return p._assets
    .filter((a) => a.kind === 'virtual' && !banned.has(a.id))
    .map((a) => ({ value: a.id, label: a.name }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** Manufacturer/model/serial_number to prefill from a linked HA device, skipping
 *  any field already set on the asset — this only fills gaps, never overwrites a
 *  value the user typed (or one already saved from a previous edit). */
function deviceDefaults(
  p: PanelHost,
  deviceId: string,
  prev: Partial<Asset> | null,
): Record<string, string> | undefined {
  const dev = p._hass?.devices?.[deviceId];
  if (!dev) return undefined;
  const fill: Record<string, string> = {};
  if (!String(prev?.manufacturer || '').trim() && dev.manufacturer) {
    fill.manufacturer = dev.manufacturer;
  }
  if (!String(prev?.model || '').trim() && dev.model) {
    fill.model = dev.model;
  }
  if (!String(prev?.serial_number || '').trim() && dev.serial_number) {
    fill.serial_number = dev.serial_number;
  }
  return Object.keys(fill).length ? fill : undefined;
}

export function renderAssetForm(p: PanelHost, host: HTMLElement): void {
  const x = p._assetEdit.asset || {};
  const editing = Boolean(x.id);
  const card = document.createElement('ha-card');
  card.className = 'hk-form-card';
  card.id = 'hk-asset-form';
  const head = drawerHead(
    editing ? t('form.appliance.edit') : t('form.appliance.new'),
    String(x.name ?? ''),
    editing ? t('btn.save') : t('btn.create'),
    () => void p._submitAssetForm(),
    () => p._closeAssetForm(),
    { save: 'a-save', cancel: 'a-cancel' },
  );
  // Saving mid-upload would PUT the client draft over the asset the upload response
  // is about to rewrite, losing the new document.
  if (p._assetEdit.upload) head.querySelector('#a-save')?.setAttribute('disabled', '');
  card.appendChild(head);
  const inner = document.createElement('div');
  inner.className = 'hk-form-inner';

  const mergeAsset = (value: Record<string, unknown>): void => {
    p._assetEdit.asset = { ...p._assetEdit.asset, ...value } as Partial<Asset>;
    setAssetError(p, undefined);
  };

  // Identity (kind toggle re-renders since the schema changes).
  const identity = p._makeForm(
    assetIdentitySchema(x, editing, eligibleParents(p, x)),
    {
      kind: x.kind ?? 'virtual',
      device_id: x.device_id ?? undefined,
      name: x.name ?? '',
      manufacturer: x.manufacturer ?? '',
      model: x.model ?? '',
      serial_number: x.serial_number ?? '',
      icon: x.icon ?? '',
      parent_asset_id: x.parent_asset_id ?? undefined,
      area_id: x.area_id ?? undefined,
    },
    (value) => {
      const prevAsset = p._assetEdit.asset;
      // Defaulted exactly as the form data above seeds it, so an appliance that
      // doesn't carry a kind can't make the form's 'virtual' read as a change — that
      // would re-render on the first character typed into the name, dropping focus
      // (and handing the keystrokes to HA's global shortcuts; see the task form).
      const prevKind = prevAsset?.kind ?? 'virtual';
      const prevDeviceId = prevAsset?.device_id;
      mergeAsset(value);
      if (value.kind === 'existing' && value.device_id && value.device_id !== prevDeviceId) {
        const fill = deviceDefaults(p, String(value.device_id), prevAsset);
        if (fill) {
          mergeAsset(fill);
          identity.data = { ...identity.data, ...fill };
        }
      }
      if (!editing && value.kind !== prevKind) p._render();
    },
  );
  inner.appendChild(identity);

  inner.appendChild(section(t('section.reference')));
  inner.appendChild(
    p._makeForm(
      structuredDetailsSchema(),
      { cost: x.cost ?? undefined },
      mergeAsset,
    ),
  );

  // Notes get their own section so the live Markdown preview can sit directly under
  // the field it previews (the appliance form is already section-split, unlike the
  // task form's single `ha-form`).
  inner.appendChild(section(t('section.notes')));
  let assetNotePreview: MarkdownPreview | null = null;
  inner.appendChild(
    p._makeForm([{ name: 'notes', selector: selText(true) }], { notes: x.notes ?? '' }, (value) => {
      mergeAsset(value);
      assetNotePreview?.update(String(value.notes ?? ''));
    }),
  );
  assetNotePreview = p._attachNotePreview(inner, String(x.notes ?? ''));

  renderDocumentsEditor(p, inner);

  renderMetadataEditor(p, inner);

  renderPartsEditor(p, inner);

  inner.appendChild(section(t('section.related')));
  inner.appendChild(
    p._makeForm(
      [{ name: 'related_device_ids', selector: selDevice(true) }],
      { related_device_ids: x.related_device_ids ?? [] },
      mergeAsset,
    ),
  );

  if (p._assetEdit.error) {
    inner.appendChild(errorAlert(p._assetEdit.error, p._assetEdit.errorLink));
  }

  card.appendChild(inner);
  host.appendChild(card);

  // An upload failure is reported inline, but the control that failed can be well
  // below the fold in a long form — bring it into view. Driven by a one-shot flag
  // set in `failUpload`, never by "an error exists": `mergeAsset` clears the error
  // on every keystroke, so a state check here would re-scroll on unrelated renders.
  if (p._scrollToError) {
    const key = p._scrollToError;
    p._scrollToError = undefined;
    requestAnimationFrame(() => {
      const el = p.shadowRoot?.getElementById(`hk-upload-err-${key}`);
      // Guarded: scrollIntoView is missing in jsdom, and the node is gone if a
      // later render dropped the alert before the frame ran.
      if (typeof el?.scrollIntoView === 'function') {
        el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
    });
  }
}
