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
import { t } from './i18n';
import type { PanelHost } from './panel-host';
import { MDI_DEVICES } from './panel-icons';
import type { Asset, Task } from './types';
import {
  areaName,
  brandLogoUrl,
  deviceDomain,
  deviceName,
  escapeHTML,
  isHttpUrl,
  navigateTo,
  safeHref,
  scanRequired,
  tagName,
} from './utils';

/**
 * Whether a managed task's owning integration is no longer loaded. A task is
 * orphaned when its `config_entry_id` is set but absent from the loaded-entry
 * set (uninstalled, disabled, or failing to set up). Without a recorded
 * `config_entry_id` we can't prove the owner is gone, so it isn't treated as
 * orphaned (the `force` service is the escape hatch for that edge case).
 */
export function isManagedOrphan(p: PanelHost, task: Task): boolean {
  const id = task.managed_by?.config_entry_id;
  return Boolean(id) && !p._loadedEntryIds.has(id as string);
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
  const mb = task.managed_by;
  if (!mb) return '';
  if (isManagedOrphan(p, task)) {
    return `<ha-assist-chip class="hk-orphaned" label="${escapeHTML(t('chip.orphaned'))}"></ha-assist-chip>`;
  }
  // A task Home Keeper synced from a sensor is "owned" by Home Keeper itself, so
  // "Managed by Home Keeper" reads as redundant — call it what it is: auto-synced.
  const selfOwned = mb.integration === 'home_keeper';
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
 * A device chip that links to the device's HA config page and shows the
 * integration's brand logo (falling back to a generic device icon).
 */
export function deviceChip(p: PanelHost, deviceId: string): string {
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
  return `<ha-assist-chip class="hk-device-chip" role="link" tabindex="0" data-device-id="${escapeHTML(
    deviceId,
  )}" label="${escapeHTML(name)}">${icon}</ha-assist-chip>`;
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
  if (deviceId && p._hass?.devices?.[deviceId]) {
    return `<ha-assist-chip class="hk-device-chip" role="link" tabindex="0" data-device-id="${escapeHTML(
      deviceId,
    )}" label="${label}" title="${tip}"><ha-icon slot="icon" icon="mdi:open-in-new" class="hk-chip-ic"></ha-icon></ha-assist-chip>`;
  }
  return `<ha-assist-chip label="${label}" title="${tip}"></ha-assist-chip>`;
}

/** Wire navigation + brand-logo fallback for every device chip in the tree. Takes no
 *  `PanelHost`: every chip already carries its device id in `data-device-id`, so the
 *  wiring reads the DOM rather than the panel. */
export function wireDeviceChips(root: ShadowRoot): void {
  root.querySelectorAll<HTMLElement>('.hk-device-chip').forEach((chip) => {
    const id = chip.dataset.deviceId;
    // Stop the event from bubbling to an enclosing `.detail-open` card row — without
    // this, clicking a device chip on a task/appliance card row is hijacked by the
    // row's open-detail handler and the chip never reaches its device page.
    const go = (e?: Event): void => {
      e?.stopPropagation();
      if (id) navigateTo(`/config/devices/device/${id}`);
    };
    chip.addEventListener('click', go);
    chip.addEventListener('keydown', (e) => {
      const key = (e as KeyboardEvent).key;
      if (key === 'Enter' || key === ' ') {
        e.preventDefault();
        go(e);
      }
    });
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
    if (img) {
      img.addEventListener('error', () => {
        // First failure: retry the generic `_/` brand path; then give up.
        const domain = img.dataset.domain;
        if (domain && !img.dataset.retried) {
          img.dataset.retried = '1';
          img.src = brandLogoUrl(domain, true);
        } else {
          fallbackIcon();
        }
      });
    } else {
      fallbackIcon();
    }
  });
}
