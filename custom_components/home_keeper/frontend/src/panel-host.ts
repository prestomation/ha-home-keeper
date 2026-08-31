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

import type { SignedUrlCache } from './documents';
import type {
  AssetEditState,
  AssetFilter,
  AssetView,
  EditState,
  GroupBy,
  NoteTarget,
  TaskFilter,
} from './panel-types';
import type { Asset, Completion, Hass, HomeKeeperOptions, Task } from './types';
import type { AssetTab, BtnWeight, PanelLocation } from './utils';

export interface PanelHost extends HTMLElement {
  /** Archive an appliance (the detail page's Archive button). */
  _archiveAsset(asset: Asset): Promise<void>;
  /** The appliance edit drawer's state. `collapsibleSection` remembers a section's
   *  open/closed choice on `openSections`; see also the in-place mutation hazard
   *  documented on `_submitAssetForm`. */
  _assetEdit: AssetEditState;
  /** Which appliances the list shows: active or archived. */
  _assetFilter: AssetFilter;
  /** The appliance detail's Notes section. Stays on the panel because it delegates to
   *  `_notesSection`, which the drawer forms share. */
  _assetNotesSection(asset: Asset): string;
  _assets: Asset[];
  /** Which sub-tab the open appliance detail is showing. */
  _assetTab(): AssetTab;
  /** Flat list or parent/child tree, for the appliance list. */
  _assetView: AssetView;
  /** A *disabled* Done wrapped in a clickable span that explains why, for a task whose
   *  source clears it (or which wants its tag scanned). */
  _blockedDone(wrapClass: string, task: Task, weight?: BtnWeight): string;
  /** The list card's muted "Clears automatically" caption — the inline form of the
   *  above, for a completion-blocked task in a row. */
  _blockedDoneInline(task: Task): string;
  /** Task rows whose chip overflow the user unfolded. */
  _chipsExpanded: Set<string>;
  /** Leave the open detail page for the list it came from. */
  _closeDetail(): void;
  /** Group sections the user collapsed this session, keyed by "<group>:<bucket>". */
  _collapsed: Set<string>;
  /** Record a completion for *task* (opening the details dialog when one is wanted). */
  _complete(task: Task): Promise<void>;
  /** A task's part link as an "Appliance · Part · In stock: N" line (HTML). */
  _consumableLinkLabel(task: Task): string;
  /** Delete a task outright (already confirmed). */
  _delete(task: Task): Promise<void>;
  /** Delete an appliance outright (already confirmed). */
  _deleteAsset(asset: Asset): Promise<void>;
  /** The object whose full detail page is open, or null for the list view. */
  _detail: PanelLocation['detail'];
  /** The task edit drawer's state — a list row marks itself while it is being edited. */
  _edit: EditState;
  /** config entry id -> integration domain, for resolving device brand logos. */
  _entryDomains: Record<string, string>;
  /** Download the appliance inventory (the appliance list's Export action). */
  _exportInventory(): Promise<void>;
  /** Which scope pill the task list is filtered to. */
  _filter: TaskFilter;
  /** How the lists are grouped, as chosen (see `effectiveGroup` for the resolved one). */
  _groupBy: GroupBy;
  _hass?: Hass;
  /** Whether this user has dismissed the first-run intro banner. */
  _introDismissed: boolean;
  /** The language dates, times and numbers are formatted in (Home Assistant's). */
  _lang(): string | undefined;
  /** config entry ids currently loaded, for managed-task orphan detection. */
  _loadedEntryIds: Set<string>;
  /** Navigate within the panel; `replace` for a lateral move that Back should skip. */
  _navigate(loc: PanelLocation, replace?: boolean): void;
  /** A detail page's Notes card contents — rendered Markdown, or the inline editor. */
  _notesCardBody(
    target: NoteTarget,
    text: string,
    editable: boolean,
    placeholder?: string,
  ): string;
  /** Toast why *task*'s Done action is unavailable. */
  _notifyBlocked(task: Task): void;
  /** Open the completion-details dialog on an already-recorded completion. */
  _openCompletionEdit(task: Task, c: Completion): void;
  /** Open the destructive-action confirmation overlay. */
  _openConfirmDialog(label: string, onConfirm: () => void): void;
  /** Open the drawer on a new task. */
  _openCreate(): void;
  /** Open the drawer on a new appliance. */
  _openCreateAsset(): void;
  /** Open an object's detail page (a Back-able step). */
  _openDetail(kind: 'task' | 'asset', id: string): void;
  /** Open the drawer editing *task*. */
  _openEdit(task: Task): void;
  /** Open the drawer editing *asset*. */
  _openEditAsset(asset: Asset): void;
  /** Open the "move completion date" dialog for a recorded completion. */
  _openMoveCompletion(task: Task, ts: string): void;
  /** Integration options — the saved Profiles the list filter offers live here. */
  _options: HomeKeeperOptions | null;
  /** The saved Profile id the task list is filtered by ('' = none). */
  _profile: string;
  /** Reload every collection from the backend and re-render. */
  _refresh(): Promise<void>;
  /** Rebuild the shadow tree from the current state. */
  _render(): void;
  /** Un-archive an appliance (the detail page's Restore button). */
  _restoreAsset(asset: Asset): Promise<void>;
  _setAssetFilter(value: AssetFilter): void;
  /** Switch the open appliance's sub-tab (replaces, so Back leaves the appliance). */
  _setAssetTab(tab: AssetTab): void;
  _setAssetView(value: AssetView): void;
  _setFilter(value: TaskFilter): void;
  _setGroupBy(value: GroupBy): void;
  _setProfile(value: string): void;
  /** Short-lived signed URLs for the uploaded files on screen; a detail page reads the
   *  href out of it as it renders and `_signFiles` fills in what wasn't minted yet. */
  _signedFiles: SignedUrlCache;
  /** HA tag-registry entries as picker options, for the tag chip. */
  _tags: { value: string; label: string }[];
  _tasks: Task[];
  /** Appliance ids whose tree children are folded away. */
  _treeCollapsed: Set<string>;
  /** Which top-level tab is showing. */
  _view: 'tasks' | 'appliances' | 'settings';
  /** Wire a detail page's inline notes editor (buttons + live preview). Stays on the
   *  panel: the preview it builds must be registered in `_previews` for disposal. */
  _wireNoteEditor(root: ShadowRoot, target: NoteTarget): void;
}
