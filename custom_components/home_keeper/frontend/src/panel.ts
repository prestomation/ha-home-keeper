import { PANEL_VERSION } from 'panel-version';
import * as api from './api';
import { profileMatches } from './card-filter';
import type { SignedFileRef } from './documents';
import {
  SIGNED_URL_REFRESH_MS,
  SignedUrlCache,
  assetFileRefs,
  documentIcon,
  documentLabel,
  isDisplayableDocument,
  openDocument,
  openPartFile,
  signedFileKey,
} from './documents';
import {
  buildTaskPayload,
  cardLinkTokens,
  consumableLinkToken,
  haDateTimeToIso,
  isoToHaDateTime,
  selArea,
  selBool,
  selDate,
  selDateTime,
  generalSchema,
  notificationSchema,
  notifyFormData,
  notifyFormToNotification,
  problemSyncSchema,
  profileFormData,
  profileFormToProfile,
  profileSchema,
  shoppingSchema,
  selDevice,
  selIcon,
  selNumber,
  selSelect,
  selText,
  DEFAULT_BACKSTOP_INTERVAL,
  formRecurrenceSummary,
  sensorHintText,
  taskFormData,
  taskFormSchemaKey,
  taskSchema,
  type FormField,
  type HaFormElement,
} from './forms';
import { selEntity } from './forms';
import { setLanguage, t, tn } from './i18n';
import { MAX_DOCUMENT_BYTES } from './limits';
import {
  createPreview,
  ensureMarkdown,
  markdownBlock,
  markdownReady,
  wireMarkdown,
  type MarkdownPreview,
} from './markdown';
import type {
  Asset,
  AssetDocument,
  AssetKind,
  Companion,
  Completion,
  Hass,
  HomeKeeperOptions,
  ManagedBy,
  MetadataEntry,
  MetadataType,
  Notification,
  PanelInfo,
  Part,
  Profile,
  Task,
} from './types';
import {
  areaName,
  assetSummary,
  brandLogoUrl,
  buildPath,
  completionStats,
  deviceDomain,
  deviceName,
  dueLabel,
  escapeHTML,
  formatQuantity,
  isHttpUrl,
  isOverdue,
  isSafeImageUrl,
  parseRoute,
  randomId,
  readingUnit,
  round1,
  safeFileHref,
  safeHref,
  recurrenceSummary,
  scanRequired,
  tagName,
  taskRecordsReading,
  tasksForAsset,
  buildAssetTree,
  type PanelLocation,
} from './utils';

// mdi:devices — fallback icon when a device has no resolvable brand logo.
const MDI_DEVICES =
  'M3,6H21V4H3A2,2 0 0,0 1,6V18A2,2 0 0,0 3,20H7V18H3V6M13,12H9V13.78C8.39,' +
  '14.33 8,15.11 8,16C8,16.89 8.39,17.67 9,18.22V20H13V18.22C13.61,17.67 14,' +
  '16.88 14,16C14,15.11 13.61,14.33 13,13.78V12M11,17.5A1.5,1.5 0 0,1 9.5,16A1.5,' +
  '1.5 0 0,1 11,14.5A1.5,1.5 0 0,1 12.5,16A1.5,1.5 0 0,1 11,17.5M22,8H16A1,1 0 0,' +
  '0 15,9V19A1,1 0 0,0 16,20H22A1,1 0 0,0 23,19V9A1,1 0 0,0 22,8M21,18H17V10H21V18Z';

// Docs page listing known companion / glue integrations (Settings → Companions
// blurb links here). Points at the User Guide's Settings page anchor, which the
// docs site generates from README.md's "Companions" section.
const COMPANIONS_DOCS_URL =
  'https://prestomation.github.io/ha-home-keeper/docs/guide/settings#companions';

// User Guide page explaining sensor-based (usage-meter / threshold) tasks — the
// task form's help affordances link here. Generated from README.md's
// "Sensor-based tasks" section (slug `sensor-tasks`, see website/scripts/sync-docs.mjs).
const SENSOR_DOCS_URL = 'https://prestomation.github.io/ha-home-keeper/docs/guide/sensor-tasks';

/**
 * The Home Keeper panel is built entirely from Home Assistant's own web
 * components (the HA design language): `ha-form` for every form (which also
 * lazy-loads its selector widgets — text, number, select, date/time, and the
 * searchable device/area/icon pickers), `ha-card` for list rows, `ha-tab-group`
 * for navigation, `ha-button`/`ha-icon-button` for actions, `ha-assist-chip`
 * for status, and `ha-alert` for empty/error states. The header reuses
 * `ha-menu-button` so the sidebar toggle works on mobile.
 *
 * Because HA components take object/array properties (`.hass`, `.schema`,
 * `.data`) that can't be expressed as HTML attributes, we render the static
 * chrome with innerHTML and then "hydrate" the live components in a follow-up
 * pass (`_hydrate`), wiring `value-changed`/`click` there.
 */

// Components we rely on. They are part of HA's frontend bundle but some load
// lazily; wait for them (best-effort) before the first render so the panel
// doesn't flash un-upgraded custom elements.
const REQUIRED_COMPONENTS = [
  'ha-form',
  'ha-card',
  'ha-button',
  'ha-icon-button',
  'ha-tab-group',
  'ha-tab-group-tab',
  'ha-alert',
  'ha-assist-chip',
  'ha-menu-button',
  'ha-svg-icon',
  // Companion rows render arbitrary mdi icons by name; ha-icon lazy-loads them.
  'ha-icon',
];

// mdi:delete — remove a single completion entry from the history dialog.
const MDI_DELETE =
  'M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z';

// mdi:pencil — edit a single completion's metadata from the history list.
const MDI_EDIT =
  'M20.71,7.04C21.1,6.65 21.1,6 20.71,5.63L18.37,3.29C18,2.9 17.35,2.9 16.96,' +
  '3.29L15.12,5.12L18.87,8.87M3,17.25V21H6.75L17.81,9.93L14.06,6.18L3,17.25Z';

// `ha-icon` name for the same glyph, used as the trailing "opens in a new tab" hint on
// a document row's link (the string-template rows take an icon name, not a path).
const MDI_OPEN_IN_NEW_ICON = 'mdi:open-in-new';

// mdi:open-in-new — open a document (link or signed file URL) in a new tab.
const MDI_OPEN_IN_NEW =
  'M14,3V5H17.59L7.76,14.83L9.17,16.24L19,6.41V10H21V3M19,19H5V5H12V3H5C3.89,' +
  '3 3,3.9 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V12H19V19Z';

// mdi:calendar-edit — move (re-timestamp) a single completion entry.
const MDI_MOVE_DATE =
  'M19,19H5V8H19M16,1V3H8V1H6V3H5C3.89,3 3,3.9 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,' +
  '19V5C21,3.89 20.1,3 19,3H18V1M12.78,11.09L9,14.87L9,17H11.13L14.91,13.22L12.78,' +
  '11.09M16.31,10.44C16.5,10.25 16.5,9.94 16.31,9.75L15.16,8.6C14.97,8.41 14.66,8.41 ' +
  '14.47,8.6L13.44,9.63L15.28,11.47L16.31,10.44Z';

// mdi:autorenew — a wear item (replaced on a recurring schedule).
const MDI_WEAR =
  'M12,6V9L16,5L12,1V4A8,8 0 0,0 4,12C4,13.57 4.46,15.03 5.24,16.26L6.7,14.8C6.25,' +
  '13.97 6,13 6,12A6,6 0 0,1 12,6M18.76,7.74L17.3,9.2C17.74,10.04 18,11 18,12A6,6 0 0,' +
  '1 12,18V15L8,19L12,23V20A8,8 0 0,0 20,12C20,10.43 19.54,8.97 18.76,7.74Z';

// mdi:package-variant-closed — a consumable spare kept in stock.
const MDI_CONSUMABLE =
  'M21,16.5C21,16.88 20.79,17.21 20.47,17.38L12.57,21.82C12.41,21.94 12.21,22 12,22C11.79,' +
  '22 11.59,21.94 11.43,21.82L3.53,17.38C3.21,17.21 3,16.88 3,16.5V7.5C3,7.12 3.21,6.79 3.53,' +
  '6.62L11.43,2.18C11.59,2.06 11.79,2 12,2C12.21,2 12.41,2.06 12.57,2.18L20.47,6.62C20.79,' +
  '6.79 21,7.12 21,7.5V16.5M12,4.15L6.04,7.5L12,10.85L17.96,7.5L12,4.15M5,15.91L11,19.29V12.58L5,' +
  '9.21V15.91M19,15.91V9.21L13,12.58V19.29L19,15.91Z';

// The smallest a part quantity that must be *positive* can be. Stock itself may be
// zero (you're out), but "how much a completion uses" and "how much a restock adds"
// can't be — a zero there is a field that quietly does nothing. A number selector
// has no exclusive minimum, so the floor is one step of the stored precision.
const MIN_POSITIVE_QUANTITY = 0.001;

const STYLES = `
  :host { display: block; }
  .hk-toolbar {
    display: flex; align-items: center; gap: 12px; height: 56px;
    padding: 0 16px;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, var(--text-primary-color, #fff));
    --mdc-icon-button-size: 40px;
    box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0,0,0,.1));
  }
  .hk-toolbar-title { font-size: 1.25rem; font-weight: 400; flex: 1; }
  .hk-wrap { padding: 16px; max-width: 920px; margin: 0 auto; }
  ha-tab-group { margin-bottom: 16px; }
  .hk-actionbar { display: flex; justify-content: flex-end; margin-bottom: 12px; }
  ha-card.hk-card { margin-bottom: 12px; }
  .hk-card-row {
    display: flex; align-items: center; gap: 12px; padding: 12px 16px;
  }
  .hk-card-row .grow { flex: 1; min-width: 0; }
  .hk-name {
    font-weight: 500; display: flex; align-items: center; gap: 8px;
    flex-wrap: wrap;
  }
  .hk-meta { color: var(--secondary-text-color); font-size: 0.85rem; margin-top: 2px; }
  .hk-card-actions { display: flex; align-items: center; gap: 4px; }
  /* A completion-blocked Done (e.g. a synced problem sensor): the inner ha-button is
     natively disabled (greyed), and the wrapping span stays clickable so a tap can
     explain why it can't be completed here. */
  .done-blocked-wrap { cursor: pointer; display: inline-flex; }
  .done-blocked-wrap ha-button { pointer-events: none; }
  ha-assist-chip.hk-overdue {
    --ha-assist-chip-container-color: var(--error-color);
    --md-assist-chip-label-text-color: var(--text-primary-color, #fff);
    --ha-assist-chip-label-text-color: var(--text-primary-color, #fff);
    --md-assist-chip-outline-color: transparent;
  }
  ha-assist-chip.hk-managed {
    --ha-assist-chip-container-color: var(--info-color, #039BE5);
    --md-assist-chip-label-text-color: #fff;
    --ha-assist-chip-label-text-color: #fff;
    --md-assist-chip-outline-color: transparent;
  }
  ha-assist-chip.hk-orphaned {
    --ha-assist-chip-container-color: var(--warning-color, #FF9800);
    --md-assist-chip-label-text-color: #fff;
    --ha-assist-chip-label-text-color: #fff;
    --md-assist-chip-outline-color: transparent;
  }
  ha-assist-chip.hk-archived {
    --ha-assist-chip-container-color: var(--disabled-color, #9E9E9E);
    --md-assist-chip-label-text-color: #fff;
    --ha-assist-chip-label-text-color: #fff;
    --md-assist-chip-outline-color: transparent;
  }
  .hk-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
  .hk-task-chip-link { display: contents; }
  ha-assist-chip.hk-device-chip { cursor: pointer; }
  .hk-managed-prompt {
    font-size: 0.85rem; color: var(--secondary-text-color);
    background: var(--secondary-background-color);
    border-radius: 6px; padding: 8px 12px; margin-top: 8px;
  }
  .hk-managed-info {
    font-size: 0.8rem; color: var(--secondary-text-color);
    margin-top: 4px; font-style: italic; align-self: center;
  }
  .hk-dev-img {
    width: 18px; height: 18px; object-fit: contain; border-radius: 3px;
    --mdc-icon-size: 18px;
  }
  /* Small inline glyph carried in an assist-chip's icon slot / inline labels. */
  .hk-chip-ic { width: 16px; height: 16px; --mdc-icon-size: 16px; color: inherit; }
  /* A completion-blocked task shows a muted "Clears automatically" caption in the
     card's action slot instead of a dead greyed-out button. */
  .hk-auto-clear {
    display: inline-flex; align-items: center; gap: 4px; padding: 0 8px;
    font-size: 0.85rem; font-style: italic; color: var(--secondary-text-color);
    cursor: help;
  }
  /* First-run orientation banner above the task list (dismissible, persisted). */
  .hk-intro {
    border: 1px solid var(--divider-color);
    border-radius: 12px; padding: 16px; margin-bottom: 16px;
    background: var(--card-background-color);
  }
  .hk-intro-head { display: flex; align-items: center; gap: 8px; }
  .hk-intro-head .hk-form-title { flex: 1; margin-bottom: 0; }
  .hk-intro-body { color: var(--secondary-text-color); font-size: 0.9rem; margin: 8px 0; }
  .hk-intro ul { margin: 8px 0 12px; padding-inline-start: 20px; }
  .hk-intro li { color: var(--secondary-text-color); font-size: 0.9rem; margin: 4px 0; line-height: 1.4; }
  /* Collapsible advanced sections in the appliance editor (native <details>). */
  details.hk-collapsible { margin: 0; }
  details.hk-collapsible > summary {
    list-style: none; cursor: pointer; display: flex; align-items: center; gap: 6px;
  }
  details.hk-collapsible > summary::-webkit-details-marker { display: none; }
  details.hk-collapsible > summary .hk-section { margin-bottom: 0; flex: 1; }
  details.hk-collapsible > summary .hk-section-chevron { transition: transform 0.15s; }
  details.hk-collapsible[open] > summary .hk-section-chevron { transform: rotate(180deg); }
  .hk-form-card { margin-bottom: 16px; }
  .hk-form-inner { padding: 16px; }
  .hk-form-title {
    font-size: 1.1rem; font-weight: 500; margin-bottom: 8px;
    display: flex; align-items: center; gap: 6px;
  }
  .hk-form-help {
    color: var(--secondary-text-color); line-height: 0;
    --mdc-icon-size: 20px;
  }
  .hk-form-help:hover { color: var(--primary-color); }
  .hk-settings-intro {
    color: var(--secondary-text-color); font-size: 0.9rem;
    margin-bottom: 16px; line-height: 1.4;
  }
  /* Live "reads N -> due at M" primer under the sensor task fields. */
  .hk-form-hint {
    color: var(--secondary-text-color); font-size: 0.85rem; line-height: 1.4;
    margin-top: 8px; padding: 8px 12px;
    background: var(--secondary-background-color);
    border-radius: 8px;
    border-left: 3px solid var(--primary-color);
  }
  #hk-settings ha-form, #hk-settings-general ha-form { display: block; }
  /* Companions section (Settings tab). */
  .hk-companion-group {
    font-size: 0.8rem; font-weight: 600; color: var(--secondary-text-color);
    text-transform: uppercase; letter-spacing: 0.04em; margin: 20px 0 8px;
  }
  .hk-companion {
    display: flex; align-items: center; gap: 12px; padding: 12px 0;
    border-top: 1px solid var(--divider-color);
  }
  .hk-companion-ic { color: var(--state-icon-color, var(--primary-text-color)); flex: 0 0 auto; }
  .hk-companion-body { flex: 1 1 auto; min-width: 0; }
  .hk-companion-name { display: flex; align-items: center; gap: 8px; font-weight: 500; }
  .hk-companion-desc {
    color: var(--secondary-text-color); font-size: 0.9rem; line-height: 1.4; margin-top: 2px;
  }
  .hk-companion-actions { display: flex; align-items: center; gap: 4px; flex: 0 0 auto; flex-wrap: wrap; }
  /* Individual collapsible profile/notification items. */
  .hk-item-card {
    border: 1px solid var(--divider-color); border-radius: 8px;
    margin-top: 12px; overflow: hidden;
  }
  .hk-item-header {
    display: flex; align-items: center; gap: 8px; cursor: pointer;
    background: none; border: none; padding: 10px 12px; width: 100%;
    color: inherit; font: inherit; text-align: left;
  }
  .hk-item-header:hover { background: var(--secondary-background-color); }
  .hk-item-name { flex: 1; font-weight: 500; }
  .hk-item-body {
    padding: 0 12px 12px; display: flex; flex-direction: column; gap: 8px;
    border-top: 1px solid var(--divider-color);
  }
  .hk-item-body ha-form { display: block; }
  .hk-notify-delete { align-self: flex-end; --mdc-theme-primary: var(--error-color, #db4437); }
  .hk-notify-add { margin-top: 12px; }
  /* Collapsible settings section headers (Profiles, Notifications). */
  .hk-section-header {
    display: flex; align-items: center; gap: 8px; cursor: pointer;
    background: none; border: none; padding: 0; width: 100%;
    color: inherit; font: inherit; text-align: left; margin-bottom: 8px;
  }
  .hk-section-header:hover { opacity: 0.8; }
  .hk-section-title { flex: 1; margin-bottom: 0; }
  .hk-section-count {
    font-size: 0.8rem; color: var(--secondary-text-color);
    background: var(--secondary-background-color);
    border-radius: 999px; padding: 1px 8px; flex: 0 0 auto;
  }
  .hk-section-chevron {
    color: var(--secondary-text-color); flex: 0 0 auto;
    transition: transform 0.2s ease; transform: rotate(-90deg);
  }
  .hk-section-chevron.open { transform: rotate(0deg); }
  ha-assist-chip.hk-comp-connected {
    --ha-assist-chip-container-color: var(--success-color, #43a047);
    --ha-assist-chip-filled-container-color: var(--success-color, #43a047);
    --md-assist-chip-label-text-color: var(--text-primary-color, #fff);
  }
  ha-assist-chip.hk-comp-suggested {
    --ha-assist-chip-container-color: var(--warning-color, #ffa600);
  }
  .hk-section {
    font-size: 0.8rem; font-weight: 600; color: var(--secondary-text-color);
    text-transform: uppercase; letter-spacing: 0.04em; margin: 20px 0 8px;
  }
  .hk-part {
    border: 1px solid var(--divider-color); border-radius: 8px;
    padding: 8px 12px 12px; margin-bottom: 10px;
  }
  .hk-part-head { display: flex; align-items: center; justify-content: space-between; }
  .hk-part-head .label { font-size: 0.85rem; color: var(--secondary-text-color); }
  .hk-meta-seeds { display: flex; flex-wrap: wrap; gap: 8px; margin: 2px 0 4px; }
  .hk-meta-seeds ha-button { --mdc-typography-button-font-size: 0.8rem; }

  /* Documents editor — existing documents as clear cards, separated from the add area */
  .hk-doc-card {
    display: flex; align-items: center; gap: 12px;
    border: 1px solid var(--divider-color); border-radius: 8px;
    padding: 8px 8px 8px 12px; margin-bottom: 10px;
  }
  .hk-doc-ic {
    flex: none; width: 36px; height: 36px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    background: var(--secondary-background-color);
    color: var(--secondary-text-color); --mdc-icon-size: 20px;
  }
  .hk-doc-main { flex: 1; min-width: 0; }
  .hk-doc-name { font-weight: 500; word-break: break-word; }
  .hk-doc-sub {
    color: var(--secondary-text-color); font-size: 0.82rem; margin-top: 2px;
    word-break: break-word;
  }
  .hk-doc-actions { flex: none; display: flex; align-items: center; gap: 2px; }
  .hk-doc-edit { padding: 8px 12px 12px; }
  .hk-doc-edit-actions { display: flex; gap: 8px; margin-top: 4px; }
  .hk-doc-add {
    border: 1px dashed var(--divider-color); border-radius: 8px;
    padding: 4px 12px 12px; margin-top: 4px;
  }
  .hk-doc-add-title {
    font-size: 0.8rem; font-weight: 600; color: var(--secondary-text-color);
    margin: 10px 0 2px;
  }
  /* In-flight upload: progress bar, byte counter and a cancel button, rendered
     directly under the upload control that started it. The bar is plain DOM on
     theme variables — HA's own ha-progress-bar lives in a lazy-loaded chunk that
     isn't registered on a custom panel's page, so it would render as an invisible
     un-upgraded element. */
  .hk-upload { display: flex; flex-direction: column; gap: 6px; margin: 8px 0 4px; }
  .hk-upload-track {
    height: 4px; width: 100%; border-radius: 2px; overflow: hidden;
    background: var(--divider-color);
  }
  .hk-upload-fill {
    height: 100%; width: 0; border-radius: 2px;
    background: var(--primary-color); transition: width 120ms linear;
  }
  /* Indeterminate: a stripe that sweeps while we have no byte counts (before the
     first progress event, and while the server stores an already-sent file). */
  .hk-upload-track.indeterminate .hk-upload-fill {
    width: 30%; transition: none; animation: hk-upload-sweep 1.1s ease-in-out infinite;
  }
  @keyframes hk-upload-sweep {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(433%); }
  }
  .hk-upload-label { font-size: 0.82rem; color: var(--secondary-text-color); }
  .hk-upload ha-button { align-self: flex-start; --mdc-typography-button-font-size: 0.8rem; }

  /* Parts list on the appliance detail page */
  .hk-parts { display: flex; flex-direction: column; }
  .hk-part-row {
    display: flex; align-items: flex-start; gap: 14px; padding: 14px 0;
    border-bottom: 1px solid var(--divider-color);
  }
  .hk-part-row:first-child { padding-top: 2px; }
  .hk-part-row:last-child { border-bottom: none; padding-bottom: 2px; }
  .hk-part-ic {
    flex: none; width: 40px; height: 40px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    background: var(--secondary-background-color);
    color: var(--secondary-text-color); --mdc-icon-size: 22px;
  }
  .hk-part-row.wear .hk-part-ic {
    background: color-mix(in srgb, var(--primary-color) 16%, transparent);
    color: var(--primary-color);
  }
  .hk-part-row .grow { flex: 1; min-width: 0; }
  .hk-part-name {
    font-weight: 500; display: flex; align-items: center; gap: 8px;
    flex-wrap: wrap; word-break: break-word;
  }
  .hk-part-name a { color: var(--primary-color); }
  .hk-part-badge {
    font-size: 0.68rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--secondary-text-color);
    border: 1px solid var(--divider-color); border-radius: 10px; padding: 1px 8px;
  }
  .hk-part-row.wear .hk-part-badge {
    color: var(--primary-color);
    border-color: color-mix(in srgb, var(--primary-color) 50%, transparent);
  }
  /* A part's attached-file paperclip. The negative block margin keeps the 44px touch
     target (WCAG 2.5.5) from stretching the part row around a 16px icon. */
  .hk-part-file {
    display: inline-flex; align-items: center; justify-content: center; cursor: pointer;
    color: var(--secondary-text-color);
    min-width: 44px; min-height: 44px; margin: -14px 0;
  }
  .hk-part-file ha-icon { --mdc-icon-size: 16px; }
  .hk-part-file:hover { color: var(--primary-color); }
  .hk-part-sub {
    color: var(--secondary-text-color); font-size: 0.85rem; margin-top: 2px;
    word-break: break-word;
  }
  .hk-part-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
  .hk-part-chips ha-assist-chip { --ha-assist-chip-container-height: 28px; }
  .hk-part-notes { color: var(--secondary-text-color); margin-top: 6px; }
  /* The rule the form currently describes, in one sentence, immediately above the
     submit button — the last thing read before committing. Louder than .hk-form-hint
     on purpose: the hint explains, this one states the outcome. */
  .hk-form-summary {
    margin-top: 16px; padding: 10px 12px;
    background: var(--secondary-background-color);
    border-radius: 8px;
    border-left: 3px solid var(--primary-color);
    font-size: 0.95rem; line-height: 1.4;
  }
  .hk-form-summary-label {
    display: block;
    color: var(--secondary-text-color);
    font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em;
    margin-bottom: 2px;
  }
  .hk-form-summary-value { color: var(--primary-text-color); font-weight: 500; }
  /* The live arithmetic under the headline (sensor tasks only): quieter, because it
     elaborates the rule rather than restating it. */
  .hk-form-summary-detail {
    display: block; margin-top: 6px;
    color: var(--secondary-text-color); font-size: 0.85rem; line-height: 1.4;
  }
  .hk-form-actions { display: flex; gap: 8px; margin-top: 20px; }
  .hk-loading { display: flex; justify-content: center; padding: 48px 0; }
  .ver { color: var(--secondary-text-color); font-size: 0.7rem; text-align: right; margin-top: 16px; }
  .hk-card-row .grow.clickable { cursor: pointer; }
  ha-card.hk-card.overdue { border-left: 3px solid var(--error-color); }
  ha-card.hk-card.hk-tree-child {
    margin-left: calc(var(--hk-tree-depth, 0) * 14px);
    position: relative;
    background: color-mix(in srgb, var(--primary-color) calc(var(--hk-tree-depth, 0) * 4%), var(--card-background-color, #fff));
  }
  ha-card.hk-card.hk-tree-child::before {
    content: '';
    position: absolute;
    left: -10px;
    top: 50%;
    width: 7px;
    height: 2px;
    background: var(--divider-color);
  }
  ha-card.hk-card.hk-tree-child::after {
    content: '';
    position: absolute;
    left: -10px;
    top: 0;
    height: 100%;
    width: 2px;
    background: var(--divider-color);
  }
  ha-card.hk-card.hk-tree-child.hk-tree-last::after {
    height: 50%;
  }
  .hk-tree-group { margin: 0; }
  .hk-tree-parent-row {
    display: flex; align-items: flex-start; gap: 0;
  }
  .hk-tree-parent-row > ha-card { flex: 1; min-width: 0; }
  .hk-tree-group:not(.hk-tree-open) > .hk-tree-children { display: none; }
  .hk-chevron {
    display: flex; align-items: center; justify-content: center;
    width: 24px; height: 24px; flex-shrink: 0;
    margin-top: 16px; margin-right: 4px;
    border-radius: 50%;
    cursor: pointer;
  }
  .hk-chevron:hover { background: var(--secondary-background-color); }
  .hk-chevron::after {
    content: '';
    display: inline-block;
    width: 0; height: 0;
    border-left: 5px solid transparent; border-right: 5px solid transparent;
    border-top: 6px solid var(--secondary-text-color);
    transition: transform 0.15s ease;
  }
  .hk-tree-group:not(.hk-tree-open) .hk-chevron::after {
    transform: rotate(-90deg);
  }

  /* Filter / group-by controls */
  .hk-controls {
    display: flex; align-items: center; gap: 16px 24px; flex-wrap: wrap;
    margin-bottom: 16px;
  }
  .hk-control { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .hk-seg-label {
    font-size: 0.8rem; font-weight: 600; color: var(--secondary-text-color);
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  .hk-seg {
    display: inline-flex; border: 1px solid var(--divider-color);
    border-radius: 999px; overflow: hidden; background: var(--card-background-color);
  }
  .hk-seg-btn {
    appearance: none; border: 0; background: transparent; cursor: pointer;
    font: inherit; font-size: 0.85rem; padding: 6px 14px;
    color: var(--primary-text-color); white-space: nowrap;
    border-left: 1px solid var(--divider-color);
  }
  .hk-seg-btn:first-child { border-left: 0; }
  .hk-profile-select {
    appearance: auto; font: inherit; font-size: 0.85rem; padding: 6px 10px;
    border: 1px solid var(--divider-color); border-radius: 999px;
    background: var(--card-background-color); color: var(--primary-text-color);
    cursor: pointer; max-width: 240px;
  }
  .hk-seg-btn:hover { background: var(--secondary-background-color); }
  .hk-seg-btn.active {
    background: var(--primary-color);
    color: var(--text-primary-color, #fff); font-weight: 500;
  }

  /* Collapsible group sections */
  details.hk-group { margin-bottom: 12px; }
  details.hk-group > summary {
    list-style: none; cursor: pointer; display: flex; align-items: center;
    gap: 8px; padding: 6px 4px; user-select: none;
  }
  details.hk-group > summary::-webkit-details-marker { display: none; }
  details.hk-group > summary::before {
    content: ''; width: 0; height: 0; flex: none;
    border-left: 5px solid var(--secondary-text-color);
    border-top: 4px solid transparent; border-bottom: 4px solid transparent;
    transition: transform 0.15s ease; transform: rotate(0deg);
  }
  details.hk-group[open] > summary::before { transform: rotate(90deg); }
  .hk-group-title { font-weight: 600; font-size: 0.95rem; }
  .hk-group-count {
    font-size: 0.8rem; color: var(--secondary-text-color);
    background: var(--secondary-background-color);
    border-radius: 999px; padding: 1px 8px;
  }

  /* Detail page */
  .hk-detailbar { display: flex; align-items: center; margin-bottom: 12px; }
  .hk-detail-card { margin-bottom: 12px; }
  .hk-detail-inner { padding: 16px; }
  .hk-detail-title {
    font-size: 1.3rem; font-weight: 500; display: flex; align-items: center;
    gap: 8px; flex-wrap: wrap;
  }
  .hk-detail-card .hk-chips { margin-top: 10px; }
  .hk-detail-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }
  .hk-detail-row {
    display: flex; gap: 12px; padding: 6px 0; align-items: baseline;
    border-bottom: 1px solid var(--divider-color);
  }
  .hk-detail-row:last-child { border-bottom: none; }
  .hk-detail-row .k {
    flex: 0 0 40%; max-width: 220px; color: var(--secondary-text-color);
    font-size: 0.85rem;
  }
  .hk-detail-row .v { flex: 1; min-width: 0; word-break: break-word; }
  /* Usage-meter progress: how far through the service interval this task is. */
  .hk-meter {
    height: 6px; border-radius: 3px; margin: 10px 0 4px;
    background: var(--divider-color); overflow: hidden;
  }
  .hk-meter > span {
    display: block; height: 100%; border-radius: 3px;
    background: var(--primary-color);
  }
  .hk-meter-note { color: var(--secondary-text-color); font-size: 0.85rem; }
  /* Anything linked from a detail row must *look* clickable — an anchor whose href is
     filled in asynchronously (a signed file URL) gets no default affordance, which is
     what made document links read as dead text (issue #164). */
  .hk-detail-row .v a { color: var(--primary-color); cursor: pointer; }
  .hk-detail-row .v a:hover { text-decoration: underline; }
  /* Documents (manuals/warranties/receipts) sit in their own card, one row each. Both
     kinds — external link and uploaded file — render identically, with a comfortable
     touch target (>=44px, WCAG 2.5.5) so they're tappable on a phone. */
  .hk-doc-row .v a.hk-doc-file {
    display: inline-flex; align-items: center; gap: 6px;
    min-height: 44px; padding: 2px 0;
  }
  /* The glyphs inside a link are decoration — never a separate hit target that could
     swallow the tap meant for the anchor. */
  .hk-doc-file ha-icon, .hk-part-file ha-icon, .hk-doc-open ha-svg-icon {
    pointer-events: none;
  }
  .hk-doc-file .hk-doc-ext {
    --mdc-icon-size: 15px; flex: none; color: var(--secondary-text-color);
  }
  .hk-doc-file:hover .hk-doc-ext { color: var(--primary-color); }
  /* The editor's "Open" action is an anchor (a native navigation), sized and coloured
     to sit flush with the ha-icon-buttons — Edit, Remove — beside it. */
  .hk-doc-open {
    display: inline-flex; align-items: center; justify-content: center;
    width: 48px; height: 48px; flex: none; border-radius: 50%;
    color: var(--secondary-text-color); --mdc-icon-size: 24px;
  }
  .hk-doc-open:hover { color: var(--primary-color); }
  .hk-muted { color: var(--secondary-text-color); }
  .hk-note-input {
    width: 100%; box-sizing: border-box; resize: vertical; min-height: 72px;
    padding: 8px; border-radius: 8px; font: inherit; color: var(--primary-text-color);
    background: var(--card-background-color);
    border: 1px solid var(--divider-color);
  }
  .hk-note-input:focus { outline: none; border-color: var(--primary-color); }

  /* Markdown-rendered free text (notes, per-completion notes). ha-markdown brings
     its own theme-aware styles for links/code/pre; we only trim the outer margins so
     a note sits flush in its card, and cap heading sizes so a stray "# " in a note
     can't tower over the surrounding UI. .hk-md-plain is the escaped-text fallback
     used when ha-markdown could not be registered (see markdown.ts). */
  .hk-md { min-width: 0; word-break: break-word; }
  .hk-md-plain { white-space: pre-wrap; }
  .hk-md h1, .hk-md h2, .hk-md h3,
  .hk-md h4, .hk-md h5, .hk-md h6 { font-size: 1.05rem; margin: 12px 0 4px; }
  .hk-md > :first-child, .hk-md ha-markdown-element > :first-child { margin-top: 0; }
  .hk-md > :last-child, .hk-md ha-markdown-element > :last-child { margin-bottom: 0; }
  .hk-md ul, .hk-md ol { padding-inline-start: 24px; }
  .hk-md table { border-collapse: collapse; }
  .hk-md th, .hk-md td { border: 1px solid var(--divider-color); padding: 4px 8px; }
  /* Secondary-text density for notes shown as a subtitle (history rows, part rows). */
  .hk-md-compact { font-size: 0.9rem; }
  .hk-md-compact p, .hk-md-compact ul, .hk-md-compact ol { margin: 2px 0; }
  .hk-md-compact h1, .hk-md-compact h2, .hk-md-compact h3,
  .hk-md-compact h4, .hk-md-compact h5, .hk-md-compact h6 {
    font-size: 0.95rem; margin: 6px 0 2px;
  }
  /* Live preview under a notes editor — same visual language as .hk-form-hint. */
  .hk-md-preview {
    margin-top: 8px; padding: 8px 12px; border-radius: 8px;
    background: var(--secondary-background-color);
    border-left: 3px solid var(--primary-color);
  }
  .hk-md-preview-caption {
    font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--secondary-text-color); margin-bottom: 4px;
  }
  .hk-rel {
    display: flex; align-items: center; gap: 12px; padding: 8px 0;
    border-bottom: 1px solid var(--divider-color); cursor: pointer;
  }
  .hk-rel:last-child { border-bottom: none; }
  .hk-rel .grow { flex: 1; min-width: 0; }
  .hk-rel .hk-name { font-weight: 500; }

  .hk-hist-group { margin-bottom: 18px; }
  .hk-hist-group:last-child { margin-bottom: 0; }
  .hk-hist-head {
    display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
    font-weight: 500; margin-bottom: 6px;
  }
  .hk-hist-sub { color: var(--secondary-text-color); font-size: 0.85rem; font-weight: 400; }
  .hk-hist-archived {
    font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--secondary-text-color); border: 1px solid var(--divider-color);
    border-radius: 10px; padding: 1px 8px;
  }
  ul.hk-hist-list { list-style: none; margin: 0; padding: 0; }
  ul.hk-hist-list li {
    padding: 2px 0; border-bottom: 1px solid var(--divider-color);
  }
  ul.hk-hist-list li:last-child { border-bottom: none; }
  .hk-hist-row { display: flex; align-items: center; gap: 12px; }
  ul.hk-hist-list .date { flex: 1; min-width: 0; }
  ul.hk-hist-list .when { color: var(--secondary-text-color); font-size: 0.85rem; white-space: nowrap; }
  .hk-hist-actions { display: flex; align-items: center; }
  ha-icon-button.hk-hist-del, ha-icon-button.hk-hist-edit, ha-icon-button.hk-hist-move {
    --mdc-icon-button-size: 36px; color: var(--secondary-text-color);
  }
  .hk-hist-meta {
    display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px;
    margin: 0 0 6px 2px;
  }
  .hk-hist-chips { color: var(--secondary-text-color); font-size: 0.85rem; }
  /* Notes render as Markdown (a block), so give one its own full-width line under
     the cost/who chips rather than letting it share the flex row. */
  .hk-hist-note { font-size: 0.9rem; flex: 1 1 100%; min-width: 0; }
  .hk-hist-photo {
    height: 56px; width: 56px; object-fit: cover; border-radius: 8px;
    border: 1px solid var(--divider-color);
  }
  /* Completion-details dialog */
  .hk-completion-body { display: flex; flex-direction: column; gap: 12px; min-width: 320px; }
  .hk-completion-photo-label { font-weight: 500; font-size: 0.9rem; }
`;

/** What the inline notes editor on a detail page is currently editing. */
type NoteTarget = { kind: 'task' | 'asset'; id: string };

interface EditState {
  open: boolean;
  task: Partial<Task> | null;
  error?: string;
}
interface AssetEditState {
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
interface UploadState {
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
const UPLOAD_KEY_DOCUMENT = 'document';
/** Upload state key for a given part's file control. */
const uploadKeyPart = (partId: string): string => `part:${partId}`;
/** How long an upload must run before the progress bar appears, so a small file that
 *  finishes almost immediately doesn't flash a bar on screen. */
const UPLOAD_BAR_DELAY_MS = 150;

// Docs section explaining a 413 from a reverse proxy in front of HA (see README
// "Large uploads (413)"). Linked from the upload error so users can self-serve the fix.
const DOCS_UPLOAD_413_URL =
  'https://prestomation.github.io/ha-home-keeper/docs/guide/appliances#large-uploads-413';
/**
 * The completion-details dialog state. Open either to *log* a new completion
 * (`ts` absent) or to *edit* a recorded one (`ts` set). `data` holds the in-progress
 * metadata; `required` is the set of fields that must be filled before saving.
 */
interface CompletionDialogState {
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
interface MoveCompletionDialogState {
  open: boolean;
  task: Task | null;
  ts: string;
  newTs?: string;
  error?: string;
}
/** One task's completion list within a history dialog (live or archived). */
interface HistoryGroup {
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
type GroupBy = 'none' | 'status' | 'area' | 'device' | 'integration';
/** Task-list quick filter. */
type TaskFilter = 'all' | 'overdue' | 'soon' | 'shopping';
/** Appliance-list quick filter. */
type AssetFilter = 'active' | 'archived';
type AssetView = 'flat' | 'tree';
/** One bucket of rows rendered under a collapsible section header. */
interface Group<T> {
  /** Stable key for remembering collapse state, e.g. "status:overdue". */
  key: string;
  /** Section header text; empty string renders the rows ungrouped. */
  label: string;
  items: T[];
}
/** Tasks due within this many days (and not overdue) count as "due soon". */
const SOON_DAYS = 7;
const LS_GROUP = 'home-keeper.groupBy';
const LS_FILTER = 'home-keeper.filter';
const LS_ASSET_FILTER = 'home-keeper.assetFilter';
const LS_PROFILE = 'home-keeper.profile';
const LS_ASSET_VIEW = 'home-keeper.assetView';
const LS_TREE_COLLAPSED = 'home-keeper.treeCollapsed';

export class HomeKeeperPanel extends HTMLElement {
  private _hass?: Hass;
  public panel?: PanelInfo;
  public narrow = false;
  private _tasks: Task[] = [];
  private _assets: Asset[] = [];
  private _completion: CompletionDialogState = {
    open: false,
    task: null,
    data: {},
    required: [],
  };
  private _moveCompletion: MoveCompletionDialogState = {
    open: false,
    task: null,
    ts: '',
  };
  private _confirmDelete: { open: boolean; label: string; onConfirm: (() => void) | null } = {
    open: false,
    label: '',
    onConfirm: null,
  };
  // Body-level scrim for the delete confirmation overlay.
  private _confirmScrim: HTMLElement | null = null;
  // The document keydown (Escape) handler bound while the confirm dialog is open, held
  // as a field so disconnectedCallback can remove it if we unmount mid-dialog.
  private _confirmOnKey: ((e: KeyboardEvent) => void) | null = null;
  // config entry id -> integration domain, for resolving device brand logos.
  private _entryDomains: Record<string, string> = {};
  // config entry ids that are currently loaded, for managed-task orphan detection.
  private _loadedEntryIds: Set<string> = new Set();
  private _edit: EditState = { open: false, task: null };
  private _assetEdit: AssetEditState = { open: false, asset: null };
  // Cancels the in-flight upload (see `_runUpload`); undefined when none is running.
  private _uploadAbort?: AbortController;
  private _uploadShowTimer?: ReturnType<typeof setTimeout>;
  // One-shot: the upload-error key to scroll to on the next render.
  private _scrollToError?: string;
  private _view: 'tasks' | 'appliances' | 'settings' = 'tasks';
  // Integration options for the Settings tab (loaded lazily with the rest).
  private _options: HomeKeeperOptions | null = null;
  // Available mobile_app_* notify services (for the Notifications profile editor).
  private _notifyTargets: string[] = [];
  // Home Keeper's own todo entities, kept out of the shopping-list picker.
  private _ownTodoEntities: string[] = [];
  // Companion integrations shown on the Settings tab (loaded with the rest).
  private _companions: Companion[] = [];
  // HA tag-registry entries as picker options, for the task form's tag field and
  // the tag chip. Best-effort: an empty list still leaves a typable combo box.
  private _tags: { value: string; label: string }[] = [];
  // List controls (persisted in localStorage).
  private _groupBy: GroupBy = 'status';
  private _filter: TaskFilter = 'all';
  private _assetFilter: AssetFilter = 'active';
  private _assetView: AssetView = 'flat';
  private _treeCollapsed = new Set<string>();
  // Selected saved Profile id to filter the task list by ('' = no profile).
  private _profile = '';
  // Group sections collapsed by the user, keyed by "<group>:<bucket>".
  // Group sections the user collapsed this session (open is the default). The
  // "monitored" status bucket — dormant condition-driven tasks like healthy
  // batteries — starts collapsed so it stays out of the way but one click to browse.
  private _collapsed = new Set<string>(['status:monitored', 'status:completed']);
  // Settings sections (profiles, notifications) the user has collapsed this session.
  private _settingsSectionCollapsed = new Set<string>();
  // Individual profile/notification items the user has expanded (default: collapsed).
  private _itemExpanded = new Set<string>();
  // The object whose full detail page is open, or null for the list view.
  private _detail: { kind: 'task' | 'asset'; id: string } | null = null;
  // Short-lived signed URLs for the uploaded files on screen, minted ahead of the click
  // so every file is opened by a native anchor tap rather than a JS `window.open` the
  // iOS app's WKWebView would swallow (issue #164). Filled by `_signFiles`.
  private _signedFiles = new SignedUrlCache();
  // Pending re-sign of the on-screen files' URLs before they expire; see `_armResign`.
  private _resignTimer: ReturnType<typeof setTimeout> | null = null;
  // The panel's URL prefix (e.g. `/home-keeper`), supplied by HA via `route`.
  // Navigation builds absolute paths from it; falls back until the first route.
  private _routePrefix = '/home-keeper';
  private _loaded = false;
  private _loadError = false;
  // Whether the current user has dismissed the first-run intro banner — loaded from
  // HA's per-user frontend data store in `_reload` (see `_introCard`).
  private _introDismissed = false;
  // In-flight refresh, shared by overlapping callers. Both `set hass` (first update)
  // and `_init` gate on `!this._loaded`, and `_loaded` only flips true after the awaited
  // reload — so without coalescing they can pass the check and run two concurrent full
  // loads. Callers await the same promise, so none no-ops and all see a completed render.
  private _refreshing: Promise<void> | null = null;
  // Debounce timers for per-keystroke option saves (profiles / notifications), so a
  // text edit doesn't fire a config-entry reload on every character (and a slow
  // earlier response can't clobber a later one — only the trailing save runs).
  private _persistTimers: Record<string, ReturnType<typeof setTimeout>> = {};
  // A form to open once the pending navigation settles in `_applyLocation` (opening
  // an edit form from a detail page changes the URL, which would otherwise clear it).
  private _pendingEdit: Partial<Task> | null = null;
  private _pendingAssetEdit: Partial<Asset> | null = null;
  // What is being note-edited inline on a detail page, or null. Notes are long-form
  // prose that renders as Markdown, so both tasks and appliances get a dedicated
  // full-width editor on their detail page rather than a cramped row in the edit form
  // (parts keep theirs in the appliance's parts editor, alongside their other fields).
  // The textarea is uncontrolled: its value is read on Save, so typing doesn't trigger
  // a re-render (which would drop focus) — only the live preview updates, in place.
  private _noteEdit: NoteTarget | null = null;
  // Every live Markdown preview on screen — the inline note editors and the notes
  // fields in the edit forms/dialogs. All are built by `_attachNotePreview` (the only
  // constructor) and torn down together: they're rebuilt each render pass, and each
  // holds a debounce timer that must not outlive its DOM.
  private _previews: MarkdownPreview[] = [];
  // The task form's notes preview, so that form's value-changed handler can feed it.
  // Owned by `_previews` for disposal — this is only a reference.
  private _taskNotePreview: MarkdownPreview | null = null;
  // Live HA components that need `.hass` refreshed when hass updates.
  private _liveHassEls: Array<{ hass?: Hass }> = [];

  set hass(hass: Hass) {
    const first = !this._hass;
    // Keep the i18n module pointed at the user's HA language before any render.
    setLanguage(hass.language);
    this._hass = hass;
    // Keep selectors/pickers current without a disruptive full re-render.
    for (const el of this._liveHassEls) el.hass = hass;
    if (first && !this._loaded) void this._refresh();
  }
  get hass(): Hass | undefined {
    return this._hass;
  }

  /**
   * HA sets `route = { prefix, path }` on the panel element for every in-panel
   * URL change, including browser Back/Forward. We treat it as the single source
   * of truth: derive the view/detail from the path and render. This is what makes
   * deep links resolve and Back move within the panel instead of ejecting from it.
   */
  set route(route: { prefix?: string; path?: string } | undefined) {
    if (route?.prefix) this._routePrefix = route.prefix;
    this._applyLocation(parseRoute(route?.path));
  }

  /** Adopt a parsed location into view/detail state, rendering only on change. */
  private _applyLocation(loc: PanelLocation): void {
    const changed =
      loc.view !== this._view ||
      loc.detail?.kind !== this._detail?.kind ||
      loc.detail?.id !== this._detail?.id;
    if (!changed) return;
    this._view = loc.view;
    this._detail = loc.detail;
    // Leaving a list/detail closes any open form (forms are ephemeral overlays)...
    this._edit = { open: false, task: null };
    this._assetEdit = { open: false, asset: null };
    this._noteEdit = null;
    // ...unless this navigation was initiated to open a form (edit from a detail
    // page): re-open it now that the location has settled.
    if (this._pendingEdit) {
      this._edit = { open: true, task: this._pendingEdit };
      this._pendingEdit = null;
    }
    if (this._pendingAssetEdit) {
      this._assetEdit = { open: true, asset: this._pendingAssetEdit };
      this._pendingAssetEdit = null;
    }
    this._render();
  }

  /**
   * Navigate the panel by changing the URL — never by mutating view/detail
   * directly. HA's `location-changed` listener re-sets our `route`, which flows
   * back through `set route` so there is exactly one path into a state change.
   * Drill-in steps push (Back-able); lateral moves (tab switch) replace.
   */
  // Set to true the first time _navigate pushes a history entry, so _closeDetail
  // knows whether history.back() has a panel URL to return to.
  private _hasHistory = false;

  private _navigate(loc: PanelLocation, replace = false): void {
    const url = this._routePrefix + buildPath(loc);
    history[replace ? 'replaceState' : 'pushState'](null, '', url);
    if (!replace) this._hasHistory = true;
    this.dispatchEvent(
      new CustomEvent('location-changed', {
        detail: { replace },
        bubbles: true,
        composed: true,
      }),
    );
  }

  connectedCallback(): void {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    this._loadPrefs();
    void this._init();
  }

  disconnectedCallback(): void {
    // Tear down anything appended outside our shadow DOM so it can't leak on unmount:
    // the body-level confirm scrim and its document keydown listener (both live past
    // the element otherwise), plus any pending per-keystroke persist timers.
    if (this._confirmOnKey) {
      document.removeEventListener('keydown', this._confirmOnKey);
      this._confirmOnKey = null;
    }
    if (this._confirmScrim) {
      this._confirmScrim.remove();
      this._confirmScrim = null;
    }
    for (const id of Object.values(this._persistTimers)) clearTimeout(id);
    this._persistTimers = {};
    // Markdown previews hold a debounce timer that would otherwise fire against a
    // detached subtree after unmount.
    this._disposeAllPreviews();
    this._armResign(false);
  }

  /**
   * Tear down every live Markdown preview and drop the references to them.
   *
   * `_attachNotePreview` is the only constructor and registers each preview in
   * `_previews`, so this covers all of them — including `_taskNotePreview`, which is
   * only ever a second reference to one of them. Called from both the render reset and
   * `disconnectedCallback`; keep it the single teardown path so a future third caller
   * can't half-clean and leave a reference dangling.
   */
  private _disposeAllPreviews(): void {
    this._previews.forEach((p) => p.dispose());
    this._previews = [];
    this._taskNotePreview = null;
  }

  /** Restore the persisted group-by / filter choices (best-effort). */
  private _loadPrefs(): void {
    try {
      const g = localStorage.getItem(LS_GROUP);
      if (g === 'none' || g === 'status' || g === 'area' || g === 'device' || g === 'integration')
        this._groupBy = g;
      const f = localStorage.getItem(LS_FILTER);
      if (f === 'all' || f === 'overdue' || f === 'soon') this._filter = f;
      const af = localStorage.getItem(LS_ASSET_FILTER);
      if (af === 'active' || af === 'archived') this._assetFilter = af;
      const av = localStorage.getItem(LS_ASSET_VIEW);
      if (av === 'flat' || av === 'tree') this._assetView = av;
      const tc = localStorage.getItem(LS_TREE_COLLAPSED);
      if (tc) {
        try {
          const arr = JSON.parse(tc);
          if (Array.isArray(arr)) this._treeCollapsed = new Set(arr.filter((x: unknown) => typeof x === 'string'));
        } catch { /* ignore malformed */ }
      }
      this._profile = localStorage.getItem(LS_PROFILE) ?? '';
    } catch {
      // localStorage unavailable (e.g. private mode) — fall back to defaults.
    }
  }

  private _setGroupBy(value: GroupBy): void {
    if (this._groupBy === value) return;
    this._groupBy = value;
    try {
      localStorage.setItem(LS_GROUP, value);
    } catch {
      /* ignore */
    }
    this._render();
  }

  private _setFilter(value: TaskFilter): void {
    if (this._filter === value) return;
    this._filter = value;
    try {
      localStorage.setItem(LS_FILTER, value);
    } catch {
      /* ignore */
    }
    this._render();
  }

  private _setAssetFilter(value: AssetFilter): void {
    if (this._assetFilter === value) return;
    this._assetFilter = value;
    try {
      localStorage.setItem(LS_ASSET_FILTER, value);
    } catch {
      /* ignore */
    }
    this._render();
  }

  private _setAssetView(value: AssetView): void {
    if (this._assetView === value) return;
    this._assetView = value;
    try {
      localStorage.setItem(LS_ASSET_VIEW, value);
    } catch {
      /* ignore */
    }
    this._render();
  }

  /** Pick a saved Profile to drive the task-list filter (''/none clears it). */
  private _setProfile(value: string): void {
    if (this._profile === value) return;
    this._profile = value;
    try {
      localStorage.setItem(LS_PROFILE, value);
    } catch {
      /* ignore */
    }
    this._render();
  }

  // ── detail page lifecycle ───────────────────────────────────────────────────
  private _openDetail(kind: 'task' | 'asset', id: string): void {
    // Drilling in is a Back-able step: push.
    this._navigate({ view: kind === 'asset' ? 'appliances' : 'tasks', detail: { kind, id } });
  }
  private _closeDetail(): void {
    if (this._hasHistory) {
      // A pushState has occurred in this session: history.back() correctly pops
      // to whatever was before the current detail — even when the detail was
      // opened cross-view (e.g. a task opened from inside an appliance detail).
      history.back();
    } else {
      // No panel navigation has been pushed yet (user deep-linked directly to
      // this detail URL). Fall back to an explicit navigate to the owning list.
      this._navigate({ view: this._view, detail: null }, true);
    }
  }

  private async _init(): Promise<void> {
    // Best-effort: let HA's lazy components register before first paint.
    await Promise.all(
      REQUIRED_COMPONENTS.map((n) =>
        Promise.race([
          customElements.whenDefined(n),
          new Promise((r) => setTimeout(r, 4000)),
        ]),
      ),
    );
    this._render();
    if (this._hass && !this._loaded) void this._refresh();
  }

  /** Fetch tasks/assets/domains into state (no render). */
  private async _reload(): Promise<void> {
    if (!this._hass) return;
    try {
      const [
        tasks,
        assets,
        entryDomains,
        loadedEntryIds,
        options,
        companions,
        introDismissed,
        tags,
      ] = await Promise.all([
        api.getTasks(this._hass),
        api.getAssets(this._hass),
        api.getEntryDomains(this._hass).catch(() => ({})),
        api.getLoadedEntryIds(this._hass).catch(() => new Set<string>()),
        api.getOptions(this._hass).catch(() => null),
        api.getCompanions(this._hass).catch(() => [] as Companion[]),
        api.getIntroDismissed(this._hass).catch(() => false),
        // Best-effort: the tag registry is a convenience for the picker and the
        // chip label, never a precondition for the panel loading.
        api.getTags(this._hass).catch(() => [] as { value: string; label: string }[]),
      ]);
      this._tasks = tasks;
      this._assets = assets;
      this._entryDomains = entryDomains;
      this._loadedEntryIds = loadedEntryIds;
      this._options = options?.options ?? null;
      this._notifyTargets = options?.notifyTargets ?? [];
      this._ownTodoEntities = options?.ownTodoEntities ?? [];
      this._companions = companions ?? [];
      this._introDismissed = introDismissed;
      this._tags = tags;
      // Drop a remembered Profile filter that no longer exists (deleted since), so the
      // Tasks-tab dropdown and the stored id can't disagree.
      if (this._profile && !(this._options?.profiles ?? []).some((p) => p.id === this._profile)) {
        this._profile = '';
        try {
          localStorage.removeItem(LS_PROFILE);
        } catch {
          /* ignore */
        }
      }
      this._loaded = true;
      this._loadError = false;
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('home-keeper: failed to load data', err);
      // Surface a retry instead of spinning forever (the only auto-retry was on the
      // first `set hass`, so a transient WS failure at startup bricked the panel).
      this._loadError = true;
    }
  }

  private _refresh(): Promise<void> {
    // Coalesce overlapping refreshes onto one in-flight load so `set hass` and `_init`
    // can't run two concurrent full loads, while every `await this._refresh()` caller
    // still waits for a completed reload + render (a blanket early-return would let a
    // caller proceed against an unrendered view).
    if (this._refreshing) return this._refreshing;
    this._refreshing = (async () => {
      try {
        await this._reload();
        this._render();
      } finally {
        this._refreshing = null;
      }
    })();
    return this._refreshing;
  }

  // ── task form lifecycle ─────────────────────────────────────────────────────
  private _openCreate(): void {
    this._edit = {
      open: true,
      task: {
        recurrence_type: 'floating',
        interval: 1,
        unit: 'months',
        consumable_link: '',
      } as Partial<Task>,
    };
    this._render();
  }
  private _openEdit(task: Task): void {
    // Seed the flat consumable_link so the picker reflects the current link and a
    // plain save (no edit) round-trips it unchanged.
    const seeded = { ...task, consumable_link: consumableLinkToken(task) } as Partial<Task>;
    // Editing happens in the list view's form host; leave any open detail page. Drive
    // this through the URL (the single source of truth) rather than mutating
    // view/detail directly. When a detail page is open, the navigation changes the
    // location, and `_applyLocation` clears ephemeral forms — so stash the target as a
    // pending edit that `_applyLocation` re-opens after the reset (avoids the form
    // flashing open then being wiped by the async route round-trip). When already on
    // the list, the location is unchanged (no reset), so just open it directly.
    if (this._view === 'tasks' && !this._detail) {
      this._edit = { open: true, task: seeded };
      this._render();
    } else {
      this._pendingEdit = seeded;
      this._navigate({ view: 'tasks', detail: null });
    }
  }
  private _closeForm(): void {
    this._edit = { open: false, task: null };
    this._render();
  }

  private async _submitForm(): Promise<void> {
    if (!this._hass || !this._edit.task) return;
    const task = this._edit.task;
    if (!task.name || !String(task.name).trim()) {
      this._edit.error = t('error.nameRequired');
      this._render();
      return;
    }
    const payload = buildTaskPayload(task);
    try {
      const saved = task.id
        ? await api.updateTask(this._hass, task.id, payload)
        : await api.addTask(this._hass, payload);
      // Record the id immediately: if the link step below throws, the form stays open
      // and a retry must *update* this task, not create a second one.
      this._edit.task = { ...this._edit.task, id: saved.id };
      // The consumable link rides its own service (it sets the task's source, which
      // update_task doesn't touch). Only call when it actually changed: the desired
      // token vs. the saved task's current link.
      const desired = String((task as Record<string, unknown>).consumable_link ?? '');
      if (desired !== consumableLinkToken(saved)) {
        const [assetId, partId] = desired ? desired.split(':') : ['', ''];
        await api.setTaskConsumable(this._hass, saved.id, assetId || null, partId || null);
      }
      this._closeForm();
      await this._refresh();
    } catch (err) {
      this._edit.error = String((err as { message?: string })?.message || err);
      this._render();
    }
  }

  /** True when the inline notes editor is open on *target*. */
  private _editingNote(target: NoteTarget): boolean {
    return this._noteEdit?.kind === target.kind && this._noteEdit.id === target.id;
  }

  /** Open the inline notes editor on *target* (closing any other one). */
  private _openNoteEditor(target: NoteTarget): void {
    this._noteEdit = target;
    this._render();
  }

  /** Close the inline notes editor, discarding whatever was typed. */
  private _closeNoteEditor(): void {
    this._noteEdit = null;
    this._render();
  }

  /**
   * Persist an inline-edited note.
   *
   * Both kinds reuse the ordinary partial-update path — `update_task` for a task
   * (the store also mirrors a problem-sensor task's note into the durable,
   * entity-keyed side-store so it outlives the mirror) and `update_asset` for an
   * appliance (`merge_update` carries every unmentioned field through). On failure
   * the editor stays open with the typed text so the user can retry.
   */
  private async _saveNote(target: NoteTarget, notes: string): Promise<void> {
    if (!this._hass) return;
    try {
      if (target.kind === 'task') {
        await api.updateTask(this._hass, target.id, { notes });
      } else {
        await api.updateAsset(this._hass, target.id, { notes });
      }
      this._noteEdit = null;
      await this._refresh();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('Home Keeper: failed to save note', err);
      this._toast(t('error.actionFailed'));
    }
  }

  /**
   * The body of a detail page's Notes card: rendered Markdown plus an Edit button,
   * or — when this target is the one being edited — a textarea with a live preview.
   *
   * *editable* is false for a note the panel doesn't own (a source-managed task whose
   * `notes` field is locked by its integration), which keeps the read-only rendering.
   * *placeholder* lets a problem-sensor task keep its more pointed prompt.
   */
  private _notesCardBody(
    target: NoteTarget,
    text: string,
    editable: boolean,
    placeholder: string = t('note.placeholderMd'),
  ): string {
    const rendered = text
      ? markdownBlock(text)
      : `<span class="hk-muted">${escapeHTML(t('detail.noNotes'))}</span>`;
    if (!editable) return rendered;
    if (this._editingNote(target)) {
      // The preview is appended into `.d-note-preview` by `_wireNoteEditor` — it is a
      // live element driven by `input`, so it can't be part of this HTML string.
      return `
        <textarea class="hk-note-input d-note-input" rows="5"
          placeholder="${escapeHTML(placeholder)}">${escapeHTML(text)}</textarea>
        <div class="d-note-preview"></div>
        <div class="hk-detail-actions">
          <ha-button raised class="d-note-save">${escapeHTML(t('btn.save'))}</ha-button>
          <ha-button class="d-note-cancel">${escapeHTML(t('btn.cancel'))}</ha-button>
        </div>`;
    }
    const label = text ? t('note.edit') : t('note.add');
    return `${rendered}
      <div class="hk-detail-actions">
        <ha-button class="d-note-edit">${escapeHTML(label)}</ha-button>
      </div>`;
  }

  /** A whole Notes section (heading + card) for a detail page. */
  private _notesSection(target: NoteTarget, text: string, editable: boolean): string {
    return `<div class="hk-section">${escapeHTML(t('field.notes'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">${this._notesCardBody(
        target,
        text,
        editable,
      )}</div></ha-card>`;
  }

  /**
   * Append a live Markdown preview for a notes field to *host*, seeded with *initial*.
   *
   * The caller feeds it from its form's existing `value-changed` handler — updating the
   * preview in place rather than re-rendering, so the field keeps focus while typing
   * (the same technique `_updateFormHints` uses for the sensor primer).
   *
   * **This is the only way to build a preview.** Every one is registered in
   * `_previews`, which `_render` and `disconnectedCallback` dispose wholesale, so a
   * preview can never outlive its DOM with a debounce timer still armed. Constructing
   * one directly with `createPreview` would leak — don't.
   */
  private _attachNotePreview(host: HTMLElement, initial: string): MarkdownPreview {
    const preview = createPreview(t('note.preview'));
    this._previews.push(preview);
    host.appendChild(preview.el);
    preview.update(initial);
    return preview;
  }

  /** Wire the inline notes editor's buttons and its live preview. */
  private _wireNoteEditor(root: ShadowRoot, target: NoteTarget): void {
    root
      .querySelector('.d-note-edit')
      ?.addEventListener('click', () => this._openNoteEditor(target));
    root
      .querySelector('.d-note-cancel')
      ?.addEventListener('click', () => this._closeNoteEditor());
    const input = root.querySelector<HTMLTextAreaElement>('.d-note-input');
    root.querySelector('.d-note-save')?.addEventListener('click', () => {
      void this._saveNote(target, input?.value ?? '');
    });
    const host = root.querySelector<HTMLElement>('.d-note-preview');
    if (!input || !host) return;
    // A fresh preview per render pass — `_render` disposed the previous one and its
    // DOM is already gone. This runs from `_hydrate`, i.e. after that reset.
    const preview = this._attachNotePreview(host, input.value);
    input.addEventListener('input', () => preview.update(input.value));
  }

  private async _complete(task: Task): Promise<void> {
    if (!this._hass) return;
    // A scan-locked task is completed by its tag, not by this button. The backend
    // rejects the call outright, so say why here rather than surfacing its error.
    if (scanRequired(task)) {
      this._toast(t('done.needsScan'));
      return;
    }
    // Tasks set to capture detail open a dialog first; the default one-taps.
    const mode = task.completion_detail || 'none';
    if (mode === 'optional' || mode === 'required') {
      this._openCompletionDialog(task);
      return;
    }
    try {
      await api.completeTask(this._hass, task.id);
    } catch (err) {
      console.error('home-keeper: complete failed', err);
      this._toast(t('error.actionFailed'));
    }
    await this._refresh();
  }

  /** Open the completion-details dialog to log a new completion for *task*. */
  private _openCompletionDialog(task: Task): void {
    this._completion = {
      open: true,
      task,
      data: {},
      required:
        task.completion_detail === 'required' ? task.completion_required_fields || ['note'] : [],
    };
    this._render();
  }

  /** Open the dialog to edit an already-recorded completion's metadata. */
  private _openCompletionEdit(task: Task, c: Completion): void {
    this._completion = {
      open: true,
      task,
      ts: c.ts,
      data: { note: c.note, cost: c.cost, photo: c.photo, who: c.who, reading: c.reading },
      required: [],
    };
    this._render();
  }

  private _closeCompletionDialog(): void {
    this._completion = { open: false, task: null, data: {}, required: [] };
    this._render();
  }

  /**
   * Open the "move date" dialog to re-timestamp an already-recorded completion.
   * Distinct from `_openCompletionEdit` (metadata only) — this changes `ts` itself
   * via `api.moveCompletion`, never `api.updateCompletion`.
   */
  private _openMoveCompletion(task: Task, ts: string): void {
    this._moveCompletion = { open: true, task, ts, newTs: ts };
    this._render();
  }

  private _closeMoveCompletion(): void {
    this._moveCompletion = { open: false, task: null, ts: '' };
    this._render();
  }

  private async _submitMoveCompletion(): Promise<void> {
    const m = this._moveCompletion;
    if (!this._hass || !m.task || !m.newTs) return;
    try {
      await api.moveCompletion(this._hass, m.task.id, m.ts, m.newTs);
      this._closeMoveCompletion();
      await this._refresh();
    } catch (err) {
      m.error = String((err as { message?: string })?.message || err);
      this._render();
    }
  }

  private _openConfirmDialog(label: string, onConfirm: () => void): void {
    // Drop any prior scrim (and its keydown listener) before opening a new one, so a
    // second open — or a stale scrim — can't orphan the earlier overlay + handler.
    if (this._confirmOnKey) {
      document.removeEventListener('keydown', this._confirmOnKey);
      this._confirmOnKey = null;
    }
    if (this._confirmScrim) {
      this._confirmScrim.remove();
      this._confirmScrim = null;
    }
    this._confirmDelete = { open: true, label, onConfirm };
    this._renderConfirmDeleteDialog();
  }

  private _closeConfirmDialog(): void {
    this._confirmDelete = { open: false, label: '', onConfirm: null };
    if (this._confirmOnKey) {
      document.removeEventListener('keydown', this._confirmOnKey);
      this._confirmOnKey = null;
    }
    if (this._confirmScrim) {
      this._confirmScrim.remove();
      this._confirmScrim = null;
    }
  }

  private _renderConfirmDeleteDialog(): void {
    const { label, onConfirm } = this._confirmDelete;

    // Appended to document.body so position:fixed works correctly outside the
    // shadow DOM stacking context.
    const scrim = document.createElement('div');
    scrim.className = 'hk-confirm-scrim';
    scrim.style.cssText =
      'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;' +
      'justify-content:center;background:rgba(0,0,0,.4)';

    const modal = document.createElement('div');
    modal.style.cssText =
      'background:var(--ha-card-background,var(--card-background-color,#fff));' +
      'border-radius:28px;padding:24px;min-width:280px;max-width:400px;' +
      'box-shadow:0 8px 32px rgba(0,0,0,.24)';

    const h2 = document.createElement('h2');
    h2.style.cssText =
      'margin:0 0 16px;font-size:1.25rem;font-weight:500;' +
      'color:var(--primary-text-color,#000)';
    h2.textContent = label;

    const p = document.createElement('p');
    p.style.cssText = 'margin:0 0 24px;color:var(--secondary-text-color,#666)';
    p.textContent = t('confirm.cannotUndo');

    const row = document.createElement('div');
    row.style.cssText = 'display:flex;justify-content:flex-end;gap:8px';

    // Held on an instance field so disconnectedCallback can remove it if we unmount
    // while the dialog is open; _closeConfirmDialog is the single teardown path.
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') this._closeConfirmDialog();
    };
    this._confirmOnKey = onKey;
    document.addEventListener('keydown', onKey);

    const close = (): void => {
      this._closeConfirmDialog();
    };

    const cancel = document.createElement('ha-button');
    cancel.textContent = t('btn.cancel');
    cancel.addEventListener('click', close);

    const del = document.createElement('ha-button');
    del.setAttribute('raised', '');
    del.setAttribute('destructive', '');
    del.setAttribute('variant', 'danger');
    del.textContent = t('btn.delete');
    del.addEventListener('click', () => {
      onConfirm?.();
      this._closeConfirmDialog();
      // Re-render after the mutation: the confirm callbacks (metadata/part row
      // deletion) only mutate state, and neither this handler nor
      // _closeConfirmDialog rendered — so a deleted row stayed visible, and its
      // siblings' value-changed closures kept stale render-time indices that wrote
      // into the now-shifted array and corrupted the wrong entry. Rebuilding the form
      // with fresh indices fixes both.
      this._render();
    });

    row.appendChild(cancel);
    row.appendChild(del);
    modal.appendChild(h2);
    modal.appendChild(p);
    modal.appendChild(row);
    scrim.appendChild(modal);
    scrim.addEventListener('click', (e) => {
      if (e.target === scrim) close();
    });

    this._confirmScrim = scrim;
    document.body.appendChild(scrim);
  }

  /** True when every required field of the in-progress completion is filled. */
  private _completionMissing(): string[] {
    const d = this._completion.data;
    return this._completion.required.filter((f) => {
      const v = (d as Record<string, unknown>)[f];
      return v == null || v === '' || (typeof v === 'number' && Number.isNaN(v));
    });
  }

  /** Save the dialog: a new completion (with metadata) or an edit of a past one. */
  private async _submitCompletion(): Promise<void> {
    const c = this._completion;
    if (!this._hass || !c.task) return;
    if (c.ts == null && this._completionMissing().length) {
      c.error = t('completion.required');
      this._render();
      return;
    }
    try {
      if (c.ts != null) {
        await api.updateCompletion(this._hass, c.task.id, c.ts, c.data);
      } else {
        await api.completeTask(this._hass, c.task.id, c.data, c.data.completedAt);
      }
      this._closeCompletionDialog();
      await this._refresh();
    } catch (err) {
      c.error = String((err as { message?: string })?.message || err);
      this._render();
    }
  }

  /** A completion-blocked task (e.g. a synced problem sensor) can't be marked done
   *  here — its owning integration clears it. Explain why instead of completing.
   *  A scan-locked task is blocked for a different reason, so it says so instead. */
  private _notifyBlocked(task: Task): void {
    this._toast(this._blockedReason(task));
  }

  /** Why *task*'s Done action is unavailable, in the words the user needs: a
   *  scan-locked task wants its tag scanned, a source-owned one clears itself. */
  private _blockedReason(task: Task): string {
    if (scanRequired(task)) return t('done.needsScan');
    return task.managed_by?.completion_prompt || t('done.blocked');
  }

  /** Render a *disabled* Done for a completion-blocked task, wrapped in a clickable
   *  span (the native `disabled` greys the button correctly across HA button
   *  versions, but swallows clicks — so the span carries the tap → explanation and a
   *  hover tooltip). ``raised`` matches the prominent detail-page button. */
  private _blockedDone(wrapClass: string, task: Task, raised = false): string {
    const reason = this._blockedReason(task);
    const cls = [wrapClass, 'done-blocked-wrap'].filter(Boolean).join(' ');
    return `<span class="${cls}" data-id="${escapeHTML(task.id)}" role="button" tabindex="0" title="${escapeHTML(reason)}"><ha-button ${raised ? 'raised ' : ''}disabled>${escapeHTML(t('btn.done'))}</ha-button></span>`;
  }
  /** A muted "Clears automatically" caption for a completion-blocked task in the list
   *  card — self-explanatory inline (no hover needed), unlike a dead greyed button. It's
   *  a *status*, not an action, so it carries no button role: the visible label conveys
   *  the gist, `aria-label` gives assistive tech the full reason, `title` shows it on
   *  hover, and a pointer tap still surfaces it as a toast (via `.done-blocked-wrap`). */
  private _blockedDoneInline(task: Task): string {
    const reason = task.managed_by?.completion_prompt || t('done.blocked');
    const label = t('done.autoClears');
    return `<span class="hk-auto-clear done-blocked-wrap" data-id="${escapeHTML(task.id)}" title="${escapeHTML(reason)}" aria-label="${escapeHTML(`${label}: ${reason}`)}"><ha-icon icon="mdi:autorenew" class="hk-chip-ic"></ha-icon>${escapeHTML(label)}</span>`;
  }
  private async _delete(task: Task): Promise<void> {
    if (!this._hass) return;
    try {
      await api.deleteTask(this._hass, task.id);
      await this._refresh();
    } catch (err) {
      const msg = String((err as { message?: string })?.message || err);
      this._toast(msg);
      await this._refresh();
    }
  }

  // ── asset form lifecycle ────────────────────────────────────────────────────
  private _openCreateAsset(): void {
    this._assetEdit = { open: true, asset: { kind: 'virtual', parts: [] } };
    this._render();
  }
  private _openEditAsset(asset: Asset): void {
    // URL-driven (single source of truth); see _openEdit for the pending-edit dance
    // that survives `_applyLocation` clearing ephemeral forms on a route change.
    const seeded: Partial<Asset> = {
      ...asset,
      parts: [...(asset.parts || [])],
      metadata: (asset.metadata || []).map((m) => ({ ...m })),
    };
    if (this._view === 'appliances' && !this._detail) {
      this._assetEdit = { open: true, asset: seeded };
      this._render();
    } else {
      this._pendingAssetEdit = seeded;
      this._navigate({ view: 'appliances', detail: null });
    }
  }
  private _closeAssetForm(): void {
    this._assetEdit = { open: false, asset: null };
    this._render();
  }

  private async _submitAssetForm(): Promise<void> {
    if (!this._hass || !this._assetEdit.asset) return;
    const a = this._assetEdit.asset;
    if (a.kind === 'virtual' && !String(a.name || '').trim()) {
      this._setAssetError(t('error.nameRequiredAppliance'));
      this._render();
      return;
    }
    if (a.kind === 'existing' && !a.device_id) {
      this._setAssetError(t('error.pickDevice'));
      this._render();
      return;
    }
    const parts = (a.parts || []).filter((p) => p.name && p.name.trim());
    // Drop half-finished metadata rows (no label) so they don't fail validation.
    const metadata = (a.metadata || []).filter((m) => m.label && m.label.trim());
    // For a saved appliance, documents are managed live (their own backend calls), so
    // they're excluded from the batch save — omitting them preserves the server's list
    // (merge_update). A brand-new appliance has no live id yet, so its collected link
    // documents ride along in the create payload (the backend seeds links on create).
    const { documents, ...rest } = a;
    const payload: Partial<Asset> = { ...rest, parts, metadata };
    if (!a.id) payload.documents = (documents || []).filter((d) => d.kind === 'link' && d.url);
    try {
      if (a.id) await api.updateAsset(this._hass, a.id, payload);
      else await api.addAsset(this._hass, payload);
      this._closeAssetForm();
      await this._refresh();
    } catch (err) {
      this._setAssetError(String((err as { message?: string })?.message || err));
      this._render();
    }
  }

  private async _deleteAsset(asset: Asset): Promise<void> {
    if (!this._hass) return;
    try {
      await api.deleteAsset(this._hass, asset.id);
    } catch (err) {
      console.error('home-keeper: delete appliance failed', err);
      this._toast(t('error.actionFailed'));
    }
    await this._refresh();
  }

  /** Hide an appliance from the default list without deleting its data;
   *  reversible via {@link _restoreAsset}. */
  private async _archiveAsset(asset: Asset): Promise<void> {
    if (!this._hass) return;
    try {
      await api.archiveAsset(this._hass, asset.id);
      await this._refresh();
    } catch (err) {
      console.error('home-keeper: archive appliance failed', err);
      this._toast(t('error.actionFailed'));
    }
  }

  private async _restoreAsset(asset: Asset): Promise<void> {
    if (!this._hass) return;
    try {
      await api.restoreAsset(this._hass, asset.id);
      await this._refresh();
    } catch (err) {
      console.error('home-keeper: restore appliance failed', err);
      this._toast(t('error.actionFailed'));
    }
  }

  /**
   * Build the home-inventory report server-side and save it as a CSV — a
   * grab-and-go record for an insurance claim (make/model/serial, purchase +
   * warranty dates, replacement cost, on-hand spares value).
   */
  private async _exportInventory(): Promise<void> {
    if (!this._hass) return;
    try {
      const { csv } = await api.exportInventory(this._hass);
      const stamp = new Date().toISOString().slice(0, 10);
      this._downloadFile(`home-keeper-inventory-${stamp}.csv`, csv, 'text/csv');
    } catch (err) {
      console.error('home-keeper: inventory export failed', err);
      this._toast(t('error.exportFailed'));
    }
  }

  /** Coalesce rapid calls under *key*, running only the trailing one after *ms*. */
  private _debounce(key: string, fn: () => void, ms = 600): void {
    const prev = this._persistTimers[key];
    if (prev) clearTimeout(prev);
    this._persistTimers[key] = setTimeout(() => {
      delete this._persistTimers[key];
      fn();
    }, ms);
  }

  /** Surface a transient message via HA's toast notification. */
  private _toast(message: string): void {
    this.dispatchEvent(
      new CustomEvent('hass-notification', {
        detail: { message },
        bubbles: true,
        composed: true,
      }),
    );
  }

  /** Trigger a client-side file download (no server round-trip for the blob). */
  private _downloadFile(filename: string, contents: string, mime: string): void {
    const blob = new Blob([contents], { type: `${mime};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Defer revoke a tick so the download isn't cancelled in browsers that read the
    // blob URL asynchronously after click().
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  // ── completion history ──────────────────────────────────────────────────────
  /**
   * Completion groups for the detail page's history section. For a task: its own
   * completions. For an appliance: every completion tied to it — live related
   * tasks (part-derived or device-attached) plus the history archived from tasks
   * deleted while still assigned to it — newest activity first.
   */
  private _completionGroupsFor(kind: 'task' | 'asset', id: string): HistoryGroup[] {
    if (kind === 'task') {
      const task = this._tasks.find((t) => t.id === id);
      if (!task) return [];
      return [{ name: task.name, completions: task.completions || [], taskId: task.id }];
    }
    const asset = this._assets.find((a) => a.id === id);
    if (!asset) return [];
    const groups: HistoryGroup[] = tasksForAsset(asset, this._tasks).map((task) => ({
      name: task.name,
      completions: task.completions || [],
      taskId: task.id,
    }));
    for (const entry of asset.task_history || []) {
      groups.push({
        name: entry.task_name,
        completions: entry.completions || [],
        archived: true,
        assetId: asset.id,
        archivedTaskId: entry.task_id,
      });
    }
    const lastTs = (g: HistoryGroup): number =>
      g.completions.reduce((m, c) => Math.max(m, new Date(c.ts).getTime() || 0), 0);
    groups.sort((a, b) => lastTs(b) - lastTs(a));
    return groups;
  }

  private async _deleteCompletion(taskId: string, ts: string): Promise<void> {
    if (!this._hass) return;
    try {
      await api.deleteCompletion(this._hass, taskId, ts);
    } catch (err) {
      console.error('home-keeper: delete completion failed', err);
      this._toast(t('error.actionFailed'));
    }
    await this._refresh();
  }

  private async _deleteArchivedCompletion(
    assetId: string,
    archivedTaskId: string,
    ts: string,
  ): Promise<void> {
    if (!this._hass) return;
    try {
      await api.deleteArchivedCompletion(this._hass, assetId, archivedTaskId, ts);
    } catch (err) {
      console.error('home-keeper: delete archived completion failed', err);
      this._toast(t('error.actionFailed'));
    }
    await this._refresh();
  }

  /**
   * Keep trying to register HA's lazy `<ha-markdown>` until it sticks, re-rendering
   * once it does so notes upgrade from the escaped-text fallback to real Markdown.
   *
   * The retry matters for a cold deep-link to `/home-keeper`: `window.loadCardHelpers`
   * is installed by HA's Lovelace chunk, so it can be absent at first paint and appear
   * later once the user has visited a dashboard. Each attempt is a cheap no-op when
   * the helper is still missing, and `markdownReady()` short-circuits it forever after
   * the element registers — so this cannot loop.
   *
   * The registration attempt outlives a single render (it awaits a lazy chunk load), so
   * the callback checks `isConnected` before re-rendering: without that, unmounting
   * while one is in flight would rebuild the whole panel — forms, previews and their
   * debounce timers — onto a detached element that nothing will ever tear down again.
   */
  private _ensureMarkdown(): void {
    if (markdownReady()) return;
    void ensureMarkdown().then((ok) => {
      if (!ok || !this.isConnected) return;
      // Never mid-edit: this resolves a lazy chunk load later, so a user who opened a
      // form and started typing would have the field replaced under them — focus falls
      // back to `<body>` and HA's global one-letter shortcuts start eating the word.
      // Nothing is lost by waiting: each live preview re-checks `markdownReady()` when
      // it paints, so the open form upgrades on the next keystroke, and the panel-wide
      // upgrade lands on the next render.
      if (this._editingOpen()) return;
      this._render();
    });
  }

  /**
   * Whether the user is editing something that a re-render would destroy — a form or a
   * dialog with fields in it. Background refreshes that only improve the rendering
   * (never the data the user is looking at) stand down while this is true.
   */
  private _editingOpen(): boolean {
    return Boolean(
      this._edit.open ||
        this._assetEdit.open ||
        this._noteEdit ||
        this._completion.open ||
        this._moveCompletion.open,
    );
  }

  // ── rendering ───────────────────────────────────────────────────────────────
  private _render(): void {
    if (!this.shadowRoot) return;
    this._ensureMarkdown();
    this._liveHassEls = [];
    // Everything below is rebuilt from scratch, so every preview on screen is about to
    // be detached — cancel its pending debounce rather than leaking a timer.
    this._disposeAllPreviews();
    const onTasks = this._view === 'tasks';

    let inner: string;
    if (!this._loaded && this._loadError) {
      // A transient WS failure at startup used to leave the panel spinning forever
      // (only the very first `set hass` retried). Show a retry instead.
      inner = `<div class="hk-loading"><ha-alert alert-type="error">${escapeHTML(
        t('error.loadFailed'),
      )}</ha-alert><ha-button id="hk-retry" raised>${escapeHTML(
        t('btn.retry'),
      )}</ha-button></div>`;
    } else if (!this._loaded) {
      inner = `<div class="hk-loading"><ha-spinner size="large"></ha-spinner></div>`;
    } else if (this._detail) {
      inner = `
        <div class="hk-detailbar">
          <ha-button id="back-btn">‹ ${escapeHTML(t('btn.back'))}</ha-button>
        </div>
        ${this._detailView()}`;
    } else if (this._view === 'settings') {
      inner = `${this._tabs()}<div id="hk-settings-host"></div><div id="hk-profiles-host"></div><div id="hk-notifications-host"></div><div id="hk-companions-host"></div>`;
    } else {
      const addLabel = onTasks ? t('btn.addTask') : t('btn.addAppliance');
      inner = `
        ${this._tabs()}
        <div class="hk-actionbar">
          <ha-button raised id="add-btn">${escapeHTML(addLabel)}</ha-button>
          ${onTasks ? '' : `<ha-button id="export-btn">${escapeHTML(t('btn.exportInventory'))}</ha-button>`}
        </div>
        <div id="hk-form-host"></div>
        ${this._controls()}
        <div id="hk-list">${onTasks ? this._tasksList() : this._assetsList()}</div>`;
    }

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="hk-toolbar">
        <span id="menu-host"></span>
        <div class="hk-toolbar-title">${escapeHTML(t('app.title'))}</div>
      </div>
      <div class="hk-wrap">
        ${inner}
        <div class="ver">v${escapeHTML(PANEL_VERSION)}</div>
      </div>
      <div id="hk-dialog-host"></div>
    `;
    this._hydrate();
  }

  /** The top tab bar (Tasks / Appliances / Settings), with the active tab marked. */
  private _tabs(): string {
    const v = this._view;
    return `
      <ha-tab-group>
        <ha-tab-group-tab id="tab-tasks" panel="tasks" ${v === 'tasks' ? 'active' : ''}>${escapeHTML(t('tab.tasks'))}</ha-tab-group-tab>
        <ha-tab-group-tab id="tab-appliances" panel="appliances" ${v === 'appliances' ? 'active' : ''}>${escapeHTML(t('tab.appliances'))}</ha-tab-group-tab>
        <ha-tab-group-tab id="tab-settings" panel="settings" ${v === 'settings' ? 'active' : ''}>${escapeHTML(t('tab.settings'))}</ha-tab-group-tab>
      </ha-tab-group>`;
  }

  // ── list controls (filter + group-by) ───────────────────────────────────────
  /** Group-by resolved for the active view (appliances only support area/none). */
  private _effectiveGroup(): GroupBy {
    const taskOnlyGroups: GroupBy[] = ['status', 'device', 'integration'];
    if (this._view === 'appliances' && taskOnlyGroups.includes(this._groupBy)) {
      return 'none';
    }
    return this._groupBy;
  }

  private _controls(): string {
    const onTasks = this._view === 'tasks';
    const groupOpts: { value: GroupBy; label: string }[] = onTasks
      ? [
          { value: 'status', label: t('group.status') },
          { value: 'area', label: t('group.area') },
          { value: 'device', label: t('group.device') },
          { value: 'integration', label: t('group.integration') },
          { value: 'none', label: t('group.none') },
        ]
      : [
          { value: 'area', label: t('group.area') },
          { value: 'none', label: t('group.none') },
        ];
    const groupControl =
      this._view === 'appliances' && this._assetView === 'tree'
        ? ''
        : `<div class="hk-control">
            <span class="hk-seg-label">${escapeHTML(t('group.by'))}</span>
            ${this._seg('group', this._effectiveGroup(), groupOpts)}
          </div>`;
    // A saved Profile, when picked, drives the status/label/area/device filter, so
    // the inline all/overdue/soon segment is hidden while one is active.
    const profile = this._activeProfile();
    const filterControl =
      onTasks && !profile
        ? `<div class="hk-control">${this._seg('filter', this._filter, [
            { value: 'all', label: t('filter.all') },
            { value: 'overdue', label: t('filter.overdue') },
            { value: 'soon', label: t('filter.soon') },
            { value: 'shopping', label: t('filter.shopping') },
          ])}</div>`
        : '';
    const assetFilterControl =
      this._view === 'appliances'
        ? `<div class="hk-control">${this._seg('assetFilter', this._assetFilter, [
            { value: 'active', label: t('filter.active') },
            { value: 'archived', label: t('filter.archived') },
          ])}</div>`
        : '';
    const viewControl =
      this._view === 'appliances'
        ? `<div class="hk-control">
            <span class="hk-seg-label">${escapeHTML(t('view.label'))}</span>
            ${this._seg('assetView', this._assetView, [
              { value: 'flat', label: t('view.flat') },
              { value: 'tree', label: t('view.tree') },
            ])}
          </div>`
        : '';
    return `<div class="hk-controls">${filterControl}${assetFilterControl}${viewControl}${this._profileControl()}${groupControl}</div>`;
  }

  /** The saved Profile currently selected for the list filter, or null. */
  private _activeProfile(): Profile | null {
    if (this._view !== 'tasks' || !this._profile) return null;
    const profiles = this._options?.profiles ?? [];
    return profiles.find((p) => p.id === this._profile) ?? null;
  }

  /** A dropdown to filter the task list by a saved Profile (Tasks tab only). */
  private _profileControl(): string {
    if (this._view !== 'tasks') return '';
    const profiles = this._options?.profiles ?? [];
    if (!profiles.length) return '';
    const opt = (value: string, label: string) =>
      `<option value="${escapeHTML(value)}"${value === this._profile ? ' selected' : ''}>${escapeHTML(
        label,
      )}</option>`;
    const options = [
      opt('', t('filter.profileNone')),
      ...profiles.map((p) => opt(p.id, p.name)),
    ].join('');
    return `
      <div class="hk-control">
        <span class="hk-seg-label">${escapeHTML(t('filter.profile'))}</span>
        <select class="hk-profile-select" data-profile-filter>${options}</select>
      </div>`;
  }

  /** A pill-style segmented toggle; the active option carries the `active` class. */
  private _seg(name: string, current: string, options: { value: string; label: string }[]): string {
    const btns = options
      .map(
        (o) =>
          `<button class="hk-seg-btn${o.value === current ? ' active' : ''}" data-seg-val="${escapeHTML(
            o.value,
          )}">${escapeHTML(o.label)}</button>`,
      )
      .join('');
    return `<div class="hk-seg" data-seg="${escapeHTML(name)}">${btns}</div>`;
  }

  // ── list bucketing ──────────────────────────────────────────────────────────
  /** Which status section a task belongs to. */
  private _statusBucket(
    task: Task,
    now = Date.now(),
  ): 'overdue' | 'soon' | 'later' | 'monitored' | 'completed' | 'none' {
    // A dormant triggered/sensor task is "monitored" — armed-but-not-due — and lands in
    // its own (default-collapsed) section rather than the generic no-schedule bucket. An
    // armed one (next_due set) flows through the normal overdue/soon/later logic.
    if (
      (task.recurrence_type === 'triggered' || task.recurrence_type === 'sensor') &&
      !task.next_due
    )
      return 'monitored';
    // A completed one-off (do-once, now dormant) goes to its own collapsed section so
    // it leaves the active list without cluttering the generic no-schedule bucket.
    if (task.recurrence_type === 'one-off' && !task.next_due && task.last_completed)
      return 'completed';
    if (!task.next_due) return 'none';
    const due = new Date(task.next_due).getTime();
    if (Number.isNaN(due)) return 'none';
    if (due <= now) return 'overdue';
    if (due - now <= SOON_DAYS * 86_400_000) return 'soon';
    return 'later';
  }

  /** A task's area: its own, else its attached device's. */
  private _taskAreaId(task: Task): string | undefined {
    if (task.area_id) return task.area_id;
    const dev = task.device_id ? this._hass?.devices?.[task.device_id] : undefined;
    return dev?.area_id ?? undefined;
  }

  private _groupTasks(tasks: Task[], now = Date.now()): Group<Task>[] {
    const group = this._effectiveGroup();
    if (group === 'status') {
      const order: {
        bucket: 'overdue' | 'soon' | 'later' | 'monitored' | 'completed' | 'none';
        label: string;
      }[] = [
        { bucket: 'overdue', label: t('chip.overdue') },
        { bucket: 'soon', label: t('filter.soon') },
        { bucket: 'later', label: t('section.later') },
        { bucket: 'monitored', label: t('section.monitored') },
        { bucket: 'none', label: t('section.noSchedule') },
        { bucket: 'completed', label: t('section.completed') },
      ];
      return order
        .map(({ bucket, label }) => ({
          key: `status:${bucket}`,
          label,
          items: tasks.filter((task) => this._statusBucket(task, now) === bucket),
        }))
        .filter((g) => g.items.length);
    }
    if (group === 'area') {
      return this._groupByKey(
        tasks,
        (task) => this._taskAreaId(task),
        (id) => areaName(this._hass?.areas, id),
        t('section.unassigned'),
        'area',
      );
    }
    if (group === 'device') {
      return this._groupByKey(
        tasks,
        (task) => task.device_id ?? undefined,
        (id) => deviceName(this._hass?.devices, id),
        t('section.noDevice'),
        'device',
      );
    }
    if (group === 'integration') {
      return this._groupByKey(
        tasks,
        (task) => task.managed_by?.display_name ?? undefined,
        (name) => name,
        t('section.standalone'),
        'integration',
      );
    }
    return [{ key: '', label: '', items: tasks }];
  }

  private _groupAssets(assets: Asset[]): Group<Asset>[] {
    if (this._effectiveGroup() === 'area') {
      return this._groupByKey(
        assets,
        (a) => a.area_id ?? undefined,
        (id) => areaName(this._hass?.areas, id),
        t('section.unassigned'),
        'area',
      );
    }
    return [{ key: '', label: '', items: assets }];
  }

  /**
   * Bucket items by a key, label each section, sort sections alphabetically and
   * sink the "no key" fallback bucket to the bottom. Keys are namespaced so
   * collapse state never collides between grouping modes.
   */
  private _groupByKey<T>(
    items: T[],
    keyOf: (item: T) => string | undefined,
    labelOf: (key: string) => string,
    fallbackLabel: string,
    prefix: string,
  ): Group<T>[] {
    const buckets = new Map<string, T[]>();
    for (const item of items) {
      const k = keyOf(item) || '';
      const arr = buckets.get(k);
      if (arr) arr.push(item);
      else buckets.set(k, [item]);
    }
    const fallbackKey = `${prefix}:none`;
    const groups: Group<T>[] = [];
    for (const [k, arr] of buckets) {
      groups.push({
        key: k ? `${prefix}:${k}` : fallbackKey,
        label: k ? labelOf(k) : fallbackLabel,
        items: arr,
      });
    }
    groups.sort((a, b) => {
      const af = a.key === fallbackKey;
      const bf = b.key === fallbackKey;
      if (af !== bf) return af ? 1 : -1;
      return a.label.localeCompare(b.label);
    });
    return groups;
  }

  /** Render groups as collapsible sections, or bare items when ungrouped. */
  private _renderGroups<T>(groups: Group<T>[], renderItem: (item: T) => string): string {
    if (groups.length === 1 && !groups[0].label) {
      return groups[0].items.map(renderItem).join('');
    }
    return groups
      .map((g) => {
        const open = this._collapsed.has(g.key) ? '' : 'open';
        return `
        <details class="hk-group" data-group-key="${escapeHTML(g.key)}" ${open}>
          <summary class="hk-group-head">
            <span class="hk-group-title">${escapeHTML(g.label)}</span>
            <span class="hk-group-count">${g.items.length}</span>
          </summary>
          <div class="hk-group-body">${g.items.map(renderItem).join('')}</div>
        </details>`;
      })
      .join('');
  }

  /** One-time orientation banner that explains the kinds of tasks a newcomer will see
   *  mixed in the list. Dismissed permanently, server-side per-user (see
   *  `_introDismissed`). Empty once dismissed. */
  private _introCard(): string {
    if (this._introDismissed) return '';
    return `
      <div class="hk-intro">
        <div class="hk-intro-head">
          <div class="hk-form-title">${escapeHTML(t('tasks.intro.title'))}</div>
          <ha-icon-button class="hk-intro-dismiss" label="${escapeHTML(
            t('tasks.intro.dismiss'),
          )}"><ha-icon icon="mdi:close"></ha-icon></ha-icon-button>
        </div>
        <div class="hk-intro-body">${escapeHTML(t('tasks.intro.body'))}</div>
        <ul>
          <li>${t('tasks.intro.recurring')}</li>
          <li>${t('tasks.intro.monitored')}</li>
          <li>${t('tasks.intro.companion')}</li>
        </ul>
        <ha-button class="hk-intro-dismiss">${escapeHTML(t('tasks.intro.dismiss'))}</ha-button>
      </div>`;
  }

  private _tasksList(): string {
    const intro = this._introCard();
    if (!this._tasks.length) {
      const addTask = `<b>${escapeHTML(t('btn.addTask'))}</b>`;
      return `${intro}<ha-alert alert-type="info">${t('tasks.empty', { addTask })}</ha-alert>`;
    }
    const now = Date.now();
    let tasks = [...this._tasks];
    const profile = this._activeProfile();
    if (profile) {
      // A saved Profile replaces the inline filter: status + labels/areas/devices.
      tasks = tasks.filter((task) =>
        profileMatches(task, profile.filter, this._hass?.devices, this._hass?.areas, now),
      );
    } else if (this._filter === 'overdue') tasks = tasks.filter((task) => isOverdue(task));
    else if (this._filter === 'soon')
      tasks = tasks.filter((task) => this._statusBucket(task, now) === 'soon');
    else if (this._filter === 'shopping')
      tasks = tasks.filter((task) => Boolean(task.source?.buy));
    tasks.sort((a, b) => {
      const ad = a.next_due ? new Date(a.next_due).getTime() : Infinity;
      const bd = b.next_due ? new Date(b.next_due).getTime() : Infinity;
      return ad - bd;
    });
    if (!tasks.length) {
      return `${intro}<ha-alert alert-type="info">${escapeHTML(t('tasks.noMatch'))}</ha-alert>`;
    }
    return `${intro}${this._orphanBanner()}${this._renderGroups(
      this._groupTasks(tasks, now),
      (task) => this._taskCard(task),
    )}`;
  }

  /**
   * A dismissable-style warning shown above the task list when one or more managed
   * tasks have been orphaned (their integration was uninstalled/disabled). Offers a
   * one-click "Remove orphaned tasks" cleanup so the user isn't stuck with tasks no
   * integration owns any more.
   */
  private _orphanBanner(): string {
    const n = this._tasks.filter((task) => this._isManagedOrphan(task)).length;
    if (!n) return '';
    return `
      <ha-alert alert-type="warning" class="hk-orphan-banner">
        ${escapeHTML(tn('managed.orphanBanner', n))}
        <ha-button slot="action" id="cleanup-orphans-btn">${escapeHTML(
          t('btn.removeOrphaned'),
        )}</ha-button>
      </ha-alert>`;
  }

  /** Delete every orphaned managed task (the bulk cleanup action). */
  private async _cleanupOrphans(): Promise<void> {
    if (!this._hass) return;
    const orphans = this._tasks.filter((task) => this._isManagedOrphan(task));
    if (!orphans.length) return;
    try {
      for (const task of orphans) await api.deleteTask(this._hass, task.id);
    } catch (err) {
      this._toast(String((err as { message?: string })?.message || err));
    }
    await this._refresh();
  }

  private _assetsList(): string {
    if (!this._assets.length) {
      return `<ha-alert alert-type="info">${escapeHTML(t('appliances.empty'))}</ha-alert>`;
    }
    const archived = this._assetFilter === 'archived';
    const filtered = this._assets.filter((a) => Boolean(a.archived_at) === archived);
    if (!filtered.length) {
      const emptyKey = archived ? 'appliances.archivedEmpty' : 'appliances.noMatch';
      return `<ha-alert alert-type="info">${escapeHTML(t(emptyKey))}</ha-alert>`;
    }
    const cmp = (a: Asset, b: Asset) => (a.name || '').localeCompare(b.name || '');
    if (this._assetView === 'tree') {
      const tree = buildAssetTree(filtered, cmp);
      const renderSubtree = (start: number, parentDepth: number): [string, number] => {
        let html = '';
        let i = start;
        while (i < tree.length && tree[i].depth > parentDepth) {
          const entry = tree[i];
          const depth = entry.depth;
          const hasChildren = i + 1 < tree.length && tree[i + 1].depth > depth;
          if (hasChildren) {
            const [childrenHtml, nextI] = renderSubtree(i + 1, depth);
            const isLast = nextI >= tree.length || tree[nextI].depth <= parentDepth;
            const isOpen = !this._treeCollapsed.has(entry.item.id);
            html += `<div class="hk-tree-group${isOpen ? ' hk-tree-open' : ''}">
              <div class="hk-tree-parent-row">
                <span class="hk-chevron" data-tree-toggle="${escapeHTML(entry.item.id)}"></span>
                ${this._assetCard(entry.item, depth, isLast)}
              </div>
              <div class="hk-tree-children">${childrenHtml}</div>
            </div>`;
            i = nextI;
          } else {
            i++;
            const isLast = i >= tree.length || tree[i].depth <= parentDepth;
            html += this._assetCard(entry.item, depth, isLast);
          }
        }
        return [html, i];
      };
      const [html] = renderSubtree(0, -1);
      return html;
    }
    const assets = [...filtered].sort(cmp);
    return this._renderGroups(this._groupAssets(assets), (asset) => this._assetCard(asset));
  }

  private _taskCard(task: Task): string {
    const overdue = isOverdue(task);
    const statusChip = overdue
      ? `<ha-assist-chip class="hk-overdue" label="${escapeHTML(t('chip.overdue'))}"></ha-assist-chip>`
      : `<ha-assist-chip label="${escapeHTML(dueLabel(task, undefined, this._hass))}"></ha-assist-chip>`;
    const dev = task.device_id ? this._deviceChip(task.device_id) : '';
    const tagChip = this._tagChip(task);
    const managedChip = this._managedChip(task);
    const taskChips = this._taskChipsHtml(task);
    // A completed one-off (do-once, now dormant) shows when it was done instead of a
    // due date.
    const completedOneOff =
      task.recurrence_type === 'one-off' && !task.next_due && !!task.last_completed;
    const dueText = task.next_due
      ? ` · ${escapeHTML(t('form.task.due', { date: new Date(task.next_due).toLocaleDateString() }))}`
      : completedOneOff
        ? ` · ${escapeHTML(t('form.task.completedOn', { date: new Date(task.last_completed as string).toLocaleDateString() }))}`
        : '';
    // For an overdue task, append *how* overdue it is — a bare date hides urgency. Use
    // whole elapsed days (floor), and only once at least one full day has passed: a
    // task overdue by mere hours reads as "Overdue" alone rather than an inflated
    // "1 day overdue".
    const overdueDays = task.next_due
      ? Math.floor((Date.now() - new Date(task.next_due).getTime()) / 86_400_000)
      : 0;
    const overdueText =
      overdue && overdueDays >= 1 ? ` · ${escapeHTML(tn('due.overdue_by', overdueDays))}` : '';
    const n = task.completions?.length ?? 0;
    // A dormant triggered task (monitored, not due) has nothing to mark done — its
    // owning integration arms it when the condition fires; hide the action. A
    // completed one-off is already done, so it too hides Done. A completion-blocked
    // task (e.g. a synced problem sensor) keeps a *disabled* Done that explains why
    // on click, rather than silently offering no action.
    const dormantTriggered = task.recurrence_type === 'triggered' && !task.next_due;
    // A scan-locked task keeps a *disabled* Done rather than the auto-clear caption:
    // it is still completable, just not from here, so a greyed button that explains
    // itself on tap is the honest affordance.
    const doneAction = dormantTriggered || completedOneOff
      ? ''
      : task.managed_by?.completion_blocked
        ? this._blockedDoneInline(task)
        : scanRequired(task)
          ? this._blockedDone('', task)
          : `<ha-button class="done-btn" data-id="${escapeHTML(task.id)}">${escapeHTML(t('btn.done'))}</ha-button>`;
    // The row opens the task's detail page; "Done" stays as a quick action.
    return `
      <ha-card class="hk-card${overdue ? ' overdue' : ''}" data-id="${escapeHTML(task.id)}">
        <div class="hk-card-row">
          <div class="grow clickable detail-open" data-detail-kind="task" data-detail-id="${escapeHTML(task.id)}" role="button" tabindex="0">
            <div class="hk-name">${escapeHTML(task.name)}</div>
            <div class="hk-meta">${escapeHTML(recurrenceSummary(task))}${dueText}${overdueText}${n ? ` · ${escapeHTML(tn('history.count', n))}` : ''}</div>
            <div class="hk-chips">${statusChip}${dev}${tagChip}${taskChips}${managedChip}</div>
          </div>
          <div class="hk-card-actions">
            ${doneAction}
          </div>
        </div>
      </ha-card>`;
  }

  private _assetCard(x: Asset, depth = 0, isLast = false): string {
    const kindChip =
      x.kind === 'virtual'
        ? this._virtualDeviceChip(x)
        : x.device_id
          ? this._deviceChip(x.device_id)
          : `<ha-assist-chip label="${escapeHTML(deviceName(this._hass?.devices, x.device_id))}"></ha-assist-chip>`;
    const title =
      x.name || deviceName(this._hass?.devices, x.device_id) || t('appliance.fallbackName');
    const subCount = this._assets.filter((a) => a.parent_asset_id === x.id).length;
    const relCount = x.related_device_ids?.length ?? 0;
    const extra = [
      subCount
        ? `<ha-assist-chip label="${escapeHTML(tn('asset.subdevices', subCount))}"></ha-assist-chip>`
        : '',
      relCount
        ? `<ha-assist-chip label="${escapeHTML(tn('asset.related', relCount))}"></ha-assist-chip>`
        : '',
      x.parent_asset_id
        ? `<ha-assist-chip label="${escapeHTML(
            '↳ ' + this._assetAncestry(x.parent_asset_id),
          )}"></ha-assist-chip>`
        : '',
      x.archived_at
        ? `<ha-assist-chip class="hk-archived" label="${escapeHTML(t('chip.archived'))}"></ha-assist-chip>`
        : '',
    ].join('');
    const depthClass = depth > 0 ? ` hk-tree-child${isLast ? ' hk-tree-last' : ''}` : '';
    const depthStyle = depth > 0 ? ` style="--hk-tree-depth: ${depth}"` : '';
    return `
      <ha-card class="hk-card${depthClass}" data-id="${escapeHTML(x.id)}"${depthStyle}>
        <div class="hk-card-row">
          <div class="grow clickable detail-open" data-detail-kind="asset" data-detail-id="${escapeHTML(x.id)}" role="button" tabindex="0">
            <div class="hk-name">${escapeHTML(title)}</div>
            <div class="hk-meta">${escapeHTML(assetSummary(x, this._hass?.areas))}</div>
            <div class="hk-chips">${kindChip}${extra}</div>
          </div>
        </div>
      </ha-card>`;
  }

  private _assetName(assetId: string): string {
    return this._assets.find((a) => a.id === assetId)?.name || assetId;
  }

  private _assetAncestry(assetId: string): string {
    const path: string[] = [];
    const seen = new Set<string>();
    let cur: string | null = assetId;
    while (cur && !seen.has(cur)) {
      seen.add(cur);
      const a = this._assets.find((x) => x.id === cur);
      if (!a) break;
      path.unshift(a.name || cur);
      cur = a.parent_asset_id ?? null;
    }
    return path.join(' › ');
  }

  // ── detail page ─────────────────────────────────────────────────────────────
  private _detailView(): string {
    const d = this._detail;
    if (!d) return '';
    if (d.kind === 'task') {
      const task = this._tasks.find((x) => x.id === d.id);
      if (!task) return `<ha-alert alert-type="warning">${escapeHTML(t('detail.gone'))}</ha-alert>`;
      return this._taskDetail(task);
    }
    const asset = this._assets.find((x) => x.id === d.id);
    if (!asset) return `<ha-alert alert-type="warning">${escapeHTML(t('detail.gone'))}</ha-alert>`;
    return this._assetDetail(asset);
  }

  /** Render a URL as a clickable anchor that opens in the browser (new tab). A
   *  non-http(s) value is shown as inert text (no href) — defence-in-depth against a
   *  `javascript:` URI that escapeHTML can't neutralise in an href. */
  private _link(url: string): string {
    const safe = escapeHTML(url);
    const href = safeHref(url);
    return href
      ? `<a href="${href}" target="_blank" rel="noopener">${safe}</a>`
      : `<span>${safe}</span>`;
  }

  /** One label/value row, omitted entirely when the value is empty. */
  private _row(label: string, value?: string | null, isHtml = false): string {
    if (value == null || value === '') return '';
    return `<div class="hk-detail-row"><span class="k">${escapeHTML(label)}</span><span class="v">${
      isHtml ? value : escapeHTML(value)
    }</span></div>`;
  }

  /** A human-readable line for a sensor task's binding, with live progress when the
   *  bound entity's current value is known: usage shows "consumed / target (entity)";
   *  threshold shows "entity: current (cmp value)"; state shows "entity: current
   *  (= wanted)". Falls back to the binding alone when the reading is unavailable. */
  private _sensorProgress(task: Task): string {
    const s = task.sensor;
    if (!s) return '';
    const state = this._hass?.states?.[s.entity_id];
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
  private _sensorProgressBar(task: Task): string {
    const s = task.sensor;
    // Allowlist usage rather than excluding threshold: a mode added later must not
    // silently inherit the meter bar and render "0 of 0".
    if (!s || s.mode !== 'usage') return '';
    const parts: string[] = [];
    const state = this._hass?.states?.[s.entity_id];
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

  private _historySection(kind: 'task' | 'asset', id: string): string {
    const groups = this._completionGroupsFor(kind, id);
    return `
      <div class="hk-section">${escapeHTML(t('btn.history'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner hk-hist-body">${this._historyBody(
        groups,
      )}</div></ha-card>`;
  }

  private _taskDetail(task: Task): string {
    const overdue = isOverdue(task);
    const statusChip = overdue
      ? `<ha-assist-chip class="hk-overdue" label="${escapeHTML(t('chip.overdue'))}"></ha-assist-chip>`
      : `<ha-assist-chip label="${escapeHTML(dueLabel(task, undefined, this._hass))}"></ha-assist-chip>`;
    const dev = task.device_id ? this._deviceChip(task.device_id) : '';
    // The task's *effective* area — its own, else its device's — so the page explains
    // which "Group by → Area" section the task lands in. When it's inherited, the
    // device chip sits right beside it and shows where it came from.
    const areaChip = this._areaChip(task);
    const tagChip = this._tagChip(task);
    const managedChip = this._managedChip(task);
    const taskChips = this._taskChipsHtml(task);
    const mb = task.managed_by;

    // Source-owned tasks (reconciler-derived wear parts, synced problem sensors) are
    // managed by their source; the panel offers no edit/delete for them. A *manual*
    // consumable link (part.manual) is user-owned, so it stays editable/deletable.
    const sourceOwned =
      (Boolean(task.source?.part) && !task.source?.part?.manual) ||
      Boolean(task.source?.problem_sensor);
    const orphaned = this._isManagedOrphan(task);
    let manage = '';
    if (!sourceOwned) {
      const editBtn = `<ha-button class="d-edit">${escapeHTML(t('btn.edit'))}</ha-button>`;
      // Deletion protection only holds while the owner is present. Once orphaned
      // (owner uninstalled/disabled), the Delete button returns so the user can
      // clean the task up — otherwise "delete it from X instead" points nowhere.
      const deleteBtn =
        mb?.deletion_protected && !orphaned
          ? `<span class="hk-managed-info">${escapeHTML(t('managed.deleteBlocked', { name: mb.display_name }))}</span>`
          : `<ha-button destructive class="d-del">${escapeHTML(t('btn.delete'))}</ha-button>`;
      // "Edit in X" deep link when config_entry_id resolves to a loaded domain.
      const domain = mb?.config_entry_id ? this._entryDomains[mb.config_entry_id] : null;
      const openInBtn = domain && !orphaned
        ? `<ha-button class="d-open-in" data-domain="${escapeHTML(domain)}">${escapeHTML(t('btn.openInIntegration', { name: mb!.display_name }))}</ha-button>`
        : '';
      manage = `${editBtn}${deleteBtn}${openInBtn}`;
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
        ? t('form.task.completedOn', { date: new Date(task.last_completed as string).toLocaleString() })
        : task.next_due
          ? new Date(task.next_due).toLocaleString()
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
        ? this._blockedDone('d-done-blocked-wrap', task, true)
        : `<ha-button raised class="d-done">${escapeHTML(t('btn.done'))}</ha-button>`;
    // Notes get an inline editor right on the detail page: they're long-form prose
    // that renders as Markdown, so authoring deserves a full-width box with a live
    // preview rather than one cramped row among the schedule fields. (For a
    // problem-sensor task it's the *only* way in — its full edit dialog is
    // suppressed — and the note persists across the mirror being cleared, re-armed,
    // even deleted and recreated, so it's there next time the problem fires.) A note
    // its owning integration has locked stays read-only.
    const notesEditable = !(mb?.locked_fields ?? []).includes('notes');
    const notes = this._notesCardBody(
      { kind: 'task', id: task.id },
      task.notes || '',
      notesEditable,
      task.source?.problem_sensor ? t('note.placeholder') : t('note.placeholderMd'),
    );
    return `
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">
        <div class="hk-detail-title">${escapeHTML(task.name)}</div>
        <div class="hk-chips">${statusChip}${dev}${areaChip}${tagChip}${taskChips}${managedChip}</div>
        <div class="hk-detail-actions">
          ${doneBtn}
          ${manage}
        </div>
        ${completionHint}
      </div></ha-card>
      <div class="hk-section">${escapeHTML(t('detail.schedule'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">
        ${this._row(t('field.recurrence_type'), recurrenceSummary(task))}
        ${task.recurrence_type === 'sensor' ? this._row(t('field.sensor_entity_id'), this._sensorProgress(task)) : ''}
        ${task.recurrence_type === 'sensor' ? this._sensorProgressBar(task) : ''}
        ${this._row(t('detail.nextDue'), due)}
        ${this._row(t('field.consumable_link'), this._consumableLinkLabel(task), true)}
      </div></ha-card>
      <div class="hk-section">${escapeHTML(t('field.notes'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">${notes}</div></ha-card>
      ${this._historySection('task', task.id)}`;
  }

  /** Appliance notes — always present (even when empty) so the Edit affordance is
   *  discoverable, matching the task detail page. */
  private _assetNotesSection(asset: Asset): string {
    return this._notesSection({ kind: 'asset', id: asset.id }, asset.notes || '', true);
  }

  private _assetDetail(asset: Asset): string {
    const kindChip =
      asset.kind === 'virtual'
        ? this._virtualDeviceChip(asset)
        : asset.device_id
          ? this._deviceChip(asset.device_id)
          : '';
    const parentChip = asset.parent_asset_id
      ? `<ha-assist-chip label="${escapeHTML(
          '↳ ' + this._assetAncestry(asset.parent_asset_id),
        )}"></ha-assist-chip>`
      : '';
    const title =
      asset.name || deviceName(this._hass?.devices, asset.device_id) || t('appliance.fallbackName');
    const cost = asset.cost != null ? String(asset.cost) : '';
    // Structured (HA-wired) fields first, then the free-form metadata entries.
    const meta = (asset.metadata || [])
      .map((m) =>
        m.value
          ? this._row(m.label, m.type === 'link' ? this._link(m.value) : m.value, m.type === 'link')
          : '',
      )
      .join('');
    const details = [
      this._row(t('field.manufacturer'), asset.manufacturer),
      this._row(t('field.model'), asset.model),
      this._row(t('field.serial_number'), asset.serial_number),
      this._row(t('field.area_id'), areaName(this._hass?.areas, asset.area_id)),
      this._row(t('field.cost'), cost),
      meta,
    ].join('');
    const detailsCard = details
      ? `<div class="hk-section">${escapeHTML(t('detail.about'))}</div>
         <ha-card class="hk-detail-card"><div class="hk-detail-inner">${details}</div></ha-card>`
      : '';
    const archived = Boolean(asset.archived_at);
    const archiveOrRestoreBtn = archived
      ? `<ha-button class="d-restore">${escapeHTML(t('btn.restore'))}</ha-button>`
      : `<ha-button class="d-archive">${escapeHTML(t('btn.archive'))}</ha-button>`;
    const archivedNote = archived
      ? `<div class="hk-managed-prompt">${escapeHTML(
          t('detail.archivedOn', { date: new Date(asset.archived_at as string).toLocaleDateString() }),
        )}</div>`
      : '';
    return `
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">
        <div class="hk-detail-title">${escapeHTML(title)}</div>
        <div class="hk-chips">${kindChip}${parentChip}</div>
        ${archivedNote}
        <div class="hk-detail-actions">
          <ha-button raised class="d-edit">${escapeHTML(t('btn.edit'))}</ha-button>
          ${archiveOrRestoreBtn}
          <ha-button destructive class="d-del">${escapeHTML(t('btn.delete'))}</ha-button>
        </div>
      </div></ha-card>
      ${detailsCard}
      ${this._assetNotesSection(asset)}
      ${this._documentsSection(asset)}
      ${this._partsSection(asset)}
      ${this._relatedTasksSection(asset)}
      ${this._subdevicesSection(asset)}
      ${this._historySection('asset', asset.id)}`;
  }

  /** The appliance's documents (manuals/warranties/receipts). Both kinds render as a
   *  real anchor that opens in a new tab: an external link uses its own URL, an
   *  uploaded file a **pre-signed** one (`_signFiles` mints it and fills the `href` in;
   *  the `data-sign` key says which file the anchor points at). Never a JS-only handler
   *  — see the `documents.ts` header for why (issue #164). */
  private _documentsSection(asset: Asset): string {
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
          // anchor keeps `tabindex` + the JS fallback wired in `_wireDetailActions`.
          const key = signedFileKey({ kind: 'document', assetId: asset.id, id: d.id || '' });
          const href = this._signedFiles.getByKey(key);
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
          icon="${documentIcon(d)}"></ha-icon></span><span class="v">${inner}</span></div>`;
      })
      .join('');
    return `<div class="hk-section">${escapeHTML(t('section.documents'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">${rows}</div></ha-card>`;
  }

  private _partsSection(asset: Asset): string {
    const parts = asset.parts || [];
    if (!parts.length) return '';
    const chip = (label: string, cls = ''): string =>
      `<ha-assist-chip class="${cls}" label="${escapeHTML(label)}"></ha-assist-chip>`;
    const rows = parts
      .map((p) => {
        const isWear = p.type === 'wear';
        // Subtitle: the descriptive, identity bits (part number, vendor, cost).
        const sub: string[] = [];
        if (p.part_number) sub.push(p.part_number);
        if (p.vendor) sub.push(p.vendor);
        if (p.cost != null) sub.push(String(p.cost));
        const subLine = sub.length
          ? `<div class="hk-part-sub">${escapeHTML(sub.join(' · '))}</div>`
          : '';
        // Chips: the actionable status (cadence, last replaced, stock on hand).
        const chips: string[] = [];
        if (isWear && p.replace_interval && p.replace_unit) {
          chips.push(
            chip(
              t('part.every', {
                n: p.replace_interval,
                unit: t(`opt.unit.${p.replace_unit}`),
              }),
            ),
          );
        }
        if (isWear) {
          chips.push(
            chip(
              p.last_replaced
                ? t('part.replacedOn', { date: p.last_replaced })
                : t('part.neverReplaced'),
            ),
          );
        }
        const low = p.stock != null && p.reorder_at != null && p.stock <= p.reorder_at;
        if (p.stock != null) {
          // "In stock: 250 ml" — the unit rides with the number wherever stock is
          // shown, so a measured part never reads as a bare count of somethings.
          const onHand = formatQuantity(p.stock, p.stock_unit);
          chips.push(
            low
              ? chip(t('part.lowStock', { n: onHand }), 'hk-overdue')
              : chip(t('part.inStock', { n: onHand })),
          );
        }
        // What one completion takes off, when it isn't the plain single spare.
        if (p.stock != null && p.consume_quantity != null) {
          chips.push(
            chip(t('part.perUse', { n: formatQuantity(p.consume_quantity, p.stock_unit) })),
          );
        }
        const chipRow = chips.length ? `<div class="hk-part-chips">${chips.join('')}</div>` : '';
        const badge = `<span class="hk-part-badge">${escapeHTML(t(`opt.part.${p.type}`))}</span>`;
        const name = p.url
          ? `<a href="${safeHref(p.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(p.name)}</a>`
          : escapeHTML(p.name);
        // An attached file (receipt/spec sheet/photo) opens via a **pre-signed** URL
        // filled in by `_signFiles`, the same native-anchor pattern asset documents use.
        const fileKey = signedFileKey({ kind: 'part', assetId: asset.id, id: p.id || '' });
        const fileHref = this._signedFiles.getByKey(fileKey);
        const fileLink = p.file_name
          ? `<a class="hk-part-file" tabindex="0" data-sign="${escapeHTML(
              fileKey,
            )}" data-part="${escapeHTML(p.id || '')}"${
              fileHref ? ` href="${safeFileHref(fileHref)}"` : ''
            } target="_blank" rel="noopener noreferrer" title="${escapeHTML(
              p.file_name,
            )}"><ha-icon icon="mdi:paperclip" aria-hidden="true"></ha-icon></a>`
          : '';
        // A part's notes render as Markdown like every other note, but read-only:
        // parts are edited as a whole in the appliance's parts editor, so letting one
        // field be edited inline while its siblings aren't would be inconsistent.
        const partNotes = p.notes
          ? `<div class="hk-part-notes">${markdownBlock(p.notes, 'hk-md-compact')}</div>`
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
            </div>
          </div>`;
      })
      .join('');
    return `
      <div class="hk-section">${escapeHTML(t('section.parts'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner hk-parts">${rows}</div></ha-card>`;
  }

  /** Set the mdi `path` on each part-row icon (ha-svg-icon takes a property). */
  private _wirePartIcons(root: ShadowRoot): void {
    root.querySelectorAll<HTMLElement>('.hk-part-ic ha-svg-icon').forEach((el) => {
      (el as HTMLElement & { path?: string }).path =
        el.dataset.mdi === 'wear' ? MDI_WEAR : MDI_CONSUMABLE;
    });
  }

  private _relatedTasksSection(asset: Asset): string {
    const tasks = tasksForAsset(asset, this._tasks);
    if (!tasks.length) return '';
    const rows = tasks
      .map((task) => {
        const overdue = isOverdue(task);
        const chip = overdue
          ? `<ha-assist-chip class="hk-overdue" label="${escapeHTML(t('chip.overdue'))}"></ha-assist-chip>`
          : `<ha-assist-chip label="${escapeHTML(dueLabel(task, undefined, this._hass))}"></ha-assist-chip>`;
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

  private _subdevicesSection(asset: Asset): string {
    const subs = this._assets.filter((a) => a.parent_asset_id === asset.id);
    if (!subs.length) return '';
    const rows = subs
      .map((sub) => {
        const title =
          sub.name || deviceName(this._hass?.devices, sub.device_id) || t('appliance.fallbackName');
        return `
          <div class="hk-rel detail-open" data-detail-kind="asset" data-detail-id="${escapeHTML(
            sub.id,
          )}" role="button" tabindex="0">
            <div class="grow"><div class="hk-name">${escapeHTML(title)}</div>
              <div class="hk-meta">${escapeHTML(assetSummary(sub, this._hass?.areas))}</div></div>
          </div>`;
      })
      .join('');
    return `
      <div class="hk-section">${escapeHTML(tn('asset.subdevices', subs.length))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">${rows}</div></ha-card>`;
  }

  /**
   * Whether a managed task's owning integration is no longer loaded. A task is
   * orphaned when its `config_entry_id` is set but absent from the loaded-entry
   * set (uninstalled, disabled, or failing to set up). Without a recorded
   * `config_entry_id` we can't prove the owner is gone, so it isn't treated as
   * orphaned (the `force` service is the escape hatch for that edge case).
   */
  private _isManagedOrphan(task: Task): boolean {
    const id = task.managed_by?.config_entry_id;
    return Boolean(id) && !this._loadedEntryIds.has(id as string);
  }

  /** Renders integration-provided metadata chips (task_chips). Chips with a URL
   *  become native links; icon slot is populated when present. */
  private _taskChipsHtml(task: Task): string {
    return (task.task_chips ?? [])
      .map(({ label, icon, url }) => {
        const iconSlot = icon
          ? `<ha-icon slot="icon" icon="${escapeHTML(icon)}" class="hk-chip-ic"></ha-icon>`
          : '';
        const chip = `<ha-assist-chip label="${escapeHTML(label)}">${iconSlot}</ha-assist-chip>`;
        return isHttpUrl(url)
          ? `<a class="hk-task-chip-link" href="${safeHref(url)}" target="_blank" rel="noopener noreferrer">${chip}</a>`
          : chip;
      })
      .join('');
  }

  /**
   * A chip naming the task's effective area (its own, else its attached device's).
   * Empty when neither resolves to a real area — an unplaced task shows no chip
   * rather than an "Unassigned" one, matching how the device chip stays absent.
   */
  private _areaChip(task: Task): string {
    const name = areaName(this._hass?.areas, this._taskAreaId(task));
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
  private _tagChip(task: Task): string {
    if (!task.tag_id) return '';
    const locked = scanRequired(task);
    const iconName = locked ? 'mdi:lock' : 'mdi:nfc-variant';
    const tip = locked ? t('chip.scanLock.tip') : t('chip.nfc.tip');
    const label = tagName(this._tags, task.tag_id) || t('chip.nfc');
    const icon = `<ha-icon slot="icon" icon="${iconName}" class="hk-chip-ic"></ha-icon>`;
    return `<ha-assist-chip class="hk-tag" label="${escapeHTML(label)}" title="${escapeHTML(tip)}">${icon}</ha-assist-chip>`;
  }

  /** Renders a "Managed by X" chip (or "Integration offline" if orphaned). */
  private _managedChip(task: Task): string {
    const mb = task.managed_by;
    if (!mb) return '';
    if (this._isManagedOrphan(task)) {
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
  private _deviceChip(deviceId: string): string {
    const name = deviceName(this._hass?.devices, deviceId);
    const domain = deviceDomain(this._hass?.devices?.[deviceId], this._entryDomains);
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
  private _virtualDeviceChip(asset: Asset): string {
    const deviceId = asset.device_id;
    const label = escapeHTML(t('chip.virtualDevice'));
    const tip = escapeHTML(t('chip.virtualDevice.tip'));
    if (deviceId && this._hass?.devices?.[deviceId]) {
      return `<ha-assist-chip class="hk-device-chip" role="link" tabindex="0" data-device-id="${escapeHTML(
        deviceId,
      )}" label="${label}" title="${tip}"><ha-icon slot="icon" icon="mdi:open-in-new" class="hk-chip-ic"></ha-icon></ha-assist-chip>`;
    }
    return `<ha-assist-chip label="${label}" title="${tip}"></ha-assist-chip>`;
  }

  private _navigateToDevice(deviceId: string): void {
    history.pushState(null, '', `/config/devices/device/${deviceId}`);
    window.dispatchEvent(
      new CustomEvent('location-changed', {
        detail: { replace: false },
        bubbles: true,
        composed: true,
      }),
    );
  }

  /** Wire navigation + brand-logo fallback for every device chip in the tree. */
  private _wireDeviceChips(root: ShadowRoot): void {
    root.querySelectorAll<HTMLElement>('.hk-device-chip').forEach((chip) => {
      const id = chip.dataset.deviceId;
      // Stop the event from bubbling to an enclosing `.detail-open` card row — without
      // this, clicking a device chip on a task/appliance card row is hijacked by the
      // row's open-detail handler and the chip never reaches its device page.
      const go = (e?: Event): void => {
        e?.stopPropagation();
        if (id) this._navigateToDevice(id);
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

  // ── ha-form schemas ─────────────────────────────────────────────────────────
  // The task form schema/data/payload helpers are shared with the dashboard card
  // (see `forms.ts`). Asset/part schemas below stay panel-only.

  private _eligibleParents(x: Partial<Asset>): { value: string; label: string }[] {
    const banned = new Set<string>();
    if (x.id) {
      banned.add(x.id);
      const childrenOf = (pid: string): void => {
        for (const a of this._assets) {
          if (a.parent_asset_id === pid && !banned.has(a.id)) {
            banned.add(a.id);
            childrenOf(a.id);
          }
        }
      };
      childrenOf(x.id);
    }
    return this._assets
      .filter((a) => a.kind === 'virtual' && !banned.has(a.id))
      .map((a) => ({ value: a.id, label: a.name }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }

  /**
   * Identity schema (kind + virtual/existing fields + area). The `kind` field is
   * omitted once the asset exists (it's immutable after creation, and ha-form
   * has no per-field disable), so editing can't put it in an inconsistent state.
   */
  private _assetIdentitySchema(x: Partial<Asset>, editing: boolean): FormField[] {
    const fields: FormField[] = [];
    if (!editing) {
      fields.push({
        name: 'kind',
        selector: selSelect([
          { value: 'virtual', label: t('opt.kind.virtual') },
          { value: 'existing', label: t('opt.kind.existing') },
        ]),
      });
    }
    const existing = x.kind === 'existing';
    if (existing) fields.push({ name: 'device_id', required: true, selector: selDevice() });
    // The device supplies its own name for an existing-device asset (normalize_fields
    // falls back to it), so it's optional there; a virtual asset owns no other name
    // source, so it's required.
    fields.push({ name: 'name', required: !existing, selector: selText() });
    fields.push({
      name: '',
      type: 'grid',
      schema: [
        { name: 'manufacturer', selector: selText() },
        { name: 'model', selector: selText() },
      ],
    });
    // serial_number is first-class (it syncs into the device page's info block), so
    // it sits with make/model rather than in the free-form custom fields.
    fields.push({ name: 'serial_number', selector: selText() });
    if (existing) {
      // Only a device we own can be a native subdevice of another via via_device
      // (normalize_fields forces an existing-device asset's parent_asset_id to None),
      // so there's no parent picker here — just the icon.
      fields.push({ name: 'icon', selector: selIcon() });
    } else {
      fields.push({
        name: '',
        type: 'grid',
        schema: [
          { name: 'icon', selector: selIcon() },
          { name: 'parent_asset_id', selector: selSelect(this._eligibleParents(x)) },
        ],
      });
    }
    fields.push({ name: 'area_id', selector: selArea() });
    return fields;
  }

  /** Manufacturer/model/serial_number to prefill from a linked HA device, skipping
   *  any field already set on the asset — this only fills gaps, never overwrites a
   *  value the user typed (or one already saved from a previous edit). */
  private _deviceDefaults(
    deviceId: string,
    prev: Partial<Asset> | null,
  ): Record<string, string> | undefined {
    const dev = this._hass?.devices?.[deviceId];
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

  /** Structured field that wires into HA: the asset's value (for the inventory). */
  private _structuredDetailsSchema(): FormField[] {
    return [{ name: 'cost', selector: selNumber(0) }];
  }

  /** Schema for one free-form metadata entry. The value control swaps by type, and
   *  a `date` entry adds a "track as sensor" toggle (opt-in automation). */
  private _metadataSchema(m: MetadataEntry): FormField[] {
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

  private _partSchema(p: Part): FormField[] {
    const isWear = p.type === 'wear';
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
    if (p.stock != null) {
      base.push({ name: 'consume_quantity', selector: selNumber(MIN_POSITIVE_QUANTITY, 'any') });
    }
    // Auto-buy: only meaningful once a reorder threshold is set (that's what defines
    // "low"). When enabled, offer the restock quantity added on completing the reminder.
    if (p.reorder_at != null) {
      base.push({ name: 'create_buy_task', selector: selBool() });
      if (p.create_buy_task) {
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
          {
            name: 'replace_unit',
            selector: selSelect([
              { value: 'days', label: t('opt.unit.days') },
              { value: 'weeks', label: t('opt.unit.weeks') },
              { value: 'months', label: t('opt.unit.months') },
            ]),
          },
        ],
      });
      // Let the user record when the part was last replaced so the derived
      // maintenance task's clock starts from the real date instead of "now".
      base.push({ name: 'last_replaced', selector: selDate() });
    }
    return base;
  }

  // ── hydration: build/configure live HA components ───────────────────────────
  private _hydrate(): void {
    const root = this.shadowRoot;
    if (!root) return;

    // `markdownBlock` carries its text in `data-md`; `content` is a property, so it
    // has to be assigned after the markup lands in the DOM.
    wireMarkdown(root);

    // Mint/refresh the signed URLs for any uploaded file this render put on screen and
    // fill them into their anchors. Async, but it lands within a round-trip — long
    // before a user can reach for a link — and the anchors carry a JS fallback until
    // it does.
    void this._signFiles();

    // The completion-details dialog overlays any view, so build it first.
    const dialogHost = root.getElementById('hk-dialog-host');
    if (dialogHost && this._completion.open) this._renderCompletionDialog(dialogHost);
    if (dialogHost && this._moveCompletion.open) this._renderMoveCompletionDialog(dialogHost);
    // _renderConfirmDeleteDialog appends directly to document.body (not shadow root).

    // Header sidebar toggle.
    const menuHost = root.getElementById('menu-host');
    if (menuHost) {
      const mb = document.createElement('ha-menu-button') as HTMLElement & {
        hass?: Hass;
        narrow?: boolean;
      };
      mb.hass = this._hass;
      mb.narrow = this.narrow;
      this._liveHassEls.push(mb);
      menuHost.appendChild(mb);
    }

    // Load-error retry (shown instead of the infinite spinner on a startup failure).
    root.getElementById('hk-retry')?.addEventListener('click', () => {
      this._loadError = false;
      this._render();
      void this._refresh();
    });

    // Detail page: just the back button, the detail's own action buttons, and
    // any device chips / completion-delete buttons it renders.
    if (this._detail) {
      root.getElementById('back-btn')?.addEventListener('click', () => this._closeDetail());
      this._wireDetailActions(root);
      this._wireDetailOpeners(root);
      this._wireDeviceChips(root);
      this._wirePartIcons(root);
      this._wireHistoryDeletes(root);
      return;
    }

    // Tab navigation. Listen on each tab (click) and on the group's shoelace
    // `sl-tab-show` event (whichever fires) — both funnel through _switchView,
    // which is a no-op when the view is unchanged.
    root.getElementById('tab-tasks')?.addEventListener('click', () => this._switchView('tasks'));
    root
      .getElementById('tab-appliances')
      ?.addEventListener('click', () => this._switchView('appliances'));
    root
      .getElementById('tab-settings')
      ?.addEventListener('click', () => this._switchView('settings'));
    root.querySelector('ha-tab-group')?.addEventListener('sl-tab-show', (e: Event) => {
      const name = (e as CustomEvent<{ name?: string }>).detail?.name;
      if (name === 'tasks' || name === 'appliances' || name === 'settings') this._switchView(name);
    });

    root.getElementById('add-btn')?.addEventListener('click', () => {
      if (this._view === 'tasks') this._openCreate();
      else this._openCreateAsset();
    });

    root.getElementById('export-btn')?.addEventListener('click', () => this._exportInventory());

    root
      .getElementById('cleanup-orphans-btn')
      ?.addEventListener('click', () => void this._cleanupOrphans());

    // Filter / group-by segmented controls.
    root.querySelectorAll<HTMLElement>('.hk-seg-btn').forEach((b) =>
      b.addEventListener('click', () => {
        const seg = (b.closest('.hk-seg') as HTMLElement | null)?.dataset.seg;
        const val = b.dataset.segVal;
        if (!val) return;
        if (seg === 'group') this._setGroupBy(val as GroupBy);
        else if (seg === 'filter') this._setFilter(val as TaskFilter);
        else if (seg === 'assetFilter') this._setAssetFilter(val as AssetFilter);
        else if (seg === 'assetView') this._setAssetView(val as AssetView);
      }),
    );
    // Saved-Profile filter dropdown.
    root
      .querySelector<HTMLSelectElement>('select[data-profile-filter]')
      ?.addEventListener('change', (e) =>
        this._setProfile((e.target as HTMLSelectElement).value),
      );
    // Remember which group sections the user collapsed (no re-render needed).
    root.querySelectorAll<HTMLDetailsElement>('details.hk-group').forEach((d) =>
      d.addEventListener('toggle', () => {
        const key = d.dataset.groupKey || '';
        if (d.open) this._collapsed.delete(key);
        else this._collapsed.add(key);
      }),
    );
    // Tree view: expand/collapse parent groups.
    root.querySelectorAll<HTMLElement>('.hk-chevron[data-tree-toggle]').forEach((ch) =>
      ch.addEventListener('click', (e) => {
        e.stopPropagation();
        const group = ch.closest('.hk-tree-group');
        if (group) group.classList.toggle('hk-tree-open');
        const id = ch.dataset.treeToggle;
        if (id) {
          if (this._treeCollapsed.has(id)) this._treeCollapsed.delete(id);
          else this._treeCollapsed.add(id);
          try { localStorage.setItem(LS_TREE_COLLAPSED, JSON.stringify([...this._treeCollapsed])); } catch { /* quota */ }
        }
      }),
    );

    // Forms.
    const host = root.getElementById('hk-form-host');
    if (host) {
      if (this._view === 'tasks' && this._edit.open) this._renderTaskForm(host);
      else if (this._view === 'appliances' && this._assetEdit.open) this._renderAssetForm(host);
    }
    const settingsHost = root.getElementById('hk-settings-host');
    if (settingsHost) this._renderSettingsForm(settingsHost);
    const profilesHost = root.getElementById('hk-profiles-host');
    if (profilesHost) this._renderProfiles(profilesHost);
    const notificationsHost = root.getElementById('hk-notifications-host');
    if (notificationsHost) this._renderNotifications(notificationsHost);
    const companionsHost = root.getElementById('hk-companions-host');
    if (companionsHost) this._renderCompanions(companionsHost);

    // Card actions: the row opens the detail page; tasks keep a quick "Done".
    this._wireDetailOpeners(root);
    if (this._view === 'tasks') {
      root.querySelectorAll<HTMLElement>('.done-btn').forEach((b) =>
        b.addEventListener('click', () => {
          const task = this._tasks.find((x) => x.id === b.dataset.id);
          if (task) void this._complete(task);
        }),
      );
      root.querySelectorAll<HTMLElement>('.hk-intro-dismiss').forEach((b) =>
        b.addEventListener('click', () => {
          this._introDismissed = true;
          this._render();
          if (this._hass) {
            void api.setIntroDismissed(this._hass).catch(() => {
              // best-effort — if this fails the banner simply reappears next load.
            });
          }
        }),
      );
    }
    // A completion-blocked Done (card row or detail) explains why on click rather
    // than completing — its source clears it.
    root.querySelectorAll<HTMLElement>('.done-blocked-wrap').forEach((b) =>
      b.addEventListener('click', () => {
        const task = this._tasks.find((x) => x.id === b.dataset.id);
        if (task) this._notifyBlocked(task);
      }),
    );
    this._wireDeviceChips(root);
  }

  /** Wire every `.detail-open` row to open its object's detail page. */
  private _wireDetailOpeners(root: ShadowRoot): void {
    root.querySelectorAll<HTMLElement>('.detail-open').forEach((el) => {
      const go = (): void => {
        const kind = el.dataset.detailKind;
        const id = el.dataset.detailId;
        if ((kind === 'task' || kind === 'asset') && id) this._openDetail(kind, id);
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
  private _wireDetailActions(root: ShadowRoot): void {
    const d = this._detail;
    if (!d) return;
    // `destructive` alone doesn't reflect into ha-button's Web Awesome variant when
    // set as static markup (only when applied to an already-upgraded element), so
    // force the red "danger" variant here rather than in the template string.
    root.querySelector('.d-del')?.setAttribute('variant', 'danger');
    if (d.kind === 'task') {
      const task = this._tasks.find((x) => x.id === d.id);
      if (!task) return;
      root.querySelector('.d-done')?.addEventListener('click', () => void this._complete(task));
      root
        .querySelector('.d-done-blocked-wrap')
        ?.addEventListener('click', () => this._notifyBlocked(task));
      root.querySelector('.d-edit')?.addEventListener('click', () => this._openEdit(task));
      this._wireNoteEditor(root, { kind: 'task', id: task.id });
      root.querySelector('.d-del')?.addEventListener('click', () => {
        this._openConfirmDialog(t('confirm.deleteTask', { name: task.name }), () => {
          // The detail is about to vanish: replace it with its list so Forward
          // can't return to a deleted task.
          this._navigate({ view: 'tasks', detail: null }, true);
          void this._delete(task);
        });
      });
      // "Edit in X" deep link: navigate to the managing integration's config page
      // (same helper the Companions "Configure" button uses).
      root.querySelectorAll<HTMLElement>('.d-open-in').forEach((btn) => {
        btn.addEventListener('click', () => {
          const domain = btn.dataset.domain;
          if (domain) this._navigateToIntegration(domain);
        });
      });
      return;
    }
    const asset = this._assets.find((x) => x.id === d.id);
    if (!asset) return;
    root.querySelector('.d-edit')?.addEventListener('click', () => this._openEditAsset(asset));
    this._wireNoteEditor(root, { kind: 'asset', id: asset.id });
    root.querySelector('.d-archive')?.addEventListener('click', () => void this._archiveAsset(asset));
    root.querySelector('.d-restore')?.addEventListener('click', () => void this._restoreAsset(asset));
    root.querySelector('.d-del')?.addEventListener('click', () => {
      const name =
        asset.name || deviceName(this._hass?.devices, asset.device_id) || t('appliance.fallbackName');
      this._openConfirmDialog(t('confirm.deleteAsset', { name }), () => {
        // The detail is about to vanish: replace it with its list so Forward
        // can't return to a deleted appliance.
        this._navigate({ view: 'appliances', detail: null }, true);
        void this._deleteAsset(asset);
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
        const doc = asset.documents?.find((d) => d.id === el.dataset.doc);
        if (doc && this._hass) void openDocument(this._hass, asset.id, doc);
      });
    });
    root.querySelectorAll<HTMLElement>('a.hk-part-file[data-part]').forEach((el) => {
      fallback(el, () => {
        const part = asset.parts?.find((p) => p.id === el.dataset.part);
        if (part && this._hass) void openPartFile(this._hass, asset.id, part);
      });
    });
  }

  /**
   * Mint the signed URLs for every uploaded file the current screen shows and fill them
   * into the anchors that are waiting for one (`data-sign` carries the cache key).
   *
   * The single signing chokepoint for the panel, run after every render: a file must be
   * openable by a *native* anchor tap, because a `window.open` issued after the async
   * sign is swallowed by the iOS app's WKWebView (issue #164). Because `ensure` also
   * evicts what isn't passed, this collects the whole set the panel currently renders —
   * the appliance detail page or the appliance edit form, which are never both up.
   */
  private async _signFiles(): Promise<void> {
    const hass = this._hass;
    if (!hass) return;
    const detailAsset =
      this._detail?.kind === 'asset'
        ? this._assets.find((a) => a.id === this._detail?.id)
        : undefined;
    const refs = [
      ...assetFileRefs(detailAsset ?? {}),
      ...assetFileRefs(this._assetEdit.asset ?? {}),
    ];
    // A screen with no uploaded files still calls through, so the cache drops the URLs
    // of whatever was on the previous one.
    await this._signedFiles.ensure(hass, refs);
    this._applySignedHrefs();
    this._armResign(refs.length > 0);
  }

  /**
   * Keep a long-lived screen's hrefs valid. Unlike the dashboard card — which re-signs
   * on every data refresh — the panel only renders on navigation and data changes, so
   * an appliance page left open (a wall tablet, a forgotten tab) would sail past the
   * backend's 1h URL TTL and every document link would 403 on click. A single timer
   * re-runs the signing pass on the same clock the cache re-mints on, updating the live
   * anchors in place. Disarmed as soon as the screen has no files, and on unmount.
   */
  private _armResign(needed: boolean): void {
    if (this._resignTimer) {
      clearTimeout(this._resignTimer);
      this._resignTimer = null;
    }
    if (!needed) return;
    this._resignTimer = setTimeout(() => {
      this._resignTimer = null;
      void this._signFiles();
    }, SIGNED_URL_REFRESH_MS);
  }

  /** Point every `data-sign` anchor at its freshly-minted URL. Anchors are matched by
   *  cache key, so this is safe to run against whatever the DOM currently holds (a
   *  re-render mid-sign just means the new nodes get the hrefs). */
  private _applySignedHrefs(): void {
    const root = this.shadowRoot;
    if (!root) return;
    root.querySelectorAll<HTMLAnchorElement>('a[data-sign]').forEach((el) => {
      const url = this._signedFiles.getByKey(el.dataset.sign || '');
      if (url && el.getAttribute('href') !== url) el.setAttribute('href', url);
    });
  }

  private _switchView(view: 'tasks' | 'appliances' | 'settings'): void {
    if (this._view === view) return;
    // Switching tabs is a lateral move, not a drill-in: replace so Back doesn't
    // retrace every tab toggle.
    this._navigate({ view, detail: null }, true);
  }

  /** Render the Settings tab — `ha-form` mirrors of the options flow that autosave
   *  each change (the backend reloads + re-runs the problem sync). Three cards: a
   *  **General** card for settings (like one-off retention) that aren't tied to any
   *  single feature, the **Shopping list** mirror, and problem-sensor sync. The two
   *  feature cards each carry a paragraph, because both do something to the user's
   *  data they should read about before switching it on. */
  private _renderSettingsForm(host: HTMLElement): void {
    const opts: HomeKeeperOptions = this._options ?? {
      sync_problem_sensors: false,
      problem_sensor_exclude_entities: [],
      problem_sensor_exclude_devices: [],
      problem_sensor_exclude_areas: [],
      problem_sensor_exclude_labels: [],
      one_off_retention_days: 0,
      shopping_list_entity: '',
      profiles: [],
      notifications: [],
    };
    // General — settings independent of any single feature (e.g. one-off retention).
    host.appendChild(
      this._settingsCard(
        'hk-settings-general',
        'settings.general_heading',
        'settings.general_help',
        generalSchema(),
        opts,
      ),
    );
    // Shopping list — where auto-buy reminders are mirrored.
    host.appendChild(
      this._settingsCard(
        'hk-settings-shopping',
        'settings.shopping_heading',
        'settings.shopping_help',
        shoppingSchema(this._ownTodoEntities),
        opts,
        // Clearing an entity picker emits `undefined`, which JSON drops on the way
        // to the backend — so the key never reaches the partial-update merge and
        // "turn the mirror off" silently wouldn't stick. Send the empty string the
        // backend reads as off. (The other settings are multi-selects, which emit
        // `[]`, which is why nothing has needed this before.)
        (value) => ({ ...value, shopping_list_entity: String(value.shopping_list_entity ?? '') }),
      ),
    );
    // Problem-sensor sync. Keeps id `hk-settings` (deep-link/e2e/test anchor).
    host.appendChild(
      this._settingsCard('hk-settings', 'settings.heading', 'settings.help', problemSyncSchema(), opts),
    );
  }

  /** Build one autosaving Settings card: a titled `ha-card` wrapping an `ha-form`
   *  for *schema*, seeded with the full *opts* and saving on change. *coerce*, when
   *  given, cleans the emitted value before it is saved. */
  private _settingsCard(
    id: string,
    headingKey: string,
    helpKey: string,
    schema: FormField[],
    opts: HomeKeeperOptions,
    coerce?: (value: Record<string, unknown>) => Record<string, unknown>,
  ): HTMLElement {
    const card = document.createElement('ha-card');
    card.className = 'hk-form-card';
    card.id = id;
    const inner = document.createElement('div');
    inner.className = 'hk-form-inner';
    inner.innerHTML = `
      <div class="hk-form-title">${escapeHTML(t(headingKey))}</div>
      <div class="hk-settings-intro">${escapeHTML(t(helpKey))}</div>`;
    const form = document.createElement('ha-form') as HaFormElement;
    form.hass = this._hass;
    form.schema = schema;
    form.data = { ...opts };
    form.computeLabel = (s: { name: string }): string => (s.name ? t('settings.' + s.name) : '');
    form.addEventListener('value-changed', (e: Event) => {
      const raw = (e as CustomEvent<{ value: Record<string, unknown> }>).detail.value;
      const value = coerce ? coerce(raw) : raw;
      void this._saveOptions(value as Partial<HomeKeeperOptions>);
    });
    this._liveHassEls.push(form);
    inner.appendChild(form);
    card.appendChild(inner);
    return card;
  }

  private async _saveOptions(value: Partial<HomeKeeperOptions>): Promise<void> {
    if (!this._hass) return;
    // Keep local state in sync optimistically so the form doesn't flicker; the
    // backend persists, reloads the entry and re-runs the problem-sensor sync.
    this._options = { ...(this._options as HomeKeeperOptions), ...value };
    try {
      await api.setOptions(this._hass, value);
      // setOptions resolves only once the backend has reloaded and reconciled the
      // synced problem-sensor tasks for the new exclusions. Refresh our cached
      // tasks (without re-rendering — that would tear down the form the user is
      // still editing) so the change is reflected the moment they return to the
      // Tasks tab, rather than lingering until the next refresh.
      await this._reload();
      this._toast(t('settings.saved'));
    } catch (err) {
      this._toast(String((err as { message?: string })?.message || err));
    }
  }

  /** Render the Settings → Profiles card: reusable saved filters (status +
   *  labels/areas/devices), each an autosaving `ha-form`. Profiles are consumed by
   *  notifications, the admin task list, and the dashboard card. */
  private _renderProfiles(host: HTMLElement): void {
    const profiles = this._options?.profiles ?? [];
    const isCollapsed = this._settingsSectionCollapsed.has('profiles');

    const card = document.createElement('ha-card');
    card.className = 'hk-form-card';
    card.id = 'hk-profiles';
    const inner = document.createElement('div');
    inner.className = 'hk-form-inner';

    // Clickable header (always visible)
    const header = document.createElement('button');
    header.className = 'hk-section-header';
    header.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
    header.innerHTML = `
      <span class="hk-form-title hk-section-title">${escapeHTML(t('notify.profiles_heading'))}</span>
      ${profiles.length ? `<span class="hk-section-count">${profiles.length}</span>` : ''}
      <ha-icon icon="mdi:chevron-down" class="hk-section-chevron${isCollapsed ? '' : ' open'}"></ha-icon>`;
    inner.appendChild(header);

    // Collapsible body
    const body = document.createElement('div');
    if (isCollapsed) body.style.display = 'none';
    const intro = document.createElement('div');
    intro.className = 'hk-settings-intro';
    intro.textContent = t('notify.profiles_help');
    body.appendChild(intro);
    if (!profiles.length) {
      const alert = document.createElement('ha-alert');
      alert.setAttribute('alert-type', 'info');
      alert.textContent = t('notify.profiles_empty');
      body.appendChild(alert);
    }
    for (const profile of profiles) body.appendChild(this._profileEditor(profile));
    const add = document.createElement('ha-button');
    add.id = 'hk-profile-add';
    add.className = 'hk-notify-add';
    add.textContent = t('notify.add_profile');
    add.addEventListener('click', () => void this._addProfile());
    body.appendChild(add);
    inner.appendChild(body);
    card.appendChild(inner);

    header.addEventListener('click', () => {
      const collapsed = this._settingsSectionCollapsed.has('profiles');
      const chevron = header.querySelector<HTMLElement>('.hk-section-chevron');
      if (collapsed) {
        this._settingsSectionCollapsed.delete('profiles');
        body.style.display = '';
        header.setAttribute('aria-expanded', 'true');
        chevron?.classList.add('open');
      } else {
        this._settingsSectionCollapsed.add('profiles');
        body.style.display = 'none';
        header.setAttribute('aria-expanded', 'false');
        chevron?.classList.remove('open');
      }
    });

    host.appendChild(card);
  }

  private _profileEditor(profile: Profile): HTMLElement {
    const isExpanded = this._itemExpanded.has(profile.id);

    const card = document.createElement('div');
    card.className = 'hk-item-card';

    // Clickable header showing the profile name
    const header = document.createElement('button');
    header.className = 'hk-item-header';
    header.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
    const nameSpan = document.createElement('span');
    nameSpan.className = 'hk-item-name';
    nameSpan.textContent = profile.name;
    header.appendChild(nameSpan);
    const chevron = document.createElement('ha-icon');
    (chevron as unknown as Record<string, string>).icon = 'mdi:chevron-down';
    chevron.className = 'hk-section-chevron' + (isExpanded ? ' open' : '');
    header.appendChild(chevron);
    card.appendChild(header);

    // Collapsible body
    const body = document.createElement('div');
    body.className = 'hk-item-body';
    if (!isExpanded) body.style.display = 'none';

    const form = document.createElement('ha-form') as HaFormElement;
    form.hass = this._hass;
    form.schema = profileSchema();
    form.data = profileFormData(profile);
    form.computeLabel = (s: { name: string }): string => {
      if (s.name === 'name') return t('field.name');
      if (s.name === 'labels') return t('field.labels');
      return t('notify.' + s.name);
    };
    form.addEventListener('value-changed', (e: Event) => {
      const value = (e as CustomEvent<{ value: Record<string, unknown> }>).detail.value;
      if (typeof value.name === 'string') nameSpan.textContent = value.name;
      const next = (this._options?.profiles ?? []).map((p) =>
        p.id === profile.id ? profileFormToProfile(profile.id, value) : p,
      );
      this._debounce('profiles', () => void this._persistProfiles(next, false));
    });
    this._liveHassEls.push(form);
    body.appendChild(form);

    const del = document.createElement('ha-button');
    del.className = 'hk-notify-delete';
    del.textContent = t('notify.delete');
    del.addEventListener('click', () => void this._deleteProfile(profile.id));
    body.appendChild(del);
    card.appendChild(body);

    header.addEventListener('click', () => {
      const expanded = this._itemExpanded.has(profile.id);
      const chev = header.querySelector<HTMLElement>('.hk-section-chevron');
      if (expanded) {
        this._itemExpanded.delete(profile.id);
        body.style.display = 'none';
        header.setAttribute('aria-expanded', 'false');
        chev?.classList.remove('open');
      } else {
        this._itemExpanded.add(profile.id);
        body.style.display = '';
        header.setAttribute('aria-expanded', 'true');
        chev?.classList.add('open');
      }
    });

    return card;
  }

  private _addProfile(): Promise<void> {
    const blank: Profile = {
      id: '',
      name: t('notify.new_profile'),
      filter: {
        status: 'overdue',
        labels: [],
        areas: [],
        devices: [],
        exclude_labels: [],
        exclude_areas: [],
        exclude_devices: [],
      },
    };
    return this._persistProfiles([...(this._options?.profiles ?? []), blank], true, true);
  }

  private _deleteProfile(id: string): Promise<void> {
    this._itemExpanded.delete(id);
    const next = (this._options?.profiles ?? []).filter((p) => p.id !== id);
    return this._persistProfiles(next, true);
  }

  private async _persistProfiles(
    profiles: Profile[],
    render: boolean,
    expandLast = false,
  ): Promise<void> {
    if (!this._hass) return;
    this._options = { ...(this._options as HomeKeeperOptions), profiles };
    try {
      this._options = await api.setOptions(this._hass, {
        profiles,
      } as Partial<HomeKeeperOptions>);
      if (expandLast) {
        const saved = this._options?.profiles ?? [];
        if (saved.length) this._itemExpanded.add(saved[saved.length - 1].id);
      }
      if (render) this._render();
      this._toast(t('settings.saved'));
    } catch (err) {
      this._toast(String((err as { message?: string })?.message || err));
    }
  }

  /** Render the Settings → Notifications card: delivery bindings that each reference
   *  a profile and add targets/buttons/style — see the backend `notifier.py`. */
  private _renderNotifications(host: HTMLElement): void {
    const profiles = this._options?.profiles ?? [];
    const notifications = this._options?.notifications ?? [];
    const isCollapsed = this._settingsSectionCollapsed.has('notifications');

    const card = document.createElement('ha-card');
    card.className = 'hk-form-card';
    card.id = 'hk-notifications';
    const inner = document.createElement('div');
    inner.className = 'hk-form-inner';

    // Clickable header (always visible)
    const header = document.createElement('button');
    header.className = 'hk-section-header';
    header.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
    header.innerHTML = `
      <span class="hk-form-title hk-section-title">${escapeHTML(t('notify.heading'))}</span>
      ${notifications.length ? `<span class="hk-section-count">${notifications.length}</span>` : ''}
      <ha-icon icon="mdi:chevron-down" class="hk-section-chevron${isCollapsed ? '' : ' open'}"></ha-icon>`;
    inner.appendChild(header);

    // Collapsible body
    const body = document.createElement('div');
    if (isCollapsed) body.style.display = 'none';
    const intro = document.createElement('div');
    intro.className = 'hk-settings-intro';
    intro.textContent = t('notify.help');
    body.appendChild(intro);
    if (!this._notifyTargets.length) {
      const alert = document.createElement('ha-alert');
      alert.setAttribute('alert-type', 'info');
      alert.textContent = t('notify.no_targets');
      body.appendChild(alert);
    }
    if (!profiles.length) {
      const alert = document.createElement('ha-alert');
      alert.setAttribute('alert-type', 'info');
      alert.textContent = t('notify.need_profile');
      body.appendChild(alert);
    }
    if (!notifications.length) {
      const alert = document.createElement('ha-alert');
      alert.setAttribute('alert-type', 'info');
      alert.textContent = t('notify.empty');
      body.appendChild(alert);
    }
    for (const notification of notifications) {
      body.appendChild(this._notificationEditor(notification, profiles));
    }
    const add = document.createElement('ha-button');
    add.id = 'hk-notify-add';
    add.className = 'hk-notify-add';
    add.textContent = t('notify.add');
    if (!profiles.length) add.setAttribute('disabled', '');
    add.addEventListener('click', () => void this._addNotification());
    body.appendChild(add);
    inner.appendChild(body);
    card.appendChild(inner);

    header.addEventListener('click', () => {
      const collapsed = this._settingsSectionCollapsed.has('notifications');
      const chevron = header.querySelector<HTMLElement>('.hk-section-chevron');
      if (collapsed) {
        this._settingsSectionCollapsed.delete('notifications');
        body.style.display = '';
        header.setAttribute('aria-expanded', 'true');
        chevron?.classList.add('open');
      } else {
        this._settingsSectionCollapsed.add('notifications');
        body.style.display = 'none';
        header.setAttribute('aria-expanded', 'false');
        chevron?.classList.remove('open');
      }
    });

    host.appendChild(card);
  }

  private _notificationEditor(notification: Notification, profiles: Profile[]): HTMLElement {
    const isExpanded = this._itemExpanded.has(notification.id);

    const card = document.createElement('div');
    card.className = 'hk-item-card';

    // Clickable header showing the notification name
    const header = document.createElement('button');
    header.className = 'hk-item-header';
    header.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
    const nameSpan = document.createElement('span');
    nameSpan.className = 'hk-item-name';
    nameSpan.textContent = notification.name;
    header.appendChild(nameSpan);
    const chevron = document.createElement('ha-icon');
    (chevron as unknown as Record<string, string>).icon = 'mdi:chevron-down';
    chevron.className = 'hk-section-chevron' + (isExpanded ? ' open' : '');
    header.appendChild(chevron);
    card.appendChild(header);

    // Collapsible body
    const body = document.createElement('div');
    body.className = 'hk-item-body';
    if (!isExpanded) body.style.display = 'none';

    const form = document.createElement('ha-form') as HaFormElement;
    form.hass = this._hass;
    form.schema = notificationSchema(this._notifyTargets, profiles);
    form.data = notifyFormData(notification);
    form.computeLabel = (s: { name: string }): string => {
      if (s.name === 'name') return t('field.name');
      if (s.name === 'profile_id') return t('notify.profile');
      return t('notify.' + s.name);
    };
    form.addEventListener('value-changed', (e: Event) => {
      const value = (e as CustomEvent<{ value: Record<string, unknown> }>).detail.value;
      if (typeof value.name === 'string') nameSpan.textContent = value.name;
      const next = (this._options?.notifications ?? []).map((n) =>
        n.id === notification.id ? notifyFormToNotification(notification.id, value) : n,
      );
      this._debounce('notifications', () => void this._persistNotifications(next, false));
    });
    this._liveHassEls.push(form);
    body.appendChild(form);

    const del = document.createElement('ha-button');
    del.className = 'hk-notify-delete';
    del.textContent = t('notify.delete');
    del.addEventListener('click', () => void this._deleteNotification(notification.id));
    body.appendChild(del);
    card.appendChild(body);

    header.addEventListener('click', () => {
      const expanded = this._itemExpanded.has(notification.id);
      const chev = header.querySelector<HTMLElement>('.hk-section-chevron');
      if (expanded) {
        this._itemExpanded.delete(notification.id);
        body.style.display = 'none';
        header.setAttribute('aria-expanded', 'false');
        chev?.classList.remove('open');
      } else {
        this._itemExpanded.add(notification.id);
        body.style.display = '';
        header.setAttribute('aria-expanded', 'true');
        chev?.classList.add('open');
      }
    });

    return card;
  }

  private _addNotification(): Promise<void> {
    const profiles = this._options?.profiles ?? [];
    if (!profiles.length) return Promise.resolve();
    const blank: Notification = {
      id: '',
      name: t('notify.new_name'),
      profile_id: profiles[0].id,
      targets: this._notifyTargets.length ? [this._notifyTargets[0]] : [],
      actions: ['complete', 'snooze', 'open'],
      snooze_hours: 24,
      style: 'walk',
      auto: { overdue: false, due_soon: false },
    };
    return this._persistNotifications([...(this._options?.notifications ?? []), blank], true, true);
  }

  private _deleteNotification(id: string): Promise<void> {
    this._itemExpanded.delete(id);
    const next = (this._options?.notifications ?? []).filter((n) => n.id !== id);
    return this._persistNotifications(next, true);
  }

  private async _persistNotifications(
    notifications: Notification[],
    render: boolean,
    expandLast = false,
  ): Promise<void> {
    if (!this._hass) return;
    this._options = { ...(this._options as HomeKeeperOptions), notifications };
    try {
      this._options = await api.setOptions(this._hass, {
        notifications,
      } as Partial<HomeKeeperOptions>);
      if (expandLast) {
        const saved = this._options?.notifications ?? [];
        if (saved.length) this._itemExpanded.add(saved[saved.length - 1].id);
      }
      if (render) this._render();
      this._toast(t('settings.saved'));
    } catch (err) {
      this._toast(String((err as { message?: string })?.message || err));
    }
  }

  /** Render the Settings → Companions section: integrations that work with
   *  Home Keeper. *Connected* rows (self-registered, or a detected glue) deep-link
   *  to the companion's own options page; *Suggested* rows (a popular upstream is
   *  installed but its glue isn't) offer an install link and can be dismissed. */
  private _renderCompanions(host: HTMLElement): void {
    const all = this._companions ?? [];
    const connected = all.filter((c) => c.status === 'connected');
    const suggested = all.filter((c) => c.status === 'suggested');

    const card = document.createElement('ha-card');
    card.className = 'hk-form-card';
    card.id = 'hk-companions';
    const inner = document.createElement('div');
    inner.className = 'hk-form-inner';

    const sections: string[] = [
      `<div class="hk-form-title">${escapeHTML(t('companions.heading'))}</div>`,
      `<div class="hk-settings-intro">${escapeHTML(t('companions.help'))}</div>`,
      // Static link to the docs catalog of known companions/glue. Only the
      // template's `<a>` is trusted here — the URL is a constant, no user content.
      `<div class="hk-settings-intro">${t('companions.discover', { url: COMPANIONS_DOCS_URL })}</div>`,
    ];
    if (!connected.length && !suggested.length) {
      sections.push(`<ha-alert alert-type="info">${escapeHTML(t('companions.empty'))}</ha-alert>`);
    }
    if (connected.length) {
      sections.push(
        `<div class="hk-companion-group">${escapeHTML(t('companions.connected'))}</div>`,
        ...connected.map((c) => this._companionRow(c)),
      );
    }
    if (suggested.length) {
      sections.push(
        `<div class="hk-companion-group">${escapeHTML(t('companions.suggested'))}</div>`,
        ...suggested.map((c) => this._companionRow(c)),
      );
    }
    inner.innerHTML = sections.join('');
    card.appendChild(inner);
    host.appendChild(card);
    this._wireCompanions(inner);
  }

  /** One companion row's HTML (icon, name + status chip, description, actions). */
  private _companionRow(c: Companion): string {
    const icon = escapeHTML(c.icon || 'mdi:puzzle');
    const chipLabel = c.status === 'connected' ? t('companions.chip.connected') : t('companions.chip.suggested');
    const chipClass = c.status === 'connected' ? 'hk-comp-connected' : 'hk-comp-suggested';
    const actions: string[] =
      c.status === 'connected'
        ? [
            `<ha-button class="hk-comp-configure" data-domain="${escapeHTML(c.configure_domain || c.domain)}">${escapeHTML(t('companions.configure'))}</ha-button>`,
          ]
        : [
            `<ha-button raised class="hk-comp-install" data-url="${escapeHTML(c.install_url || '')}">${escapeHTML(t('companions.install'))}</ha-button>`,
            `<ha-button class="hk-comp-dismiss" data-domain="${escapeHTML(c.domain)}">${escapeHTML(t('companions.dismiss'))}</ha-button>`,
          ];
    if (c.docs_url) {
      actions.push(
        `<ha-button class="hk-comp-docs" data-url="${escapeHTML(c.docs_url)}">${escapeHTML(t('companions.docs'))}</ha-button>`,
      );
    }
    const desc = c.description
      ? `<div class="hk-companion-desc">${escapeHTML(c.description)}</div>`
      : '';
    return `
      <div class="hk-companion">
        <ha-icon class="hk-companion-ic" icon="${icon}"></ha-icon>
        <div class="hk-companion-body">
          <div class="hk-companion-name">
            ${escapeHTML(c.name)}
            <ha-assist-chip class="${chipClass}" label="${escapeHTML(chipLabel)}"></ha-assist-chip>
          </div>
          ${desc}
        </div>
        <div class="hk-companion-actions">${actions.join('')}</div>
      </div>`;
  }

  /** Wire a companion section's Configure / Install / Docs / Dismiss buttons. */
  private _wireCompanions(root: HTMLElement): void {
    root.querySelectorAll<HTMLElement>('.hk-comp-configure').forEach((b) =>
      b.addEventListener('click', () => {
        const domain = b.dataset.domain;
        if (domain) this._navigateToIntegration(domain);
      }),
    );
    root.querySelectorAll<HTMLElement>('.hk-comp-install, .hk-comp-docs').forEach((b) =>
      b.addEventListener('click', () => {
        const url = b.dataset.url;
        // Defense in depth: the backend already restricts docs_url to http(s), but
        // only open externally-supplied links with a safe scheme regardless.
        if (url && /^https?:\/\//i.test(url)) window.open(url, '_blank', 'noopener');
      }),
    );
    root.querySelectorAll<HTMLElement>('.hk-comp-dismiss').forEach((b) =>
      b.addEventListener('click', () => {
        const domain = b.dataset.domain;
        if (domain) void this._dismissCompanion(domain);
      }),
    );
  }

  /** Deep-link to an integration's config page (same pattern as "Edit in X"). */
  private _navigateToIntegration(domain: string): void {
    history.pushState(null, '', `/config/integrations/integration/${domain}`);
    window.dispatchEvent(
      new CustomEvent('location-changed', {
        detail: { replace: false },
        bubbles: true,
        composed: true,
      }),
    );
  }

  /** Hide a suggested companion by persisting its domain to dismissed_companions. */
  private async _dismissCompanion(domain: string): Promise<void> {
    if (!this._hass) return;
    const current = this._options?.dismissed_companions ?? [];
    if (current.includes(domain)) return;
    const dismissed_companions = [...current, domain];
    try {
      await api.setOptions(this._hass, { dismissed_companions });
      await this._refresh();
    } catch (err) {
      this._toast(String((err as { message?: string })?.message || err));
    }
  }

  private _makeForm(
    schema: FormField[],
    data: Record<string, unknown>,
    onChange: (value: Record<string, unknown>) => void,
  ): HaFormElement {
    const form = document.createElement('ha-form') as HaFormElement;
    form.hass = this._hass;
    form.schema = schema;
    form.data = data;
    form.computeLabel = (s: { name: string }): string => (s.name ? t('field.' + s.name) : '');
    // Muted per-field helper text under each field (keyed `help.<field>`); returns ''
    // where no string is authored, so helpers appear only where we wrote them.
    form.computeHelper = (s: { name: string }): string => {
      if (!s.name) return '';
      const h = t('help.' + s.name);
      return h === 'help.' + s.name ? '' : h;
    };
    form.addEventListener('value-changed', (e: Event) => {
      const value = (e as CustomEvent<{ value: Record<string, unknown> }>).detail.value;
      onChange(value);
    });
    this._liveHassEls.push(form);
    return form;
  }

  /** Appliances associated with a task's attached device (its own or related). */
  private _assetsForDevice(deviceId?: string | null): Asset[] {
    if (!deviceId) return [];
    return this._assets.filter(
      (a) =>
        a.device_id === deviceId || (a.related_device_ids ?? []).includes(deviceId),
    );
  }

  /**
   * `asset_id:part_id` options for the task form's "Linked consumable" picker,
   * scoped to the consumables of the appliance the task is **attached to** (its
   * device). You link a task to its own appliance's consumable, not some unrelated
   * appliance's — so the list stays short and unambiguous. Empty when the task has no
   * device, or its appliance has no consumables (the picker then hides).
   */
  private _consumableOptions(task: Partial<Task>): { value: string; label: string }[] {
    const assets = this._assetsForDevice(task.device_id);
    const multi = assets.length > 1; // disambiguate by appliance only when needed
    const options: { value: string; label: string }[] = [];
    for (const asset of assets) {
      for (const part of asset.parts ?? []) {
        if (part.type !== 'consumable' || !part.id) continue;
        options.push({
          value: `${asset.id}:${part.id}`,
          label: multi ? `${asset.name} · ${part.name}` : part.name,
        });
      }
    }
    return options.sort((a, b) => a.label.localeCompare(b.label));
  }

  /** Appliances reachable from a task: the one(s) it's attached to via its device,
   *  plus the appliance behind a manual consumable link (its part's asset). */
  private _assetsForTask(task: Partial<Task>): Asset[] {
    const byDevice = this._assetsForDevice(task.device_id);
    const partAssetId = task.source?.part?.asset_id;
    if (partAssetId && !byDevice.some((a) => a.id === partAssetId)) {
      const a = this._assets.find((x) => x.id === partAssetId);
      if (a) return [...byDevice, a];
    }
    return byDevice;
  }

  /**
   * `asset_id:entry_id` options for the task form's "Links to show on card" picker:
   * every appliance document — an external **link** (kind `link`) or an **uploaded
   * file** (kind `file`, e.g. a PDF manual) — plus every metadata link (type `link`)
   * on the appliance(s) the task is associated with. The card resolves the chosen
   * pairs live (a file opens via a signed URL minted on click). Empty (the picker
   * then hides) when the task touches no appliance or none of them carry a document.
   */
  private _documentOptions(task: Partial<Task>): { value: string; label: string }[] {
    const assets = this._assetsForTask(task);
    const multi = assets.length > 1; // disambiguate by appliance only when needed
    const options: { value: string; label: string }[] = [];
    for (const asset of assets) {
      for (const doc of asset.documents ?? []) {
        if (!doc.id || !isDisplayableDocument(doc)) continue;
        const label = documentLabel(doc);
        options.push({
          value: `${asset.id}:${doc.id}`,
          label: multi ? `${asset.name} · ${label}` : label,
        });
      }
      for (const meta of asset.metadata ?? []) {
        if (meta.type !== 'link' || !meta.value || !meta.id) continue;
        options.push({
          value: `${asset.id}:${meta.id}`,
          label: multi ? `${asset.name} · ${meta.label}` : meta.label,
        });
      }
    }
    return options.sort((a, b) => a.label.localeCompare(b.label));
  }

  /** Resolve a task's part link to a "Appliance · Part · In stock: N" detail line
   *  (HTML — the part name is a clickable link to its product page when it has a
   *  `url`, same anchor pattern as the appliance's parts-list read view). */
  private _consumableLinkLabel(task: Task): string {
    const part = task.source?.part;
    if (!part) return '';
    const asset = this._assets.find((a) => a.id === part.asset_id);
    const p = asset?.parts?.find((x) => x.id === part.part_id);
    if (!asset || !p) return '';
    const stock =
      p.stock != null
        ? ` · ${escapeHTML(
            t(
              p.reorder_at != null && p.stock <= p.reorder_at ? 'part.lowStock' : 'part.inStock',
              { n: formatQuantity(p.stock, p.stock_unit) },
            ),
          )}`
        : '';
    const name = p.url
      ? `<a href="${safeHref(p.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(p.name)}</a>`
      : escapeHTML(p.name);
    return `${escapeHTML(asset.name)} · ${name}${stock}`;
  }

  /**
   * The bound sensor's live reading and unit for the task-form hint. Mirrors
   * `_sensorProgress`'s value extraction but reads the flat `sensor_*` edit state
   * (the entity/attribute the user is currently picking). `reading` is undefined
   * when the entity is unset, unknown, or non-numeric.
   */
  private _sensorLive(task: Partial<Task>): { reading?: number; unit?: string } {
    const sd = task as Record<string, unknown>;
    const entityId = String(sd.sensor_entity_id ?? task.sensor?.entity_id ?? '');
    if (!entityId) return {};
    const state = this._hass?.states?.[entityId];
    if (!state) return {};
    const attribute = String(sd.sensor_attribute ?? task.sensor?.attribute ?? '');
    const raw = attribute ? (state.attributes?.[attribute] as unknown) : state.state;
    const num = raw == null || raw === '' ? NaN : Number(raw);
    const unit = state.attributes?.unit_of_measurement as string | undefined;
    return { reading: Number.isNaN(num) ? undefined : num, unit };
  }

  /**
   * Refresh the task form's live copy in place (no re-render → keeps input focus).
   *
   * Two pieces: the sensor primer (only on sensor tasks, explains the baseline model)
   * and the rule summary above the submit button (every task kind). Both are pure
   * text derived from the current edit state, so this runs on any field change.
   */
  private _updateFormHints(box?: HTMLElement): void {
    // `box` is passed while the form is still being assembled (before it's in the
    // shadow root); afterwards we look it up. Same code either way, so the first
    // paint and every keystroke can't disagree about what the strip says.
    const root: ParentNode | null | undefined =
      box ?? this.shadowRoot?.querySelector('.hk-form-summary');
    if (!root) return;
    const task = this._edit.task || {};

    const value = root.querySelector('#hk-form-summary-value') as HTMLElement | null;
    const ruleText = formRecurrenceSummary(task);
    if (value) value.textContent = ruleText;

    const detail = root.querySelector('#hk-sensor-hint') as HTMLElement | null;
    const detailText =
      task.recurrence_type === 'sensor' ? sensorHintText(task, this._sensorLive(task)) : '';
    if (detail) {
      detail.textContent = detailText;
      detail.style.display = detailText ? '' : 'none';
    }

    // Hide the whole strip only when it has nothing at all to say — a form with a
    // recurrence type but no sensor detail still shows its rule.
    (root as HTMLElement).style.display = ruleText || detailText ? '' : 'none';
  }

  private _renderTaskForm(host: HTMLElement): void {
    const task = this._edit.task || {};
    const card = document.createElement('ha-card');
    card.className = 'hk-form-card';
    card.id = 'hk-form';
    const inner = document.createElement('div');
    inner.className = 'hk-form-inner';
    // Title carries a help affordance: a "?" icon linking to the User Guide so the
    // recurrence kinds (esp. sensor-based) are one tap from an explanation.
    inner.innerHTML = `<div class="hk-form-title"><span>${escapeHTML(
      task.id ? t('form.task.edit') : t('form.task.new'),
    )}</span><a class="hk-form-help" href="${SENSOR_DOCS_URL}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(
      t('help.docsLink'),
    )}" aria-label="${escapeHTML(t('help.docsLink'))}"><ha-icon icon="mdi:help-circle-outline"></ha-icon></a></div>`;

    // Sensor-based tasks have no clock cadence — a short primer (with a docs link)
    // explains the baseline/reset model the fields below can't convey on their own.
    if (task.recurrence_type === 'sensor') {
      const intro = document.createElement('div');
      intro.className = 'hk-settings-intro';
      intro.innerHTML = t('help.sensor.section', { url: SENSOR_DOCS_URL });
      inner.appendChild(intro);
    }

    const form = this._makeForm(
      taskSchema(task, this._consumableOptions(task), this._documentOptions(task), this._tags),
      taskFormData(task),
      (value) => {
        // Which fields the form shows, before this edit — normalized through
        // `taskFormData` so a default the form seeded can't read as a change (see
        // `taskFormSchemaKey`). Anything else, a typed character included, leaves it
        // untouched and must never reach `_render()`.
        const prevSchemaKey = taskFormSchemaKey(this._edit.task ?? {});
        const prevDevice = this._edit.task?.device_id ?? '';
        this._edit.task = {
          ...this._edit.task,
          ...value,
          interval: Number(value.interval) || 1,
        } as Partial<Task>;
        this._edit.error = undefined;
        // Refresh the notes preview in place — a re-render here would drop focus from
        // the textarea mid-word.
        this._taskNotePreview?.update(String(value.notes ?? ''));
        // Changing the attached device re-scopes the consumable picker; drop a link
        // that no longer belongs to the newly-attached appliance. Both sides are
        // normalized to '' so a cleared picker (null vs. undefined vs. absent) doesn't
        // look like a change on an unrelated edit.
        if ((value.device_id ?? '') !== prevDevice) {
          const opts = this._consumableOptions(this._edit.task);
          const cur = (this._edit.task as Record<string, unknown>).consumable_link;
          if (cur && !opts.some((o) => o.value === cur)) {
            (this._edit.task as Record<string, unknown>).consumable_link = '';
          }
          // The card-link picker is likewise device-scoped — drop chosen links that
          // no longer resolve to the newly-attached appliance.
          const docOpts = this._documentOptions(this._edit.task);
          (this._edit.task as Record<string, unknown>).card_links = cardLinkTokens(
            this._edit.task,
          ).filter((tok) => docOpts.some((o) => o.value === tok));
        }
        // Picking a meter entity prefills the unit label from the entity itself, so
        // "300" reads as "300 h" without anyone typing it. Only when still blank —
        // a label the user (or a managing integration) chose is never overwritten.
        if (
          this._edit.task?.recurrence_type === 'sensor' &&
          !String(value.sensor_unit ?? '').trim()
        ) {
          const live = this._sensorLive(this._edit.task);
          if (live.unit) {
            (this._edit.task as Record<string, unknown>).sensor_unit = live.unit;
          }
        }
        // Switching the time backstop on with a blank or zeroed interval seeds a
        // working default, so the three fields it reveals describe a real rule
        // immediately instead of sitting at "every 0" and being silently dropped.
        if (
          Boolean(value.sensor_backstop_on) &&
          !(Number((this._edit.task as Record<string, unknown>).sensor_also_every) > 0)
        ) {
          (this._edit.task as Record<string, unknown>).sensor_also_every =
            DEFAULT_BACKSTOP_INTERVAL;
        }
        // The recurrence type (cadence/sensor fields), the sensor mode (usage vs.
        // threshold vs. state), the time-backstop switch (which reveals or hides its
        // three fields), the bound entity's binary-ness (which swaps the state
        // control), and the attached device (which scopes the consumable picker) each
        // toggle the visible schema -> re-render. Read off the merged state, so it and
        // the "before" key above are the same shape through the same normalizer.
        if (taskFormSchemaKey(this._edit.task ?? {}) !== prevSchemaKey) {
          this._render();
        } else {
          // The edit didn't change the visible schema, so refresh the live copy in
          // place — a full re-render would drop focus from the box being typed in, and
          // Home Assistant's global one-letter shortcuts would then swallow the rest of
          // the word (`d` device search, `a` Assist, `e`/`c` quick bar, `m` my-link).
          // Every task kind, not just sensor: the rule summary above the submit
          // button has to track an interval or a unit change too.
          this._updateFormHints();
        }
      },
    );
    form.id = 'hk-task-form';
    // Muted per-field helper text under each field (keyed `help.<field>`); returns
    // '' where no string is authored, so helpers appear only where we wrote them.
    form.computeHelper = (s: { name: string }): string => {
      if (!s.name) return '';
      const h = t('help.' + s.name);
      return h === 'help.' + s.name ? '' : h;
    };
    inner.appendChild(form);

    // Live Markdown preview of the notes field. It sits after the whole form rather
    // than directly under the field: the task schema is one `ha-form` (name, notes,
    // recurrence, sensor…), and splitting it just to interleave a preview would fork a
    // pure, well-tested schema builder. The preview only shows once there's something
    // to preview, so it stays out of the way for the common no-notes task.
    this._taskNotePreview = this._attachNotePreview(inner, String(task.notes ?? ''));

    // One box, directly above the submit button, answering "what did I just build?"
    // in two registers: the rule as a headline, and — for a sensor task — the live
    // arithmetic underneath ("reads 660 h, so first due at 760 h"). These used to be
    // two separate panels stacked on each other, which meant two places to look for
    // one answer; the headline is the same sentence the saved task's card will show,
    // because it comes from the same formatter.
    const summary = document.createElement('div');
    summary.className = 'hk-form-summary';
    summary.innerHTML =
      `<span class="hk-form-summary-label">${escapeHTML(t('form.summary.label'))}</span>` +
      `<span class="hk-form-summary-value" id="hk-form-summary-value"></span>` +
      `<span class="hk-form-summary-detail" id="hk-sensor-hint"></span>`;
    inner.appendChild(summary);
    this._updateFormHints(summary);

    if (this._edit.error) {
      const err = document.createElement('ha-alert');
      err.setAttribute('alert-type', 'error');
      err.textContent = this._edit.error;
      inner.appendChild(err);
    }

    const actions = document.createElement('div');
    actions.className = 'hk-form-actions';
    const save = document.createElement('ha-button');
    save.setAttribute('raised', '');
    save.id = 'f-save';
    save.textContent = task.id ? t('btn.save') : t('btn.create');
    save.addEventListener('click', () => void this._submitForm());
    const cancel = document.createElement('ha-button');
    cancel.id = 'f-cancel';
    cancel.textContent = t('btn.cancel');
    cancel.addEventListener('click', () => this._closeForm());
    actions.append(save, cancel);
    inner.appendChild(actions);

    card.appendChild(inner);
    host.appendChild(card);
  }

  /** Build the completion-details dialog (log a new completion, or edit a past one). */
  private _renderCompletionDialog(host: HTMLElement): void {
    const c = this._completion;
    if (!c.task) return;
    const editing = c.ts != null;
    const dialog = document.createElement('ha-dialog') as HTMLElement & {
      heading?: string;
    };
    dialog.setAttribute('open', '');
    dialog.setAttribute(
      'heading',
      editing ? t('completion.edit') : t('completion.title', { name: c.task.name }),
    );
    dialog.addEventListener('closed', () => {
      if (this._completion.open) this._closeCompletionDialog();
    });

    const body = document.createElement('div');
    body.className = 'hk-completion-body';

    // note / cost / who via ha-form; required fields get the asterisk cue. Logging a
    // *new* completion also offers an optional "Completed at" date/time (defaults to
    // now server-side when left blank) — never shown in edit-metadata mode, which
    // must never touch the timestamp (see MoveCompletionDialogState for that).
    const req = new Set(c.required);
    const schema: FormField[] = [];
    if (!editing) {
      schema.push({ name: 'completedAt', selector: selDateTime() });
    }
    schema.push(
      { name: 'note', required: req.has('note'), selector: selText(true) },
      { name: 'cost', required: req.has('cost'), selector: selNumber(0) },
      { name: 'who', required: req.has('who'), selector: selEntity({ domain: 'person' }) },
    );
    // A sensor task in a numeric mode also logs where its meter stood. Home Keeper
    // fills this in from the live sensor, so it is never *required* — but it is
    // editable, which matters twice: back-dating records today's reading (the meter
    // has moved since the work was done), and on a usage task correcting it on the
    // latest completion re-anchors the meter itself. Bare number selector, like the
    // form's starting-reading box: a reading can be 0 or negative.
    const live = taskRecordsReading(c.task) ? this._sensorLive(c.task) : null;
    if (live)
      schema.push({
        name: 'reading',
        selector: { number: { mode: 'box', step: 'any' } },
      });
    // A completion note renders as Markdown in the history list, so it gets the same
    // live preview as every other notes field.
    let notePreview: MarkdownPreview | null = null;
    const form = this._makeForm(
      schema,
      {
        completedAt: isoToHaDateTime(c.data.completedAt),
        note: c.data.note ?? '',
        cost: c.data.cost ?? undefined,
        who: c.data.who ?? undefined,
        // Logging a new completion pre-fills the live reading (that *is* where the
        // meter stands); editing shows what was recorded at the time.
        reading: c.data.reading ?? (editing ? undefined : live?.reading),
      },
      (value) => {
        this._completion.data = {
          ...this._completion.data,
          completedAt: editing ? c.data.completedAt : haDateTimeToIso(value.completedAt as string),
          note: (value.note as string) || undefined,
          cost: value.cost == null || value.cost === '' ? undefined : Number(value.cost),
          who: (value.who as string) || undefined,
          reading:
            value.reading == null || value.reading === '' ? undefined : Number(value.reading),
        };
        this._completion.error = undefined;
        notePreview?.update(String(value.note ?? ''));
      },
    );
    body.appendChild(form);
    notePreview = this._attachNotePreview(body, String(c.data.note ?? ''));

    // Photo upload via HA's native picture-upload, if the element is available in
    // this frontend build (degrade gracefully if not — the rest still works).
    if (customElements.get('ha-picture-upload')) {
      const label = document.createElement('div');
      label.className = 'hk-completion-photo-label';
      label.textContent = t('completion.photo');
      const upload = document.createElement('ha-picture-upload') as HTMLElement & {
        hass?: Hass;
        value?: string | null;
      };
      upload.hass = this._hass;
      upload.value = c.data.photo ?? null;
      this._liveHassEls.push(upload);
      const onPhoto = (): void => {
        this._completion.data = { ...this._completion.data, photo: upload.value || undefined };
      };
      upload.addEventListener('change', onPhoto);
      upload.addEventListener('value-changed', onPhoto);
      body.append(label, upload);
    }

    if (c.error) {
      const err = document.createElement('ha-alert');
      err.setAttribute('alert-type', 'error');
      err.textContent = c.error;
      body.appendChild(err);
    }
    dialog.appendChild(body);

    // Action buttons must be wrapped in <ha-dialog-footer slot="footer"> — current
    // ha-dialog (backed by wa-dialog) only exposes a "footer" slot; primaryAction/
    // secondaryAction slotted directly on <ha-dialog> silently don't render. Fall
    // back to slotting straight on <ha-dialog> (the pre-wa-dialog convention) if
    // ha-dialog-footer isn't registered, so older HA frontends keep working too.
    const hasFooter = Boolean(customElements.get('ha-dialog-footer'));
    const footer: HTMLElement = hasFooter
      ? document.createElement('ha-dialog-footer')
      : dialog;
    if (hasFooter) footer.setAttribute('slot', 'footer');

    // Primary action: log (or save edit). Optional-mode logging also offers "skip
    // details" to complete with nothing recorded.
    const primary = document.createElement('ha-button');
    primary.setAttribute('slot', 'primaryAction');
    primary.setAttribute('raised', '');
    primary.textContent = editing ? t('btn.save') : t('completion.markDone');
    primary.addEventListener('click', () => void this._submitCompletion());
    footer.appendChild(primary);

    if (!editing && c.task.completion_detail === 'optional') {
      const skip = document.createElement('ha-button');
      skip.setAttribute('slot', 'secondaryAction');
      skip.textContent = t('completion.skip');
      skip.addEventListener('click', () => {
        this._completion.data = {};
        void this._submitCompletion();
      });
      footer.appendChild(skip);
    }
    const cancel = document.createElement('ha-button');
    cancel.setAttribute('slot', 'secondaryAction');
    cancel.textContent = t('btn.cancel');
    cancel.addEventListener('click', () => this._closeCompletionDialog());
    footer.appendChild(cancel);

    if (hasFooter) dialog.appendChild(footer);
    host.appendChild(dialog);
  }

  /**
   * Build the "move completion date" dialog — re-timestamps one already-recorded
   * completion via `api.moveCompletion`. Deliberately minimal (one date/time field)
   * and separate from `_renderCompletionDialog`'s edit-metadata mode.
   */
  private _renderMoveCompletionDialog(host: HTMLElement): void {
    const m = this._moveCompletion;
    if (!m.task) return;
    const dialog = document.createElement('ha-dialog') as HTMLElement & {
      heading?: string;
    };
    dialog.setAttribute('open', '');
    dialog.setAttribute('heading', t('completion.moveDate'));
    dialog.addEventListener('closed', () => {
      if (this._moveCompletion.open) this._closeMoveCompletion();
    });

    const body = document.createElement('div');
    body.className = 'hk-completion-body';

    const schema: FormField[] = [{ name: 'completedAt', required: true, selector: selDateTime() }];
    const form = this._makeForm(
      schema,
      { completedAt: isoToHaDateTime(m.newTs) },
      (value) => {
        this._moveCompletion.newTs = haDateTimeToIso(value.completedAt as string);
        this._moveCompletion.error = undefined;
      },
    );
    body.appendChild(form);

    if (m.error) {
      const err = document.createElement('ha-alert');
      err.setAttribute('alert-type', 'error');
      err.textContent = m.error;
      body.appendChild(err);
    }
    dialog.appendChild(body);

    // See _renderCompletionDialog: current ha-dialog (backed by wa-dialog) only
    // exposes a "footer" slot — primaryAction/secondaryAction slotted directly on
    // <ha-dialog> silently don't render. Fall back to the old direct-slot
    // convention if ha-dialog-footer isn't registered (older HA frontends).
    const hasFooter = Boolean(customElements.get('ha-dialog-footer'));
    const footer: HTMLElement = hasFooter ? document.createElement('ha-dialog-footer') : dialog;
    if (hasFooter) footer.setAttribute('slot', 'footer');

    const primary = document.createElement('ha-button');
    primary.setAttribute('slot', 'primaryAction');
    primary.setAttribute('raised', '');
    primary.textContent = t('btn.save');
    primary.addEventListener('click', () => void this._submitMoveCompletion());
    footer.appendChild(primary);

    const cancel = document.createElement('ha-button');
    cancel.setAttribute('slot', 'secondaryAction');
    cancel.textContent = t('btn.cancel');
    cancel.addEventListener('click', () => this._closeMoveCompletion());
    footer.appendChild(cancel);

    if (hasFooter) dialog.appendChild(footer);
    host.appendChild(dialog);
  }

  private _renderAssetForm(host: HTMLElement): void {
    const x = this._assetEdit.asset || {};
    const editing = Boolean(x.id);
    const card = document.createElement('ha-card');
    card.className = 'hk-form-card';
    card.id = 'hk-asset-form';
    const inner = document.createElement('div');
    inner.className = 'hk-form-inner';
    inner.innerHTML = `<div class="hk-form-title">${escapeHTML(
      editing ? t('form.appliance.edit') : t('form.appliance.new'),
    )}</div>`;

    const mergeAsset = (value: Record<string, unknown>): void => {
      this._assetEdit.asset = { ...this._assetEdit.asset, ...value } as Partial<Asset>;
      this._setAssetError(undefined);
    };

    // Identity (kind toggle re-renders since the schema changes).
    const identity = this._makeForm(
      this._assetIdentitySchema(x, editing),
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
        const prevAsset = this._assetEdit.asset;
        // Defaulted exactly as the form data above seeds it, so an appliance that
        // doesn't carry a kind can't make the form's 'virtual' read as a change — that
        // would re-render on the first character typed into the name, dropping focus
        // (and handing the keystrokes to HA's global shortcuts; see the task form).
        const prevKind = prevAsset?.kind ?? 'virtual';
        const prevDeviceId = prevAsset?.device_id;
        mergeAsset(value);
        if (value.kind === 'existing' && value.device_id && value.device_id !== prevDeviceId) {
          const fill = this._deviceDefaults(String(value.device_id), prevAsset);
          if (fill) {
            mergeAsset(fill);
            identity.data = { ...identity.data, ...fill };
          }
        }
        if (!editing && value.kind !== prevKind) this._render();
      },
    );
    inner.appendChild(identity);

    inner.appendChild(this._section(t('section.reference')));
    inner.appendChild(
      this._makeForm(
        this._structuredDetailsSchema(),
        { cost: x.cost ?? undefined },
        mergeAsset,
      ),
    );

    // Notes get their own section so the live Markdown preview can sit directly under
    // the field it previews (the appliance form is already section-split, unlike the
    // task form's single `ha-form`).
    inner.appendChild(this._section(t('section.notes')));
    let assetNotePreview: MarkdownPreview | null = null;
    inner.appendChild(
      this._makeForm([{ name: 'notes', selector: selText(true) }], { notes: x.notes ?? '' }, (value) => {
        mergeAsset(value);
        assetNotePreview?.update(String(value.notes ?? ''));
      }),
    );
    assetNotePreview = this._attachNotePreview(inner, String(x.notes ?? ''));

    this._renderDocumentsEditor(inner);

    this._renderMetadataEditor(inner);

    this._renderPartsEditor(inner);

    inner.appendChild(this._section(t('section.related')));
    inner.appendChild(
      this._makeForm(
        [{ name: 'related_device_ids', selector: selDevice(true) }],
        { related_device_ids: x.related_device_ids ?? [] },
        mergeAsset,
      ),
    );

    if (this._assetEdit.error) {
      inner.appendChild(this._errorAlert(this._assetEdit.error, this._assetEdit.errorLink));
    }

    const actions = document.createElement('div');
    actions.className = 'hk-form-actions';
    const save = document.createElement('ha-button');
    save.setAttribute('raised', '');
    save.id = 'a-save';
    save.textContent = editing ? t('btn.save') : t('btn.create');
    // Saving mid-upload would PUT the client draft over the asset the upload response
    // is about to rewrite, losing the new document.
    if (this._assetEdit.upload) save.setAttribute('disabled', '');
    save.addEventListener('click', () => void this._submitAssetForm());
    const cancel = document.createElement('ha-button');
    cancel.id = 'a-cancel';
    cancel.textContent = t('btn.cancel');
    cancel.addEventListener('click', () => this._closeAssetForm());
    actions.append(save, cancel);
    inner.appendChild(actions);

    card.appendChild(inner);
    host.appendChild(card);

    // An upload failure is reported inline, but the control that failed can be well
    // below the fold in a long form — bring it into view. Driven by a one-shot flag
    // set in `_failUpload`, never by "an error exists": `mergeAsset` clears the error
    // on every keystroke, so a state check here would re-scroll on unrelated renders.
    if (this._scrollToError) {
      const key = this._scrollToError;
      this._scrollToError = undefined;
      requestAnimationFrame(() => {
        const el = this.shadowRoot?.getElementById(`hk-upload-err-${key}`);
        // Guarded: scrollIntoView is missing in jsdom, and the node is gone if a
        // later render dropped the alert before the frame ran.
        if (typeof el?.scrollIntoView === 'function') {
          el.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
      });
    }
  }

  /** Documents editor: list existing docs with a remove button, plus controls to add
   *  a link or upload a file. Documents are managed live (each its own backend call),
   *  so a file upload needs an already-saved appliance (it must have an id). */
  private _renderDocumentsEditor(inner: HTMLElement): void {
    inner.appendChild(this._section(t('section.documents')));
    const docs = this._assetEdit.asset?.documents || [];

    // Existing documents: each is a clear card (icon + name + details) with Open /
    // Edit / Remove actions — except the one being edited, which shows its form.
    docs.forEach((d) => {
      if (d.id && this._assetEdit.editingDocId === d.id) this._renderDocumentEdit(inner, d);
      else this._renderDocumentCard(inner, d);
    });

    this._renderDocumentAdd(inner);
  }

  /** One existing document as a read row: icon, name, a details subtitle, and the
   *  Open (link/signed-file URL) / Edit / Remove actions. */
  private _renderDocumentCard(inner: HTMLElement, d: AssetDocument): void {
    const card = document.createElement('div');
    card.className = 'hk-doc-card';

    const ic = document.createElement('div');
    ic.className = 'hk-doc-ic';
    const icon = document.createElement('ha-icon');
    icon.setAttribute('icon', documentIcon(d));
    ic.appendChild(icon);

    const main = document.createElement('div');
    main.className = 'hk-doc-main';
    const name = document.createElement('div');
    name.className = 'hk-doc-name';
    name.textContent = documentLabel(d);
    main.appendChild(name);
    const subText = this._documentSubtitle(d);
    if (subText) {
      const sub = document.createElement('div');
      sub.className = 'hk-doc-sub';
      sub.textContent = subText;
      main.appendChild(sub);
    }

    const actions = document.createElement('div');
    actions.className = 'hk-doc-actions';
    // Open is only meaningful for a link with a URL, or a file already saved (it owns
    // a blob keyed by its id — a brand-new asset's links have no file to open).
    const canOpen = d.kind === 'file' ? Boolean(d.id) : Boolean(d.url);
    if (canOpen) {
      // A real link for the same reason the detail page's rows are — a `window.open`
      // after the async sign never fires in the iOS app's WKWebView.
      const assetId = this._assetEdit.asset?.id;
      const target: SignedFileRef | string | undefined =
        d.kind === 'file'
          ? assetId && d.id
            ? { kind: 'document', assetId, id: d.id }
            : undefined
          : d.url;
      actions.appendChild(this._openFileAnchor(target, () => this._openDocument(d)));
    }
    const edit = document.createElement('ha-icon-button');
    edit.setAttribute('label', t('btn.edit'));
    this._setIcon(edit, MDI_EDIT);
    edit.addEventListener('click', () => {
      this._assetEdit.editingDocId = d.id;
      this._render();
    });
    const del = document.createElement('ha-icon-button');
    del.setAttribute('label', t('btn.removeDocument'));
    this._setIcon(del, MDI_DELETE);
    del.addEventListener('click', () => void this._removeDocument(d));
    actions.append(edit, del);

    card.append(ic, main, actions);
    inner.appendChild(card);
  }

  /** Inline editor for one document: a link edits name + URL; a file (upload-only) edits
   *  only its display name. Save commits, Cancel discards. */
  private _renderDocumentEdit(inner: HTMLElement, d: AssetDocument): void {
    const box = document.createElement('div');
    box.className = 'hk-part hk-doc-edit';
    const isLink = d.kind === 'link';
    const draft = { name: d.name || '', url: d.kind === 'link' ? d.url ?? '' : '' };
    const schema: FormField[] = isLink
      ? [
          {
            name: '',
            type: 'grid',
            schema: [
              { name: 'doc_name', selector: selText() },
              { name: 'doc_url', selector: selText() },
            ],
          },
        ]
      : [{ name: 'doc_name', selector: selText() }];
    const data = isLink ? { doc_name: draft.name, doc_url: draft.url } : { doc_name: draft.name };
    box.appendChild(
      this._makeForm(schema, data, (value) => {
        if ('doc_name' in value) draft.name = String(value.doc_name ?? '');
        if ('doc_url' in value) draft.url = String(value.doc_url ?? '');
      }),
    );

    const row = document.createElement('div');
    row.className = 'hk-doc-edit-actions';
    const save = document.createElement('ha-button');
    save.setAttribute('raised', '');
    save.textContent = t('btn.save');
    save.addEventListener('click', () =>
      void this._updateDocument(d, isLink ? { name: draft.name, url: draft.url } : { name: draft.name }),
    );
    const cancel = document.createElement('ha-button');
    cancel.textContent = t('btn.cancel');
    cancel.addEventListener('click', () => {
      this._assetEdit.editingDocId = undefined;
      this._render();
    });
    row.append(save, cancel);
    box.appendChild(row);
    inner.appendChild(box);
  }

  /** The "add a document" area: a name + URL link form (always available, even before
   *  the appliance is saved) and — once saved — a file upload control. */
  private _renderDocumentAdd(inner: HTMLElement): void {
    const assetId = this._assetEdit.asset?.id;
    const add = document.createElement('div');
    add.className = 'hk-doc-add';
    const title = document.createElement('div');
    title.className = 'hk-doc-add-title';
    title.textContent = t('doc.addHeading');
    add.appendChild(title);

    const draft: { name: string; url: string } = { name: '', url: '' };
    add.appendChild(
      this._makeForm(
        [
          {
            name: '',
            type: 'grid',
            schema: [
              { name: 'doc_name', selector: selText() },
              { name: 'doc_url', selector: selText() },
            ],
          },
        ],
        { doc_name: '', doc_url: '' },
        (value) => {
          draft.name = String(value.doc_name ?? '');
          draft.url = String(value.doc_url ?? '');
        },
      ),
    );

    const seedRow = document.createElement('div');
    seedRow.className = 'hk-meta-seeds';
    const addLink = document.createElement('ha-button');
    addLink.textContent = t('btn.addLink');
    addLink.addEventListener('click', () => void this._addLinkDocument(draft.name, draft.url));
    seedRow.appendChild(addLink);

    // A file can only be uploaded once the appliance exists (its id keys the blob).
    if (assetId) {
      const upload = document.createElement('ha-button');
      upload.textContent = this._uploadButtonLabel(UPLOAD_KEY_DOCUMENT, t('btn.uploadFile'));
      const picker = document.createElement('input');
      picker.type = 'file';
      picker.accept = 'application/pdf,image/png,image/jpeg,image/webp,image/gif';
      picker.style.display = 'none';
      picker.addEventListener('change', () => {
        const file = picker.files?.[0];
        if (file) void this._uploadDocument(file);
        picker.value = '';
      });
      upload.addEventListener('click', () => picker.click());
      if (this._assetEdit.upload) upload.setAttribute('disabled', '');
      seedRow.append(upload, picker);
    }
    add.appendChild(seedRow);
    // Progress / failure for this control, right where the user pressed the button.
    this._renderUploadStatus(add, UPLOAD_KEY_DOCUMENT);

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
  private _documentSubtitle(d: AssetDocument): string {
    if (d.kind === 'link') return d.url || '';
    const parts: string[] = [];
    if (d.filename) parts.push(d.filename);
    const size = this._formatBytes(d.size);
    if (size) parts.push(size);
    const type = this._documentTypeLabel(d.content_type);
    if (type) parts.push(type);
    return parts.join(' · ');
  }

  /** Format a byte count as a short human size ("950 B", "1.2 MB"). */
  private _formatBytes(bytes?: number): string {
    if (!bytes || bytes <= 0) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let value = bytes;
    let i = 0;
    while (value >= 1024 && i < units.length - 1) {
      value /= 1024;
      i += 1;
    }
    const rounded = i === 0 || value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
    return `${rounded} ${units[i]}`;
  }

  /** A short type badge from a MIME type ("application/pdf" → "PDF", "image/jpeg" → "JPEG"). */
  private _documentTypeLabel(contentType?: string): string {
    if (!contentType) return '';
    const subtype = contentType.split('/')[1] || '';
    return subtype.split(';')[0].trim().toUpperCase();
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
  private _openFileAnchor(
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
      const href = this._signedFiles.getByKey(key);
      if (href) a.href = href;
    }
    a.addEventListener('click', (e) => {
      if (a.getAttribute('href')) return; // native tap — don't double-open
      e.preventDefault();
      fallback();
    });
    const icon = document.createElement('ha-svg-icon');
    this._setIcon(icon, MDI_OPEN_IN_NEW);
    a.appendChild(icon);
    return a;
  }

  /** Open a document from the editor: a link opens its URL; a file opens via a signed
   *  URL. A link needs no asset id (it carries its own URL), so an unsaved asset's
   *  links still open. Fallback only — `_openFileAnchor` is the primary path. */
  private _openDocument(d: AssetDocument): void {
    if (this._hass) void openDocument(this._hass, this._assetEdit.asset?.id ?? '', d);
  }

  /** Append the live document list onto the in-progress edit copy and re-render. */
  private _setEditDocuments(asset: Asset): void {
    if (this._assetEdit.asset) this._assetEdit.asset.documents = asset.documents || [];
    this._render();
  }

  /** Set (or clear) the appliance-form error, plus an optional "Learn more" link. */
  private _setAssetError(message?: string, link?: string): void {
    this._assetEdit.error = message;
    this._assetEdit.errorLink = link;
  }

  private async _addLinkDocument(name: string, url: string): Promise<void> {
    if (!url.trim()) return;
    const assetId = this._assetEdit.asset?.id;
    // A saved appliance persists links through the service; a brand-new one collects
    // them on the working copy so they ride along in the create payload.
    if (!assetId) {
      const list = [...(this._assetEdit.asset?.documents || [])];
      list.push({ id: randomId(), kind: 'link', name, url });
      this._assetEdit.asset!.documents = list;
      this._render();
      return;
    }
    if (!this._hass) return;
    try {
      const asset = await api.addAssetDocument(this._hass, assetId, { name, url });
      this._setEditDocuments(asset);
    } catch (err) {
      this._setAssetError(String((err as { message?: string })?.message || err));
      this._render();
    }
  }

  private async _updateDocument(
    doc: AssetDocument,
    changes: { name: string; url?: string },
  ): Promise<void> {
    if (!doc.id) return;
    const assetId = this._assetEdit.asset?.id;
    if (!assetId) {
      const list = [...(this._assetEdit.asset?.documents || [])];
      const idx = list.findIndex((d) => d.id === doc.id);
      if (idx >= 0) {
        const merged: AssetDocument = { ...list[idx], name: changes.name };
        if (merged.kind === 'link' && changes.url !== undefined) merged.url = changes.url;
        list[idx] = merged;
        this._assetEdit.asset!.documents = list;
      }
      this._assetEdit.editingDocId = undefined;
      this._render();
      return;
    }
    if (!this._hass) return;
    try {
      const asset = await api.updateAssetDocument(this._hass, assetId, doc.id, changes);
      this._assetEdit.editingDocId = undefined;
      this._setEditDocuments(asset);
    } catch (err) {
      this._setAssetError(String((err as { message?: string })?.message || err));
      this._render();
    }
  }

  private async _removeDocument(doc: AssetDocument): Promise<void> {
    if (!doc.id) return;
    const assetId = this._assetEdit.asset?.id;
    if (this._assetEdit.editingDocId === doc.id) this._assetEdit.editingDocId = undefined;
    if (!assetId) {
      this._assetEdit.asset!.documents = (this._assetEdit.asset?.documents || []).filter(
        (d) => d.id !== doc.id,
      );
      this._render();
      return;
    }
    if (!this._hass) return;
    try {
      const asset = await api.removeAssetDocument(this._hass, assetId, doc.id);
      this._setEditDocuments(asset);
    } catch (err) {
      this._setAssetError(String((err as { message?: string })?.message || err));
      this._render();
    }
  }

  private async _uploadDocument(file: File): Promise<void> {
    const assetId = this._assetEdit.asset?.id;
    if (!this._hass || !assetId) return;
    const documentId = randomId();
    const hass = this._hass;
    const asset = await this._runUpload(UPLOAD_KEY_DOCUMENT, file, (opts) =>
      api.uploadAssetDocument(hass, assetId, documentId, file, undefined, opts),
    );
    if (asset) this._setEditDocuments(asset);
  }

  /**
   * Run an upload with a size pre-check, progress reporting and visible failures.
   *
   * Shared by the appliance-documents and part-file controls so both behave
   * identically. Returns the upload's result, or `undefined` if it failed or was
   * cancelled — the caller only grafts its own state on success.
   */
  private async _runUpload<T>(
    key: string,
    file: File,
    run: (opts: api.UploadOptions) => Promise<T>,
  ): Promise<T | undefined> {
    // A previous failure is stale the moment a new upload starts.
    this._assetEdit.uploadError = undefined;
    this._setAssetError(undefined);

    // Refuse an oversized file *here*: uploading 30 MB just to have the backend 413 it
    // wastes minutes, and on a slow link looks like a hang.
    const tooLarge = this._uploadSizeError(file);
    if (tooLarge) {
      this._failUpload(key, tooLarge);
      return undefined;
    }

    this._assetEdit.upload = {
      key,
      filename: file.name,
      loaded: 0,
      total: file.size,
      indeterminate: true,
      sent: false,
      visible: false,
    };
    this._uploadAbort = new AbortController();
    // Small files finish before this fires, so they never flash a progress bar — the
    // disabled "Uploading…" button is the only affordance they need.
    this._uploadShowTimer = setTimeout(() => {
      if (this._assetEdit.upload) {
        this._assetEdit.upload.visible = true;
        this._render();
      }
    }, UPLOAD_BAR_DELAY_MS);
    this._render();

    try {
      const result = await run({
        onProgress: (p) => this._onUploadProgress(key, p),
        signal: this._uploadAbort.signal,
      });
      this._toast(t('doc.uploadComplete', { name: file.name }));
      return result;
    } catch (err) {
      const e = err as api.UploadError;
      // A cancellation is the user's own doing — no error to report.
      if (!e?.aborted) {
        const { message, link } = this._uploadErrorMessage(e, file);
        this._failUpload(key, message, link);
      }
      return undefined;
    } finally {
      if (this._uploadShowTimer) clearTimeout(this._uploadShowTimer);
      this._uploadShowTimer = undefined;
      this._uploadAbort = undefined;
      this._assetEdit.upload = undefined;
      this._render();
    }
  }

  /** The pre-check message for a file over the shared ceiling, else undefined. */
  private _uploadSizeError(file: File): string | undefined {
    if (file.size <= MAX_DOCUMENT_BYTES) return undefined;
    return t('doc.uploadTooLargeLocal', {
      name: file.name,
      size: this._formatBytes(file.size),
      limit: this._formatBytes(MAX_DOCUMENT_BYTES),
    });
  }

  /** Map an upload failure onto localized user-facing text (plus an optional docs link). */
  private _uploadErrorMessage(
    e: api.UploadError,
    file: File,
  ): { message: string; link?: string } {
    // A 413 with no Home Keeper message body means a reverse proxy in front of HA
    // rejected the upload (its request-body limit) — guide the user to the fix.
    if (e?.status === 413 && !e.serverMessage) {
      return { message: t('doc.uploadTooLargeProxy'), link: DOCS_UPLOAD_413_URL };
    }
    if (!e?.status) {
      // No HTTP status at all. If the body was still going out, the connection was cut
      // mid-upload — classically a proxy body limit, which closes rather than replying,
      // so the browser never sees the 413. Offer that fix without asserting it.
      if ((e?.bytesSent ?? 0) > 0 && e.bytesSent! < file.size) {
        return { message: t('doc.uploadNetworkOrProxy'), link: DOCS_UPLOAD_413_URL };
      }
      return { message: t('doc.uploadNetworkError') };
    }
    return { message: t('doc.uploadFailed', { error: String(e?.message ?? '') }) };
  }

  /** Report an upload failure where the user is actually looking: inline next to the
   *  control, plus HA's toast (viewport-fixed, so it can't scroll out of sight). */
  private _failUpload(key: string, message: string, link?: string): void {
    this._assetEdit.uploadError = { key, message, link };
    this._toast(message);
    this._scrollToError = key;
    this._render();
  }

  /** Patch the live progress bar in place. Deliberately does *not* re-render: a render
   *  replaces the whole shadow root, which would thrash on every progress event. */
  private _onUploadProgress(key: string, p: api.UploadProgress): void {
    const state = this._assetEdit.upload;
    if (!state || state.key !== key) return;
    const before = this._uploadPercent(state);
    Object.assign(state, {
      loaded: p.loaded,
      total: p.total || state.total,
      indeterminate: p.indeterminate,
      sent: p.sent,
    });
    // Whole-percent changes only; a large upload fires progress events far more often
    // than the bar can meaningfully move.
    if (!p.sent && this._uploadPercent(state) === before) return;
    const host = this.shadowRoot?.getElementById('hk-upload');
    // Gone — a re-render happened. State is authoritative; the next render rebuilds it.
    if (!host) return;
    this._applyUploadProgress(host, state);
  }

  /** Percent complete, or undefined while indeterminate. */
  private _uploadPercent(state: UploadState): number | undefined {
    if (state.indeterminate || !state.total) return undefined;
    return Math.min(100, Math.round((state.loaded / state.total) * 100));
  }

  /** Write a progress state onto an existing bar (shared by first render and updates). */
  private _applyUploadProgress(host: HTMLElement, state: UploadState): void {
    const pct = this._uploadPercent(state);
    const track = host.querySelector('.hk-upload-track');
    const fill = host.querySelector<HTMLElement>('.hk-upload-fill');
    const label = host.querySelector('.hk-upload-label');
    const bar = host.querySelector('#hk-upload-bar');
    if (track) track.classList.toggle('indeterminate', pct === undefined);
    if (fill && pct !== undefined) fill.style.width = `${pct}%`;
    if (bar) {
      // Screen readers announce a determinate bar by value; while indeterminate there
      // is no value to announce, so drop it and mark the region busy instead.
      if (pct === undefined) {
        bar.removeAttribute('aria-valuenow');
        bar.setAttribute('aria-busy', 'true');
      } else {
        bar.setAttribute('aria-valuenow', String(pct));
        bar.removeAttribute('aria-busy');
      }
    }
    if (label) label.textContent = this._uploadLabel(state);
  }

  /** The line under the bar: "manual.pdf · 42% · 4.2 MB of 10 MB", or a phase message
   *  while there's no percentage to show. */
  private _uploadLabel(state: UploadState): string {
    if (state.sent) return t('doc.uploadFinishing', { name: state.filename });
    const pct = this._uploadPercent(state);
    if (pct === undefined) return t('doc.uploadPreparing', { name: state.filename });
    return t('doc.uploadProgress', {
      name: state.filename,
      pct: String(pct),
      done: this._formatBytes(state.loaded),
      total: this._formatBytes(state.total),
    });
  }

  /** Render the progress bar and/or the inline error for one upload control. Called
   *  from both upload call sites so they stay identical. */
  private _renderUploadStatus(host: HTMLElement, key: string): void {
    const state = this._assetEdit.upload;
    if (state?.key === key && state.visible) {
      const wrap = document.createElement('div');
      wrap.className = 'hk-upload';
      wrap.id = 'hk-upload';
      const bar = document.createElement('div');
      bar.id = 'hk-upload-bar';
      bar.setAttribute('role', 'progressbar');
      bar.setAttribute('aria-valuemin', '0');
      bar.setAttribute('aria-valuemax', '100');
      bar.setAttribute('aria-label', t('doc.uploadPreparing', { name: state.filename }));
      const track = document.createElement('div');
      track.className = 'hk-upload-track';
      const fill = document.createElement('div');
      fill.className = 'hk-upload-fill';
      track.appendChild(fill);
      bar.appendChild(track);
      // No aria-live on the bar: announcing every percent tick would flood a screen
      // reader. The completion toast and the role="alert" error carry the outcome.
      const label = document.createElement('div');
      label.className = 'hk-upload-label';
      const cancel = document.createElement('ha-button');
      cancel.textContent = t('btn.cancelUpload');
      // Safe at any point: the backend only writes the blob once the whole body has
      // been parsed, so an aborted upload leaves nothing behind.
      cancel.addEventListener('click', () => this._uploadAbort?.abort());
      wrap.append(bar, label, cancel);
      this._applyUploadProgress(wrap, state);
      host.appendChild(wrap);
    }
    const failure = this._assetEdit.uploadError;
    if (failure?.key === key) {
      const alert = this._errorAlert(failure.message, failure.link);
      alert.id = `hk-upload-err-${key}`;
      host.appendChild(alert);
    }
  }

  /** An error alert with an optional "Learn more" link. */
  private _errorAlert(message: string, link?: string): HTMLElement {
    const err = document.createElement('ha-alert');
    err.setAttribute('alert-type', 'error');
    err.textContent = message;
    if (link) {
      const a = document.createElement('a');
      a.href = link;
      a.target = '_blank';
      a.rel = 'noopener';
      a.textContent = t('btn.learnMore');
      a.style.marginInlineStart = '8px';
      err.appendChild(a);
    }
    return err;
  }

  private _renderMetadataEditor(inner: HTMLElement): void {
    const entries = this._assetEdit.asset?.metadata || [];
    const { details, body } = this._collapsibleSection(t('section.metadata'), 'metadata', entries.length);
    inner.appendChild(details);
    entries.forEach((m, i) => {
      const box = document.createElement('div');
      box.className = 'hk-part';
      box.dataset.idx = String(i);
      const head = document.createElement('div');
      head.className = 'hk-part-head';
      head.innerHTML = `<span class="label">${escapeHTML(t('section.meta_n', { n: i + 1 }))}</span>`;
      const del = document.createElement('ha-icon-button');
      del.className = 'part-del';
      del.setAttribute('label', t('btn.removeField'));
      this._setIcon(del, MDI_DELETE);
      del.addEventListener('click', () => {
        const dlabel = m.label
          ? t('confirm.removeNamed', { name: m.label })
          : t('confirm.removeField', { n: i + 1 });
        this._openConfirmDialog(dlabel, () => {
          const list = this._assetEdit.asset?.metadata || [];
          this._assetEdit.asset!.metadata = list.filter((_, j) => j !== i);
        });
      });
      head.appendChild(del);
      box.appendChild(head);

      const form = this._makeForm(
        this._metadataSchema(m),
        {
          type: m.type ?? 'text',
          label: m.label ?? '',
          value: m.value ?? '',
          track: Boolean(m.track),
        },
        (value) => {
          const prevType = this._assetEdit.asset?.metadata?.[i]?.type;
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
          const list = [...(this._assetEdit.asset?.metadata || [])];
          list[i] = updated;
          this._assetEdit.asset!.metadata = list;
          // Re-render when the type changes so the value control (and the date
          // "track" toggle) swaps to match.
          if (newType !== prevType) this._render();
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
      const list = [...(this._assetEdit.asset?.metadata || [])];
      list.push(entry);
      this._assetEdit.asset!.metadata = list;
      this._render();
    };
    const seedRow = document.createElement('div');
    seedRow.className = 'hk-meta-seeds';
    for (const s of seeds) {
      const b = document.createElement('ha-button');
      b.textContent = s.label;
      b.addEventListener('click', () => addEntry({ type: s.type, label: s.label, value: '' }));
      seedRow.appendChild(b);
    }
    const custom = document.createElement('ha-button');
    custom.textContent = t('btn.addField');
    custom.addEventListener('click', () => addEntry({ type: 'text', label: '', value: '' }));
    seedRow.appendChild(custom);
    body.appendChild(seedRow);
  }

  private _renderPartsEditor(inner: HTMLElement): void {
    const parts = this._assetEdit.asset?.parts || [];
    const { details, body } = this._collapsibleSection(t('section.parts'), 'parts', parts.length);
    inner.appendChild(details);
    parts.forEach((p, i) => {
      const box = document.createElement('div');
      box.className = 'hk-part';
      box.dataset.idx = String(i);
      const head = document.createElement('div');
      head.className = 'hk-part-head';
      head.innerHTML = `<span class="label">${escapeHTML(t('section.part_n', { n: i + 1 }))}</span>`;
      const del = document.createElement('ha-icon-button');
      del.className = 'part-del';
      del.setAttribute('label', t('btn.removePart'));
      this._setIcon(del, MDI_DELETE);
      del.addEventListener('click', () => {
        const dlabel = p.name
          ? t('confirm.removeNamed', { name: p.name })
          : t('confirm.removePart', { n: i + 1 });
        this._openConfirmDialog(dlabel, () => {
          const list = this._assetEdit.asset?.parts || [];
          this._assetEdit.asset!.parts = list.filter((_, j) => j !== i);
        });
      });
      head.appendChild(del);
      box.appendChild(head);

      // Declared before the form so its value-changed handler can feed it; attached
      // below, after the form, so it renders directly under the part's fields.
      let partNotePreview: MarkdownPreview | null = null;
      const form = this._makeForm(
        this._partSchema(p),
        {
          part_name: p.name ?? '',
          part_number: p.part_number ?? '',
          type: p.type ?? 'consumable',
          vendor: p.vendor ?? '',
          cost: p.cost ?? undefined,
          part_url: p.url ?? '',
          notes: p.notes ?? '',
          stock: p.stock ?? undefined,
          reorder_at: p.reorder_at ?? undefined,
          stock_unit: p.stock_unit ?? '',
          consume_quantity: p.consume_quantity ?? undefined,
          create_buy_task: p.create_buy_task ?? false,
          restock_quantity: p.restock_quantity ?? undefined,
          replace_interval: p.replace_interval ?? undefined,
          replace_unit: p.replace_unit ?? 'months',
          last_replaced: p.last_replaced ?? undefined,
        },
        (value) => {
          const prevPart = this._assetEdit.asset?.parts?.[i];
          const prevType = prevPart?.type;
          // These fields gate which others render (see _partSchema): the reorder
          // threshold reveals the auto-buy toggle, and the toggle reveals the restock
          // quantity. Re-render when one of them flips so the dependent field appears.
          const prevHasReorder = prevPart?.reorder_at != null;
          const prevBuy = Boolean(prevPart?.create_buy_task);
          // Tracking stock at all is what reveals the per-completion amount.
          const prevTracksStock = prevPart?.stock != null;
          partNotePreview?.update(String(value.notes ?? ''));
          const updated: Part = {
            id: p.id,
            // The last-replaced date is only editable for wear items; preserve any
            // existing value when the part is a consumable (no field shown).
            last_replaced:
              value.type === 'wear'
                ? value.last_replaced
                  ? String(value.last_replaced)
                  : null
                : (p.last_replaced ?? null),
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
            // Not editable in this form (upload-only — see _renderPartFile); carry
            // the current known values forward so the in-progress client copy stays
            // accurate between saves. The server ignores whatever this sends anyway
            // and always restores the stored values (see assets._merge_parts), but
            // without this the local UI would show "no file" the moment any other
            // field on this part changes, even though nothing was actually lost.
            file_name: p.file_name ?? null,
            file_content_type: p.file_content_type ?? null,
            file_size: p.file_size ?? null,
          };
          const list = [...(this._assetEdit.asset?.parts || [])];
          list[i] = updated;
          this._assetEdit.asset!.parts = list;
          const nowHasReorder = updated.reorder_at != null;
          if (
            value.type !== prevType ||
            nowHasReorder !== prevHasReorder ||
            (updated.stock != null) !== prevTracksStock ||
            Boolean(updated.create_buy_task) !== prevBuy
          )
            this._render();
        },
      );
      box.appendChild(form);
      partNotePreview = this._attachNotePreview(box, String(p.notes ?? ''));
      this._renderPartFile(box, p, i);

      if (p.type === 'wear') {
        const note = document.createElement('div');
        note.className = 'hk-meta';
        note.textContent = t('part.wearHint');
        box.appendChild(note);
      }
      body.appendChild(box);
    });

    const add = document.createElement('ha-button');
    add.id = 'a-add-part';
    add.textContent = t('btn.addPart');
    add.addEventListener('click', () => {
      const list = [...(this._assetEdit.asset?.parts || [])];
      list.push({ name: '', type: 'consumable' });
      this._assetEdit.asset!.parts = list;
      this._render();
    });
    body.appendChild(add);
  }

  /** A part's single attached file: a card (icon, filename · size · type, Open /
   *  Remove) when one is attached; otherwise an "Attach file" upload button — only
   *  once both the appliance and this part row are saved (a part gets its id from
   *  the backend, so a brand-new unsaved part has none yet to upload against). */
  private _renderPartFile(box: HTMLElement, p: Part, i: number): void {
    const assetId = this._assetEdit.asset?.id;
    if (p.file_name) {
      const card = document.createElement('div');
      card.className = 'hk-doc-card';

      const ic = document.createElement('div');
      ic.className = 'hk-doc-ic';
      const icon = document.createElement('ha-icon');
      icon.setAttribute('icon', 'mdi:paperclip');
      ic.appendChild(icon);

      const main = document.createElement('div');
      main.className = 'hk-doc-main';
      const name = document.createElement('div');
      name.className = 'hk-doc-name';
      name.textContent = p.file_name;
      main.appendChild(name);
      const subText = this._partFileSubtitle(p);
      if (subText) {
        const sub = document.createElement('div');
        sub.className = 'hk-doc-sub';
        sub.textContent = subText;
        main.appendChild(sub);
      }

      const actions = document.createElement('div');
      actions.className = 'hk-doc-actions';
      const del = document.createElement('ha-icon-button');
      del.setAttribute('label', t('btn.removePartFile'));
      this._setIcon(del, MDI_DELETE);
      del.addEventListener('click', () => void this._removePartFile(p, i));
      // Same native-anchor treatment as an uploaded document (see `_openFileAnchor`).
      actions.append(
        this._openFileAnchor(assetId && p.id ? { kind: 'part', assetId, id: p.id } : undefined, () =>
          this._openPartFile(p),
        ),
        del,
      );

      card.append(ic, main, actions);
      box.appendChild(card);
      return;
    }
    if (!assetId || !p.id) return;
    const key = uploadKeyPart(p.id);
    const upload = document.createElement('ha-button');
    upload.textContent = this._uploadButtonLabel(key, t('btn.attachFile'));
    const picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'application/pdf,image/png,image/jpeg,image/webp,image/gif';
    picker.style.display = 'none';
    picker.addEventListener('change', () => {
      const file = picker.files?.[0];
      if (file) void this._uploadPartFile(p, i, file);
      picker.value = '';
    });
    upload.addEventListener('click', () => picker.click());
    if (this._assetEdit.upload) upload.setAttribute('disabled', '');
    const row = document.createElement('div');
    row.className = 'hk-meta-seeds';
    row.append(upload, picker);
    box.appendChild(row);
    this._renderUploadStatus(box, key);
  }

  /** An upload button reads "Uploading…" while it owns the in-flight upload. Every
   *  upload button is disabled meanwhile — only one upload runs at a time. */
  private _uploadButtonLabel(key: string, idle: string): string {
    return this._assetEdit.upload?.key === key ? t('btn.uploading') : idle;
  }

  /** Details line for a part's attached file: filename · size · type. */
  private _partFileSubtitle(p: Part): string {
    const parts: string[] = [];
    const size = this._formatBytes(p.file_size ?? undefined);
    if (size) parts.push(size);
    const type = this._documentTypeLabel(p.file_content_type ?? undefined);
    if (type) parts.push(type);
    return parts.join(' · ');
  }

  private _openPartFile(p: Part): void {
    const assetId = this._assetEdit.asset?.id;
    if (this._hass && assetId) void openPartFile(this._hass, assetId, p);
  }

  private async _uploadPartFile(p: Part, i: number, file: File): Promise<void> {
    const assetId = this._assetEdit.asset?.id;
    if (!this._hass || !assetId || !p.id) return;
    const hass = this._hass;
    const partId = p.id;
    const updated = await this._runUpload(uploadKeyPart(partId), file, (opts) =>
      api.uploadPartFile(hass, assetId, partId, file, undefined, opts),
    );
    if (!updated) return;
    const list = [...(this._assetEdit.asset?.parts || [])];
    list[i] = {
      ...list[i],
      file_name: updated.file_name,
      file_content_type: updated.file_content_type,
      file_size: updated.file_size,
    };
    this._assetEdit.asset!.parts = list;
    this._render();
  }

  private async _removePartFile(p: Part, i: number): Promise<void> {
    const assetId = this._assetEdit.asset?.id;
    if (!this._hass || !assetId || !p.id) return;
    try {
      await api.removePartFile(this._hass, assetId, p.id);
      const list = [...(this._assetEdit.asset?.parts || [])];
      list[i] = { ...list[i], file_name: null, file_content_type: null, file_size: null };
      this._assetEdit.asset!.parts = list;
      this._render();
    } catch (err) {
      this._setAssetError(String((err as { message?: string })?.message || err));
      this._render();
    }
  }

  private _section(title: string): HTMLElement {
    const el = document.createElement('div');
    el.className = 'hk-section';
    el.textContent = title;
    return el;
  }

  /** A collapsible `<details>` section for the advanced parts of the appliance editor,
   *  so a first appliance isn't a wall of fields. Defaults open when it already holds
   *  entries (editing existing data) and collapsed when empty. Returns the body to
   *  fill; the caller appends the returned `details` to its container. */
  private _collapsibleSection(
    title: string,
    key: string,
    count: number,
  ): { details: HTMLDetailsElement; body: HTMLElement } {
    const details = document.createElement('details');
    details.className = 'hk-collapsible';
    // Respect a remembered choice; otherwise open when the section already has content.
    details.open = this._assetEdit.openSections?.[key] ?? count > 0;
    details.addEventListener('toggle', () => {
      (this._assetEdit.openSections ??= {})[key] = details.open;
    });
    const summary = document.createElement('summary');
    summary.innerHTML =
      `<span class="hk-section">${escapeHTML(title)}</span>` +
      (count ? `<span class="hk-section-count">${count}</span>` : '') +
      `<ha-icon icon="mdi:chevron-down" class="hk-section-chevron"></ha-icon>`;
    details.appendChild(summary);
    const body = document.createElement('div');
    details.appendChild(body);
    return { details, body };
  }

  /** Give an ha-icon-button its mdi icon via the native `path` property. */
  private _setIcon(button: HTMLElement, path: string): void {
    (button as HTMLElement & { path?: string }).path = path;
  }

  // ── completion-history rendering (inline in the detail page) ─────────────────
  private _historyBody(groups: HistoryGroup[]): string {
    const withAny = groups.filter((g) => (g.completions?.length ?? 0) > 0);
    if (!withAny.length) {
      return `<ha-alert alert-type="info">${escapeHTML(t('history.empty'))}</ha-alert>`;
    }
    const multi = withAny.length > 1;
    return withAny.map((g) => this._historyGroup(g, multi)).join('');
  }

  private _historyGroup(group: HistoryGroup, showHead: boolean): string {
    // Sort the completion objects (not just Dates) so each row keeps its `ts`
    // string for the per-row delete button.
    const comps = [...(group.completions || [])]
      .filter((c) => !Number.isNaN(new Date(c.ts).getTime()))
      .sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());
    const stats = completionStats(group.completions);
    const sub: string[] = [tn('history.count', stats.count)];
    if (stats.avgIntervalDays) sub.push(t('history.cadence', { days: stats.avgIntervalDays }));
    const archived = group.archived
      ? `<span class="hk-hist-archived">${escapeHTML(t('history.archived'))}</span>`
      : '';
    const head = showHead
      ? `<div class="hk-hist-head">${escapeHTML(group.name)}${archived}
           <span class="hk-hist-sub">${escapeHTML(sub.join(' · '))}</span></div>`
      : `<div class="hk-hist-head"><span class="hk-hist-sub">${escapeHTML(sub.join(' · '))}</span>${archived}</div>`;
    // Encode the deletion target on each trash button: a live task carries
    // `data-del-task`; an archived group carries `data-del-asset` + `data-del-arch`.
    const delAttrs = group.taskId
      ? `data-del-task="${escapeHTML(group.taskId)}"`
      : group.assetId
        ? `data-del-asset="${escapeHTML(group.assetId)}" data-del-arch="${escapeHTML(group.archivedTaskId || '')}"`
        : '';
    // Editing a completion's metadata only applies to a live task (the backend's
    // update_completion works on tasks, not an appliance's archived history).
    const editTask = !group.archived ? group.taskId : undefined;
    // The unit for any meter readings in this group, resolved once rather than per
    // row. An archived group has no live task, so its rows show a bare number.
    const unit = readingUnit(
      group.taskId ? this._tasks.find((x) => x.id === group.taskId) : undefined,
      this._hass,
    );
    const items = comps
      .map((c) => {
        const d = new Date(c.ts);
        const date = d.toLocaleDateString(undefined, {
          year: 'numeric',
          month: 'short',
          day: 'numeric',
        });
        const editBtn = editTask
          ? `<ha-icon-button class="hk-hist-edit" data-edit-task="${escapeHTML(editTask)}" data-ts="${escapeHTML(c.ts)}" label="${escapeHTML(t('btn.edit'))}"></ha-icon-button>`
          : '';
        // Moving a completion's date only applies to a live task, same as editing
        // its metadata — move_completion doesn't operate on archived history.
        const moveBtn = editTask
          ? `<ha-icon-button class="hk-hist-move" data-move-task="${escapeHTML(editTask)}" data-ts="${escapeHTML(c.ts)}" label="${escapeHTML(t('btn.moveDate'))}"></ha-icon-button>`
          : '';
        return `<li>
            <div class="hk-hist-row">
              <span class="date">${escapeHTML(date)}</span>
              <span class="when">${escapeHTML(this._relativeDay(d))}</span>
              <span class="hk-hist-actions">${moveBtn}${editBtn}<ha-icon-button class="hk-hist-del" ${delAttrs} data-ts="${escapeHTML(c.ts)}" label="${escapeHTML(t('btn.delete'))}"></ha-icon-button></span>
            </div>
            ${this._completionMeta(c, unit)}
          </li>`;
      })
      .join('');
    return `<div class="hk-hist-group">${head}<ul class="hk-hist-list">${items}</ul></div>`;
  }

  /**
   * Render a completion's recorded detail (reading / cost / who / note / photo).
   *
   * `unit` is resolved once per history group by the caller rather than looked up
   * here: a `Completion` is a bare history entry and knows nothing about the sensor
   * it came from, and an archived group has no live task to ask at all (its rows then
   * show a bare number, which is still the figure that matters).
   */
  private _completionMeta(c: Completion, unit = ''): string {
    const bits: string[] = [];
    // The meter reading leads: on a usage task it is the number the whole task is
    // measured in, and it is what the cost/who chips are context for.
    if (c.reading != null)
      bits.push(
        escapeHTML(
          t('completion.reading', {
            reading: `${round1(c.reading)}${unit ? ` ${unit}` : ''}`,
          }),
        ),
      );
    if (c.cost != null) bits.push(escapeHTML(this._formatCost(c.cost)));
    if (c.who) bits.push(escapeHTML(t('completion.by', { who: this._personName(c.who) })));
    const line = bits.length
      ? `<span class="hk-hist-chips">${bits.join(' · ')}</span>`
      : '';
    // A completion note renders as Markdown too, so it's a block (not a span) and
    // takes its own line under the cost/who chips.
    const note = c.note
      ? `<div class="hk-hist-note">${markdownBlock(c.note, 'hk-md-compact')}</div>`
      : '';
    // `photo` is caller-supplied (any string via home_keeper/complete_task) and was
    // rendered as a raw href — escapeHTML can't neutralise a `javascript:` URI in an
    // href, so a non-admin could plant a stored-XSS payload an admin clicks. Only
    // render the link/thumbnail when the URL is http(s) or a site-relative path (the
    // shape `ha-picture-upload` produces, e.g. `/api/image/serve/<id>/original`).
    const photo = isSafeImageUrl(c.photo)
      ? `<a href="${escapeHTML(c.photo)}" target="_blank" rel="noopener"><img class="hk-hist-photo" src="${escapeHTML(c.photo)}" alt="${escapeHTML(t('completion.photo'))}" /></a>`
      : '';
    if (!line && !note && !photo) return '';
    return `<div class="hk-hist-meta">${line}${note}${photo}</div>`;
  }

  /** Format a cost in the instance's configured currency (falls back to the number). */
  private _formatCost(amount: number): string {
    const currency = this._hass?.config?.currency;
    if (currency) {
      try {
        return new Intl.NumberFormat(this._hass?.language, {
          style: 'currency',
          currency,
        }).format(amount);
      } catch {
        /* fall through to a bare number */
      }
    }
    return String(amount);
  }

  /** Resolve a person entity id to its friendly name (falls back to the id). */
  private _personName(entityId: string): string {
    const friendly = this._hass?.states?.[entityId]?.attributes?.friendly_name;
    return typeof friendly === 'string' && friendly ? friendly : entityId;
  }

  /** Set the trash/pencil icons and wire each per-completion delete/edit button. */
  private _wireHistoryDeletes(root: ParentNode): void {
    root.querySelectorAll<HTMLElement>('.hk-hist-del').forEach((b) => {
      this._setIcon(b, MDI_DELETE);
      b.addEventListener('click', () => {
        const ts = b.dataset.ts;
        if (!ts) return;
        if (b.dataset.delTask) void this._deleteCompletion(b.dataset.delTask, ts);
        else if (b.dataset.delAsset)
          void this._deleteArchivedCompletion(b.dataset.delAsset, b.dataset.delArch || '', ts);
      });
    });
    root.querySelectorAll<HTMLElement>('.hk-hist-edit').forEach((b) => {
      this._setIcon(b, MDI_EDIT);
      b.addEventListener('click', () => {
        const ts = b.dataset.ts;
        const taskId = b.dataset.editTask;
        if (!ts || !taskId) return;
        const task = this._tasks.find((x) => x.id === taskId);
        const comp = task?.completions?.find((c) => c.ts === ts);
        if (task && comp) this._openCompletionEdit(task, comp);
      });
    });
    root.querySelectorAll<HTMLElement>('.hk-hist-move').forEach((b) => {
      this._setIcon(b, MDI_MOVE_DATE);
      b.addEventListener('click', () => {
        const ts = b.dataset.ts;
        const taskId = b.dataset.moveTask;
        if (!ts || !taskId) return;
        const task = this._tasks.find((x) => x.id === taskId);
        if (task) this._openMoveCompletion(task, ts);
      });
    });
  }

  /** "today" / "yesterday" / "N days ago" for a past completion date. */
  private _relativeDay(d: Date, now: Date = new Date()): string {
    const days = Math.round((now.getTime() - d.getTime()) / 86_400_000);
    if (days <= 0) return t('due.today');
    if (days === 1) return t('due.yesterday');
    return tn('due.days_ago', days);
  }
}
