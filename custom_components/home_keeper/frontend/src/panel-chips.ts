/**
 * The chip vocabulary of a task/appliance row: area, tag, managing integration, and
 * the device chip that links out to a device page — plus the integration-supplied
 * `task_chips` a task carries, and the one wiring pass that makes every device chip
 * clickable and falls its brand logo back to a glyph.
 *
 * `taskChipsList` takes no `PanelHost`: it is a pure function of the task, which is
 * why the dashboard card can render the same chips from the same code rather than
 * from a second copy of the template. The rest read the panel's live registries
 * (areas, devices, tags, loaded config entries) through `PanelHost`.
 */

import { taskAreaId } from './card-filter';
import { t, tn } from './i18n';
import type { PanelHost } from './panel-host';
import { MDI_DEVICES } from './panel-icons';
import type { Asset, ManagedByBase, Part, Task } from './types';
import {
  HK_DOMAIN,
  areaName,
  brandLogoUrl,
  deviceDomain,
  deviceName,
  escapeHTML,
  formatQuantity,
  isHttpUrl,
  isUseTask,
  navigateTo,
  safeHref,
  scanRequired,
  stockLinks,
  tagName,
} from './utils';

/**
 * Run *fn* on a click, and on Enter or Space. A `role="button"` span gets no click
 * from the keyboard, so a greyed button wired by click only does nothing for a
 * keyboard user (F07-7).
 */
export function onActivate(el: HTMLElement, fn: () => void): void {
  el.addEventListener('click', fn);
  el.addEventListener('keydown', (e) => {
    const key = (e as KeyboardEvent).key;
    if (key === 'Enter' || key === ' ') {
      e.preventDefault();
      fn();
    }
  });
}

/**
 * Whether a managed task's owning integration is no longer loaded. A task is
 * orphaned when its `config_entry_id` is set but absent from the loaded-entry
 * set (uninstalled, disabled, or failing to set up). Without a recorded
 * `config_entry_id` we can't prove the owner is gone, so it isn't treated as
 * orphaned (the `force` service is the escape hatch for that edge case).
 */
export function isManagedOrphan(p: PanelHost, task: Task): boolean {
  return ownerIsGone(p, task.managed_by);
}

/** The same question about an appliance's owner. An appliance carries the same
 *  ownership block a task does, so it can be orphaned the same way. */
export function isManagedAssetOrphan(p: PanelHost, asset: Asset): boolean {
  return ownerIsGone(p, asset.managed_by);
}

/** The one reading of "the owner is no longer here", shared by both surfaces. */
function ownerIsGone(p: PanelHost, mb?: ManagedByBase | null): boolean {
  const id = mb?.config_entry_id;
  // Unknown owners are not gone: a failed lookup must not offer to delete them.
  const loaded = p._loadedEntryIds;
  return Boolean(id) && loaded !== null && !loaded.has(id as string);
}

/**
 * A task owned by its *source* rather than by the user: a reconciler-derived wear
 * part, or a synced problem sensor. The panel offers it no edit, no delete and no
 * duplicate — its source keeps it in step, and an unowned lookalike would drift.
 *
 * A *manual* consumable link (`part.manual`) is user-owned, so it is not source-owned:
 * the user made that link by hand and may edit, delete and copy the task freely.
 *
 * Lives here, beside `isManagedOrphan`, because the render and the guards that decide
 * which actions exist must read one predicate — two copies are free to disagree.
 */
export function sourceOwnedTask(task: Task): boolean {
  return (
    (Boolean(task.source?.part) && !task.source?.part?.manual) ||
    // A declarative-companion task is not on this list. Its reconciler owns the
    // fields in `managed_by.locked_fields`, and the task form already leaves those
    // out, so Edit offers only what a person may change on one task: labels, the
    // tag, the completion detail, and the notes when no notes template writes them
    // (#378). Delete and Duplicate stay withheld through the managed path, because
    // the task is `deletion_protected` and has a `managed_by` block.
    Boolean(task.source?.problem_sensor)
  );
}

/** Renders integration-provided metadata chips (task_chips). Chips with a URL
 *  become native links; icon slot is populated when present. */
export function taskChipsHtml(task: Task): string {
  return taskChipsList(task).join('');
}

/** The integration-provided chips as individual elements. The list card counts them
 *  to decide how many fit inline, which a pre-joined string can't answer. */
export function taskChipsList(task: Task): string[] {
  return (task.task_chips ?? [])
    .map(({ label, icon, url }) => {
      const iconSlot = icon
        ? `<ha-icon slot="icon" icon="${escapeHTML(icon)}" class="hk-chip-ic"></ha-icon>`
        : '';
      const chip = `<ha-assist-chip label="${escapeHTML(label)}">${iconSlot}</ha-assist-chip>`;
      return isHttpUrl(url)
        ? `<a class="hk-task-chip-link" href="${safeHref(url)}" target="_blank" rel="noopener noreferrer">${chip}</a>`
        : chip;
    });
}

/**
 * A chip naming the task's effective area (its own, else its attached device's).
 * Empty when neither resolves to a real area — an unplaced task shows no chip
 * rather than an "Unassigned" one, matching how the device chip stays absent.
 */
export function areaChip(p: PanelHost, task: Task): string {
  const name = areaName(p._hass?.areas, taskAreaId(task, p._hass?.devices));
  if (!name) return '';
  const icon = `<ha-icon slot="icon" icon="mdi:texture-box" class="hk-chip-ic"></ha-icon>`;
  return `<ha-assist-chip label="${escapeHTML(name)}">${icon}</ha-assist-chip>`;
}

/**
 * A chip for the task's bound NFC/RFID tag, naming it where the tag registry
 * knows it and falling back to the raw id. A scan-locked task swaps the glyph for
 * a padlock, so the row shows at a glance why its Done button is greyed out.
 * Empty when no tag is bound.
 */
export function tagChip(p: PanelHost, task: Task): string {
  if (!task.tag_id) return '';
  const locked = scanRequired(task);
  const iconName = locked ? 'mdi:lock' : 'mdi:nfc-variant';
  const tip = locked ? t('chip.scanLock.tip') : t('chip.nfc.tip');
  const label = tagName(p._tags, task.tag_id) || t('chip.nfc');
  const icon = `<ha-icon slot="icon" icon="${iconName}" class="hk-chip-ic"></ha-icon>`;
  return `<ha-assist-chip class="hk-tag" label="${escapeHTML(label)}" title="${escapeHTML(tip)}">${icon}</ha-assist-chip>`;
}

/** Renders a "Managed by X" chip (or "Integration offline" if orphaned). */
export function managedChip(p: PanelHost, task: Task): string {
  return ownerChip(p, task.managed_by);
}

/**
 * The same chip for an appliance an integration owns. One renderer, because the
 * chip says the same thing on both surfaces and two copies would be free to
 * disagree about what "offline" looks like.
 */
export function assetManagedChip(p: PanelHost, asset: Asset): string {
  return ownerChip(p, asset.managed_by);
}

function ownerChip(p: PanelHost, mb?: ManagedByBase | null): string {
  if (!mb) return '';
  if (ownerIsGone(p, mb)) {
    return `<ha-assist-chip class="hk-orphaned" label="${escapeHTML(t('chip.orphaned'))}"></ha-assist-chip>`;
  }
  // A task Home Keeper synced from a sensor is "owned" by Home Keeper itself, so
  // "Managed by Home Keeper" reads as redundant — call it what it is: auto-synced.
  const selfOwned = mb.integration === HK_DOMAIN;
  const label = selfOwned ? t('chip.autoSynced') : t('chip.managed', { name: mb.display_name });
  const tip = selfOwned ? t('chip.autoSynced.tip') : label;
  // A leading glyph gives the owner chip the same icon grammar as the device chip:
  // the companion's own mdi icon when known, a generic integration glyph otherwise,
  // and an autorenew mark for self-synced tasks.
  const iconName = selfOwned ? 'mdi:autorenew' : mb.icon || 'mdi:puzzle';
  const icon = `<ha-icon slot="icon" icon="${escapeHTML(iconName)}" class="hk-chip-ic"></ha-icon>`;
  return `<ha-assist-chip class="hk-managed" label="${escapeHTML(label)}" title="${escapeHTML(tip)}">${icon}</ha-assist-chip>`;
}

/**
 * What completing this task takes off the shelf, and what is left: "Takes 2 AAA ·
 * 2 left".
 *
 * The count already lives on the appliance page, but the task row is where the work
 * is decided — a replacement the user is about to mark done is exactly when "am I
 * about to run out" matters. The quantity is the link's own when it carries one
 * (a device takes 2 cells, its neighbour takes 4), else the part's per-completion
 * amount, else one whole spare.
 *
 * A part that tracks no stock still gets the chip, without the "left" half: the
 * task still takes that part, and the chip is the way to it. A click opens the part
 * on its appliance page (`wirePartChips`). So an integration that links its task to
 * a part gets this chip for free, and does not have to send a chip of its own.
 *
 * 1 chip for each part the task takes (#493). Empty when each link points at a
 * part that is gone, and on a counted wear item's *use* task, which draws nothing
 * off the shelf.
 */
export function consumableChip(p: PanelHost, task: Task): string {
  return resolvedStockLinks(p, task)
    .map(({ asset, part, takes }) => {
      const bits = [t('chip.takes', { n: formatQuantity(takes, part.stock_unit), part: part.name })];
      if (part.stock != null) {
        bits.push(t('chip.left', { n: formatQuantity(part.stock, part.stock_unit) }));
      }
      return partChip(asset.id, part.id as string, bits.join(' · '), t('chip.part.tip'));
    })
    .join('');
}

/**
 * The 1 stock chip of a task-list row. The row has room for a short chip only, so
 * the full "Takes 2 Sediment filter · 4 left" line goes to the tooltip.
 *
 * - 1 part: the part name and what is left. A long name is cut, so the count stays
 *   in view. A click opens the part, as on the task page.
 * - More parts (#493): "2 parts", plus "Low stock" when 1 of them is at or below
 *   its reorder point. A click opens the task page, which shows 1 chip per part.
 *
 * Empty when the task takes no part that still exists.
 */
export function consumableRowChip(p: PanelHost, task: Task): string {
  const links = resolvedStockLinks(p, task);
  if (!links.length) return '';
  const lines = links.map(({ part, takes }) =>
    t('chip.takes', { n: formatQuantity(takes, part.stock_unit), part: part.name }),
  );
  if (links.length === 1) {
    const [{ asset, part }] = links;
    const left =
      part.stock != null ? t('chip.left', { n: formatQuantity(part.stock, part.stock_unit) }) : '';
    const label = left ? `${rowChipName(part.name)} · ${left}` : rowChipName(part.name);
    return partChip(asset.id, part.id as string, label, left ? `${lines[0]} · ${left}` : lines[0]);
  }
  const low = links.some(
    ({ part }) => part.stock != null && part.reorder_at != null && part.stock <= part.reorder_at,
  );
  const label = [tn('chip.parts', links.length), ...(low ? [t('chip.lowStock')] : [])].join(' · ');
  const icon = `<ha-icon slot="icon" icon="mdi:package-variant" class="hk-chip-ic"></ha-icon>`;
  return `<ha-assist-chip class="hk-counted hk-part-chip" role="link" tabindex="0" data-open-task="${escapeHTML(
    task.id,
  )}" label="${escapeHTML(label)}" title="${escapeHTML(lines.join('\n'))}">${icon}</ha-assist-chip>`;
}

/** The longest part name a row chip shows whole. */
const ROW_CHIP_NAME_MAX = 18;

/**
 * A part name cut to fit a row chip, with an ellipsis. The chip label has no style
 * hook, so CSS cannot cut the name and keep the count after it.
 */
function rowChipName(name: string): string {
  const chars = [...name];
  if (chars.length <= ROW_CHIP_NAME_MAX) return name;
  return `${chars.slice(0, ROW_CHIP_NAME_MAX - 1).join('').trimEnd()}…`;
}

/** Each part a completion of *task* draws, with what it takes, that still exists. */
function resolvedStockLinks(
  p: PanelHost,
  task: Task,
): { asset: Asset; part: Part; takes: number }[] {
  // A counted wear item's use task draws nothing off the shelf.
  if (isUseTask(task)) return [];
  const out: { asset: Asset; part: Part; takes: number }[] = [];
  for (const link of stockLinks(task)) {
    const asset = p._assets.find((a) => a.id === link.asset_id);
    const part = asset?.parts?.find((x) => x.id === link.part_id);
    if (!asset || !part?.id) continue;
    out.push({ asset, part, takes: link.quantity ?? part.consume_quantity ?? 1 });
  }
  return out;
}

/** 1 chip that opens a part on its appliance page (`wirePartChips`). */
function partChip(assetId: string, partId: string, label: string, title: string): string {
  const icon = `<ha-icon slot="icon" icon="mdi:package-variant" class="hk-chip-ic"></ha-icon>`;
  return `<ha-assist-chip class="hk-counted hk-part-chip" role="link" tabindex="0" data-asset-id="${escapeHTML(
    assetId,
  )}" data-part-id="${escapeHTML(partId)}" label="${escapeHTML(label)}" title="${escapeHTML(
    title,
  )}">${icon}</ha-assist-chip>`;
}

/**
 * Wire every part chip, and the appliance link on a task's "Linked consumables"
 * row, to open its part. A list-row chip for several parts opens its task. Each carries the destination in the DOM, the same way a
 * device chip does. The click stops here, so a chip on a list row does not also
 * open the row's task.
 */
export function wirePartChips(p: PanelHost, root: ParentNode): void {
  root.querySelectorAll<HTMLElement>('.hk-part-chip, a.hk-part-link').forEach((chip) => {
    const { assetId, partId, openTask } = chip.dataset;
    // A row chip for several parts opens its task, which lists each part.
    if (!openTask && (!assetId || !partId)) return;
    const go = (e: Event): void => {
      // A modified click on the link keeps the browser's own meaning: a new tab.
      const m = e as MouseEvent;
      if (m.ctrlKey || m.metaKey || m.shiftKey || m.button === 1) return;
      e.preventDefault();
      e.stopPropagation();
      if (openTask) p._openDetail('task', openTask);
      else p._openPart(assetId as string, partId as string);
    };
    chip.addEventListener('click', go);
    // An anchor already turns Enter into a click; only the chip needs the keys.
    if (chip.tagName === 'A') return;
    chip.addEventListener('keydown', (e) => {
      const key = (e as KeyboardEvent).key;
      if (key === 'Enter' || key === ' ') {
        e.preventDefault();
        go(e);
      }
    });
  });
}

/**
 * A device chip showing the integration's brand logo (falling back to a generic
 * device icon), with one of two destinations.
 *
 * Pass `assetId` and the chip stays inside the panel: it opens that appliance's
 * Home Keeper page. That is what the chip means on a *task* — "the appliance this
 * work is about" — and a device page, which knows nothing about Home Keeper, was
 * never the useful answer there.
 *
 * Leave `assetId` out and the chip keeps its original destination, the device's
 * Home Assistant page. That is what the chip means on an *appliance*, and it is
 * also the fallback for a task whose device no appliance claims. A chip that
 * leaves the panel says so with a trailing mark, so the two destinations are told
 * apart before the click rather than after it.
 */
export function deviceChip(p: PanelHost, deviceId: string, assetId?: string): string {
  const name = deviceName(p._hass?.devices, deviceId);
  // No name, no chip. The device has left the registry, so the chip had nothing to
  // say and its link went to a config page that no longer exists — the same guard
  // `areaChip` has always had. `virtualDeviceChip` checks the registry too.
  if (!name) return '';
  const domain = deviceDomain(p._hass?.devices?.[deviceId], p._entryDomains);
  const icon = domain
    ? `<img slot="icon" class="hk-dev-img" alt="" src="${escapeHTML(
        brandLogoUrl(domain),
      )}" data-domain="${escapeHTML(domain)}" />`
    : `<ha-svg-icon slot="icon" class="hk-dev-img"></ha-svg-icon>`;
  // The device page is admin-only, so for a view-only user a chip that goes there
  // only shows the name. `hk-dev-plain` gets the logo fallback and no link.
  if (!assetId && p._readOnly()) {
    return `<ha-assist-chip class="hk-dev-plain" label="${escapeHTML(name)}">${icon}</ha-assist-chip>`;
  }
  const asset = assetId ? ` data-asset-id="${escapeHTML(assetId)}"` : '';
  const tip = assetId ? t('chip.device.appliance.tip') : t('chip.device.tip');
  const chip = `<ha-assist-chip class="hk-device-chip" role="link" tabindex="0" data-device-id="${escapeHTML(
    deviceId,
  )}"${asset} label="${escapeHTML(name)}" title="${escapeHTML(tip)}">${icon}</ha-assist-chip>`;
  // The mark rides a wrapper rather than a sibling element: `wireLists` recounts the
  // "+n" label from the child count of `.hk-chips-inline`, so one chip has to stay
  // one child of it.
  return assetId ? chip : `<span class="hk-chip-ext">${chip}</span>`;
}

/**
 * Chip for a *virtual* appliance. A virtual asset now provisions a real HA device
 * (see `devices._reconcile_virtual`), so when that device is resolvable the chip is
 * a clickable link to its device page — reusing the same `.hk-device-chip` wiring as
 * the existing-device chip. Until the device is provisioned (or if it's gone) it
 * falls back to a static marker.
 */
export function virtualDeviceChip(p: PanelHost, asset: Asset): string {
  const deviceId = asset.device_id;
  const label = escapeHTML(t('chip.virtualDevice'));
  const tip = escapeHTML(t('chip.virtualDevice.tip'));
  // The device page is admin-only, so a view-only user gets the static marker.
  if (deviceId && p._hass?.devices?.[deviceId] && !p._readOnly()) {
    return `<ha-assist-chip class="hk-device-chip" role="link" tabindex="0" data-device-id="${escapeHTML(
      deviceId,
    )}" label="${label}" title="${tip}"><ha-icon slot="icon" icon="mdi:open-in-new" class="hk-chip-ic"></ha-icon></ha-assist-chip>`;
  }
  return `<ha-assist-chip label="${label}" title="${tip}"></ha-assist-chip>`;
}

/**
 * Wire navigation + brand-logo fallback for every device chip in the tree. Each chip
 * carries its own destination in the DOM — `data-asset-id` for an appliance page,
 * `data-device-id` for the Home Assistant device page — so this reads the chip rather
 * than the task or appliance it came from. It takes the panel only to reach
 * `_openDetail`, which is what keeps an in-panel hop on the panel's own history.
 *
 * `root` is a `ParentNode` rather than the shadow root, because `_applyQuery` rebuilds
 * only `#hk-list` for the text filter and re-wires that element alone.
 */
export function wireDeviceChips(p: PanelHost, root: ParentNode): void {
  root.querySelectorAll<HTMLElement>('.hk-device-chip, .hk-dev-plain').forEach((chip) => {
    const id = chip.dataset.deviceId;
    const assetId = chip.dataset.assetId;
    // Stop the event from bubbling to an enclosing `.detail-open` card row — without
    // this, clicking a device chip on a task/appliance card row is hijacked by the
    // row's open-detail handler and the chip never reaches its own destination.
    const go = (e?: Event): void => {
      e?.stopPropagation();
      if (assetId) p._openDetail('asset', assetId);
      else if (id) navigateTo(`/config/devices/device/${id}`);
    };
    // A plain chip (see `deviceChip`) is not a link. It only gets the logo fallback.
    if (chip.classList.contains('hk-device-chip')) {
      chip.addEventListener('click', go);
      chip.addEventListener('keydown', (e) => {
        const key = (e as KeyboardEvent).key;
        if (key === 'Enter' || key === ' ') {
          e.preventDefault();
          go(e);
        }
      });
    }
    const fallbackIcon = (): void => {
      const el = chip.querySelector('.hk-dev-img');
      if (!el) return;
      const svg = document.createElement('ha-svg-icon');
      (svg as HTMLElement & { path?: string }).path = MDI_DEVICES;
      svg.setAttribute('slot', 'icon');
      svg.className = 'hk-dev-img';
      el.replaceWith(svg);
    };
    const img = chip.querySelector<HTMLImageElement>('img.hk-dev-img');
    if (img) wireBrandImage(img, fallbackIcon);
    else fallbackIcon();
  });
}

/**
 * Make a brand logo `<img>` (with `data-domain`) fail over. The first error retries
 * the generic `_/` brand path. The second calls *fallback*, which puts an icon in
 * its place. The device chip and the companion row both use it, so a logo that is
 * not there fails over the same way on each.
 */
export function wireBrandImage(img: HTMLImageElement, fallback: () => void): void {
  img.addEventListener('error', () => {
    const domain = img.dataset.domain;
    if (domain && !img.dataset.retried) {
      img.dataset.retried = '1';
      img.src = brandLogoUrl(domain, true);
    } else {
      fallback();
    }
  });
}
