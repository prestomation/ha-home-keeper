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
import type { FormField, HaFormElement } from './forms';
import type { MarkdownPreview } from './markdown';
import type {
  AssetEditState,
  AssetFilter,
  AssetView,
  CompletionDialogState,
  DeclarativeDialogState,
  EditState,
  GroupBy,
  MoveCompletionDialogState,
  NoteTarget,
  TaskFilter,
} from './panel-types';
import type {
  Asset,
  Companion,
  DeclarativeCompanion,
  DeclarativeCompanionPreset,
  Hass,
  HomeKeeperOptions,
  Task,
} from './types';
import type { AssetTab, BtnWeight, PanelLocation, SettingsSection } from './utils';

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
  /** Build a live Markdown preview under *host*, seeded with *initial*. The panel's
   *  only preview constructor: it registers each one for disposal (see the field
   *  comment on `_previews`), so a region must never build one itself. */
  _attachNotePreview(host: HTMLElement, initial: string): MarkdownPreview;
  /** A *disabled* Done wrapped in a clickable span that explains why, for a task whose
   *  source clears it (or which wants its tag scanned). */
  _blockedDone(wrapClass: string, task: Task, weight?: BtnWeight): string;
  /** The list card's muted "Clears automatically" caption — the inline form of the
   *  above, for a completion-blocked task in a row. */
  _blockedDoneInline(task: Task): string;
  /** A *disabled* Duplicate wrapped in a clickable span that explains why, for a task
   *  Home Keeper doesn't own. */
  _blockedDuplicate(task: Task): string;
  /** Whether *task*'s configuration can be copied into a new task. */
  _canDuplicate(task: Task): boolean;
  /** Task rows whose chip overflow the user unfolded. */
  _chipsExpanded: Set<string>;
  /** Leave the open detail page for the list it came from. */
  _closeDetail(): void;
  /** Discard the open appliance drawer. */
  _closeAssetForm(): void;
  /** Leave the open detail page for the list it came from. */
  _closeForm(): void;
  /** Leave an open Settings section for the section index (the phone's back arrow). */
  _closeSettingsSection(): void;
  /** Group sections the user collapsed this session, keyed by "<group>:<bucket>". */
  _collapsed: Set<string>;
  /** The completion-details dialog's state (logging one, or editing a recorded one). */
  _completion: CompletionDialogState;
  /** The companion integrations the Settings tab lists. */
  _companions: Companion[];
  /** The destructive-action confirmation's state. */
  _confirmDelete: { open: boolean; label: string; onConfirm: (() => void) | null };
  /** The document keydown (Escape) handler bound while the confirmation is open, held
   *  as a field so an unmount mid-dialog can remove it. */
  _confirmOnKey: ((e: KeyboardEvent) => void) | null;
  /** Body-level scrim for the confirmation overlay (outside the shadow root, so
   *  `position:fixed` resolves against the viewport). */
  _confirmScrim: HTMLElement | null;
  /** Record a completion for *task* (opening the details dialog when one is wanted). */
  _complete(task: Task): Promise<void>;
  /** Run *fn* once the key has been quiet for *ms*, so a per-keystroke save doesn't
   *  fire a config-entry reload on every character. */
  _debounce(key: string, fn: () => void, ms?: number): void;
  /** The declarative-companion dialogs' state: the preset picker, or the add/edit
   *  form with the recipe it is editing. */
  _declDialog: DeclarativeDialogState;
  /** Declarative-companion recipes stored on the config entry, listed under
   *  Settings → Companions. */
  _declarativeCompanions: DeclarativeCompanion[];
  /** The bundled presets the "Add from preset" picker offers. Fetched on the first
   *  open and kept; null until then. */
  _declarativePresets: DeclarativeCompanionPreset[] | null;
  /** Delete a task outright (already confirmed). */
  _delete(task: Task): Promise<void>;
  /** Delete an appliance outright (already confirmed). */
  _deleteAsset(asset: Asset): Promise<void>;
  /** The drawer's own Escape handler, taken away while a confirmation is up so one
   *  press cannot close both overlays. */
  _drawerOnKey: ((e: KeyboardEvent) => void) | null;
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
  /** Integration domains that have a config entry, for the declarative-companion
   *  form's integration picker and the preset picker's "requires" gate. Fetched on
   *  the first dialog open; null until then. */
  _installedIntegrations: string[] | null;
  /** Whether this user has dismissed the first-run intro banner. */
  _introDismissed: boolean;
  /** Profile / notification rows (and a profile's sync group) the user has expanded. */
  _itemExpanded: Set<string>;
  /** The language dates, times and numbers are formatted in (Home Assistant's). */
  _lang(): string | undefined;
  /** Live HA components that need `.hass` refreshed when hass updates. **Push-only**:
   *  the panel empties it in `_render`, at the point the shadow tree those elements
   *  live in is replaced — a region that reset it would stop feeding `hass` to
   *  everything an earlier pass registered. */
  _liveHassEls: Array<{ hass?: Hass }>;
  /** config entry ids currently loaded, for managed-task orphan detection. */
  _loadedEntryIds: Set<string>;
  /** Build one live `ha-form`, registered for `hass` updates. The panel's only
   *  `ha-form` constructor; *labelling* is for a form whose fields are not named from
   *  `field.<name>` (see the panel's own doc comment). */
  _makeForm(
    schema: FormField[],
    data: Record<string, unknown>,
    onChange: (value: Record<string, unknown>) => void,
    labelling?: {
      computeLabel: (s: { name: string }) => string;
      computeHelper?: (s: { name: string }) => string;
    },
  ): HaFormElement;
  /** Navigate within the panel; `replace` for a lateral move that Back should skip. */
  _navigate(loc: PanelLocation, replace?: boolean): void;
  /** A detail page's Notes card contents — rendered Markdown, or the inline editor. */
  _notesCardBody(
    target: NoteTarget,
    text: string,
    editable: boolean,
    placeholder?: string,
  ): string;
  /** The "move completion date" dialog's state. */
  _moveCompletion: MoveCompletionDialogState;
  /** Toast why *task*'s Done action is unavailable. */
  _notifyBlocked(task: Task): void;
  /** Toast why *task* can't be duplicated. */
  _notifyNoDuplicate(task: Task): void;
  /** The mobile_app_* notify services a notification can be delivered to. */
  _notifyTargets: string[];
  /** Open the drawer on a new task. */
  _openCreate(): void;
  /** Open the drawer on a new appliance. */
  _openCreateAsset(): void;
  /** Open an object's detail page (a Back-able step). */
  _openDetail(kind: 'task' | 'asset', id: string): void;
  /** Open the drawer on a new task prefilled with a copy of *task*. */
  _openDuplicate(task: Task): void;
  /** Open the drawer editing *task*. */
  _openEdit(task: Task): void;
  /** Open the drawer editing *asset*. */
  _openEditAsset(asset: Asset): void;
  /** Integration options — the saved Profiles the list filter offers live here. */
  _options: HomeKeeperOptions | null;
  /** Home Keeper's own todo entities, kept out of the shopping-list picker. */
  _ownTodoEntities: string[];
  /** The saved Profile id the task list is filtered by ('' = none). */
  _profile: string;
  /** Reload every collection from the backend and re-render. */
  _refresh(): Promise<void>;
  /** Reload every collection from the backend *without* re-rendering — for a save that
   *  must not tear down the form the user is still editing. */
  _reload(): Promise<void>;
  /** Rebuild the shadow tree from the current state. */
  _render(): void;
  /** Un-archive an appliance (the detail page's Restore button). */
  _restoreAsset(asset: Asset): Promise<void>;
  /** How a scroll the panel starts itself should move (honours reduced-motion). */
  _scrollBehavior(): ScrollBehavior;
  /** One-shot: the upload-error key the next render should scroll into view. */
  _scrollToError?: string;
  _setAssetFilter(value: AssetFilter): void;
  /** Switch the open appliance's sub-tab (replaces, so Back leaves the appliance). */
  _setAssetTab(tab: AssetTab): void;
  _setAssetView(value: AssetView): void;
  _setFilter(value: TaskFilter): void;
  _setGroupBy(value: GroupBy): void;
  _setProfile(value: string): void;
  /** Which Settings section the URL names, or null for the section index. */
  _settingsSection: SettingsSection | null;
  /** Settings sections (and profile sync groups) the user has collapsed this session. */
  _settingsSectionCollapsed: Set<string>;
  /** Save the open appliance drawer (validates, then creates or updates). */
  _submitAssetForm(): Promise<void>;
  /** Save the open task drawer (validates, then creates or updates). */
  _submitForm(): Promise<void>;
  /** Short-lived signed URLs for the uploaded files on screen; a detail page reads the
   *  href out of it as it renders and `_signFiles` fills in what wasn't minted yet. */
  _signedFiles: SignedUrlCache;
  /** HA tag-registry entries as picker options, for the tag chip. */
  _tags: { value: string; label: string }[];
  _tasks: Task[];
  /** The task form's notes preview, so its value-changed handler can feed it in place.
   *  Owned by the panel's `_previews` for disposal — this is only a reference. */
  _taskNotePreview: MarkdownPreview | null;
  /** Re-arm the drawer's modality (its Escape handler and sheet/side layout) after a
   *  confirmation that took it away has closed. */
  _syncDrawerModality(): void;
  /** Appliance ids whose tree children are folded away. */
  _treeCollapsed: Set<string>;
  /** Cancels the in-flight upload; undefined when none is running. */
  _uploadAbort?: AbortController;
  /** Pending "the upload has run long enough to show a bar" timer. */
  _uploadShowTimer?: ReturnType<typeof setTimeout>;
  /** Which top-level tab is showing. */
  _view: 'tasks' | 'appliances' | 'settings';
  /** Wire a detail page's inline notes editor (buttons + live preview). Stays on the
   *  panel: the preview it builds must be registered in `_previews` for disposal. */
  _wireNoteEditor(root: ShadowRoot, target: NoteTarget): void;
}
