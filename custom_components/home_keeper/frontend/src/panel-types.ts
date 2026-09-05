/**
 * The panel's own state vocabulary: the shapes its fields hold (edit drawers, dialog
 * state, upload progress) and the small constants that name things — the localStorage
 * keys its list controls persist under, and the upload-state keys.
 *
 * Data shapes that cross the websocket live in `types.ts`; these never leave the
 * panel, so they stay here rather than widening the shared surface.
 */

import type { Asset, Completion, DeclarativeCompanion, Task } from './types';

/**
 * The declarative-companion dialogs' state: the preset picker, or the add/edit form.
 * `draft` is the recipe the form edits **in place** (each section's form writes into
 * the same object), so a mode change can rebuild the dialog without losing what was
 * typed; it is null while the picker is up.
 */
export interface DeclarativeDialogState {
  open: boolean;
  kind: 'picker' | 'form';
  draft: DeclarativeCompanion | null;
  error?: string;
}

/** What the inline notes editor on a detail page is currently editing. */
export type NoteTarget = { kind: 'task' | 'asset'; id: string };

export interface EditState {
  open: boolean;
  task: Partial<Task> | null;
  error?: string;
}
export interface AssetEditState {
  open: boolean;
  asset: Partial<Asset> | null;
  error?: string;
  // Optional "Learn more" link shown beside the error (e.g. the docs for a proxy 413).
  errorLink?: string;
  // Id of the document currently being edited inline (its card shows a name/url form).
  editingDocId?: string;
  // Per-section expand state for the collapsible advanced editors (keyed "metadata"/
  // "parts"), preserved across re-renders so an expanded section doesn't snap shut
  // when an unrelated edit re-renders the form. Unset → defaults to "open if non-empty".
  openSections?: Record<string, boolean>;
  // The single in-flight upload, if any (one at a time — every upload button is
  // disabled while this is set). Lives in state, not just the DOM, so a re-render
  // mid-upload rebuilds the progress bar instead of dropping it.
  upload?: UploadState;
  // An upload failure rendered *inline*, next to the control that caused it. The
  // form-level `error` above is hundreds of pixels away from the upload buttons, which
  // is what made these failures look silent (issue #159).
  uploadError?: { key: string; message: string; link?: string };
}

/** Progress of the in-flight upload. `key` scopes it to the control that started it:
 *  "document" for the appliance's documents section, `part:<id>` for a part's file. */
export interface UploadState {
  key: string;
  filename: string;
  loaded: number;
  total: number;
  indeterminate: boolean;
  sent: boolean;
  /** Set once the upload has run long enough to be worth showing a bar for. */
  visible: boolean;
}

/** Upload state key for the appliance-documents upload control. */
export const UPLOAD_KEY_DOCUMENT = 'document';
/** Upload state key for a given part's file control. */
export const uploadKeyPart = (partId: string): string => `part:${partId}`;
/** How long an upload must run before the progress bar appears, so a small file that
 *  finishes almost immediately doesn't flash a bar on screen. */
export const UPLOAD_BAR_DELAY_MS = 150;

/**
 * The completion-details dialog state. Open either to *log* a new completion
 * (`ts` absent) or to *edit* a recorded one (`ts` set). `data` holds the in-progress
 * metadata; `required` is the set of fields that must be filled before saving.
 */
export interface CompletionDialogState {
  open: boolean;
  task: Task | null;
  ts?: string;
  data: {
    completedAt?: string;
    note?: string;
    cost?: number;
    photo?: string;
    who?: string;
    reading?: number;
  };
  required: string[];
  error?: string;
}
/**
 * The "move completion date" dialog state — re-timestamps an already-recorded
 * completion (identified by `ts`), distinct from `CompletionDialogState`'s
 * edit-metadata mode, which never touches the timestamp.
 */
export interface MoveCompletionDialogState {
  open: boolean;
  task: Task | null;
  ts: string;
  newTs?: string;
  error?: string;
}
/** One task's completion list within a history dialog (live or archived). */
export interface HistoryGroup {
  name: string;
  completions: Completion[];
  archived?: boolean;
  // Deletion context for the per-completion trash button: a live task carries
  // `taskId`; an archived (removed-task) group carries `assetId` + `archivedTaskId`.
  taskId?: string;
  assetId?: string;
  archivedTaskId?: string;
}
/** How the list view buckets rows; `status`/`device`/`integration` apply to tasks only. */
export type GroupBy = 'none' | 'status' | 'area' | 'device' | 'integration';
/** Task-list quick filter. */
export type TaskFilter = 'all' | 'overdue' | 'soon' | 'shopping';
/** Appliance-list quick filter. */
export type AssetFilter = 'active' | 'archived';
export type AssetView = 'flat' | 'tree';
/**
 * The panel's status vocabulary, as `card-filter.statusBucket` options: no separate
 * "today" section (anything due within the week reads as "Due soon"), and a completed
 * one-off gets its own collapsed section instead of the generic no-schedule bucket.
 * The card's defaults are the other way round.
 */
export const PANEL_BUCKETS = { today: false, completed: true } as const;
export const LS_GROUP = 'home-keeper.groupBy';
export const LS_FILTER = 'home-keeper.filter';
export const LS_ASSET_FILTER = 'home-keeper.assetFilter';
export const LS_PROFILE = 'home-keeper.profile';
export const LS_ASSET_VIEW = 'home-keeper.assetView';
export const LS_TREE_COLLAPSED = 'home-keeper.treeCollapsed';
