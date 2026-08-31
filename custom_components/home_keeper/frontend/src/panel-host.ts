/**
 * The slice of `HomeKeeperPanel` that the extracted region modules (`panel-*.ts`) are
 * allowed to touch.
 *
 * `panel.ts` is one class rendering every surface, and the regions being lifted out of
 * it are functions over that class rather than objects of their own. Rather than pass
 * the whole panel as `any`, each region takes a `PanelHost` — so what a region reads
 * and calls is declared, checked, and reviewable.
 *
 * Rules for this file:
 *
 * - Every member listed here is public-with-underscore on `HomeKeeperPanel`. The
 *   underscore still means "internal to the panel"; the `public` is what lets a region
 *   module reach it.
 * - Nothing outside `src/panel-*.ts` may use this interface. It is the panel's own
 *   seam, not a general API.
 * - **This list is the coupling surface.** Adding a member widens what every region can
 *   reach, so it is a deliberate act: prefer passing the value the region needs as an
 *   argument, and only add a member when the region genuinely needs the panel itself
 *   (its live state, or a method that re-enters the render).
 * - Keep it sorted, and only as wide as the extracted regions need — it grows one
 *   commit at a time, alongside the region that needs it.
 */

import type { AssetEditState } from './panel-types';
import type { Asset, Completion, Hass, Task } from './types';

export interface PanelHost extends HTMLElement {
  /** The appliance edit drawer's state. `collapsibleSection` remembers a section's
   *  open/closed choice on `openSections`; see also the in-place mutation hazard
   *  documented on `_submitAssetForm`. */
  _assetEdit: AssetEditState;
  _assets: Asset[];
  /** config entry id -> integration domain, for resolving device brand logos. */
  _entryDomains: Record<string, string>;
  _hass?: Hass;
  /** The language dates, times and numbers are formatted in (Home Assistant's). */
  _lang(): string | undefined;
  /** config entry ids currently loaded, for managed-task orphan detection. */
  _loadedEntryIds: Set<string>;
  /** Open the completion-details dialog on an already-recorded completion. */
  _openCompletionEdit(task: Task, c: Completion): void;
  /** Open the "move completion date" dialog for a recorded completion. */
  _openMoveCompletion(task: Task, ts: string): void;
  /** Reload every collection from the backend and re-render. */
  _refresh(): Promise<void>;
  /** HA tag-registry entries as picker options, for the tag chip. */
  _tags: { value: string; label: string }[];
  _tasks: Task[];
}
