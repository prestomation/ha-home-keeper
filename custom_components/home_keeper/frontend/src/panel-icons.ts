/**
 * The panel's static asset vocabulary: the MDI glyph paths it draws, the Home
 * Assistant components it waits for before the first paint, and the docs pages it
 * links out to. All of it is data — no logic, no imports, no dependency on the
 * panel's state — so it lives apart from the class that renders with it.
 *
 * `ha-svg-icon` takes a raw path (`.path = MDI_DELETE`); `ha-icon` takes a name
 * (`icon="mdi:open-in-new"`). Both forms appear here, suffixed `_ICON` when it is
 * the name rather than the path.
 *
 * The dashboard card draws the same open-in-new glyph on its document chips, so it
 * imports `MDI_OPEN_IN_NEW_ICON` from here rather than keeping a second copy of the
 * string. Everything else is the panel's alone.
 */

// mdi:devices — fallback icon when a device has no resolvable brand logo.
export const MDI_DEVICES =
  'M3,6H21V4H3A2,2 0 0,0 1,6V18A2,2 0 0,0 3,20H7V18H3V6M13,12H9V13.78C8.39,' +
  '14.33 8,15.11 8,16C8,16.89 8.39,17.67 9,18.22V20H13V18.22C13.61,17.67 14,' +
  '16.88 14,16C14,15.11 13.61,14.33 13,13.78V12M11,17.5A1.5,1.5 0 0,1 9.5,16A1.5,' +
  '1.5 0 0,1 11,14.5A1.5,1.5 0 0,1 12.5,16A1.5,1.5 0 0,1 11,17.5M22,8H16A1,1 0 0,' +
  '0 15,9V19A1,1 0 0,0 16,20H22A1,1 0 0,0 23,19V9A1,1 0 0,0 22,8M21,18H17V10H21V18Z';

// Docs page listing known companion / glue integrations (Settings → Companions
// blurb links here). Points at the User Guide's Settings page anchor, which the
// docs site generates from README.md's "Companions" section.
export const COMPANIONS_DOCS_URL =
  'https://prestomation.github.io/ha-home-keeper/docs/guide/settings#companions';

// User Guide page explaining sensor-based (usage-meter / threshold) tasks — the
// task form's help affordances link here. Generated from README.md's
// "Sensor-based tasks" section (slug `sensor-tasks`, see website/scripts/sync-docs.mjs).
export const SENSOR_DOCS_URL =
  'https://prestomation.github.io/ha-home-keeper/docs/guide/sensor-tasks';

// The User Guide itself — linked from the Settings rail's foot, next to the version,
// so "where do I read about this?" is answered from the page that raises the question.
export const DOCS_URL = 'https://prestomation.github.io/ha-home-keeper/docs/guide/';

// Docs section explaining a 413 from a reverse proxy in front of HA (see README
// "Large uploads (413)"). Linked from the upload error so users can self-serve the fix.
export const DOCS_UPLOAD_413_URL =
  'https://prestomation.github.io/ha-home-keeper/docs/guide/appliances#large-uploads-413';

// Components we rely on. They are part of HA's frontend bundle but some load
// lazily; wait for them (best-effort) before the first render so the panel
// doesn't flash un-upgraded custom elements.
export const REQUIRED_COMPONENTS = [
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
export const MDI_DELETE =
  'M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z';

// mdi:close — dismiss the edit drawer without saving.
export const MDI_CLOSE =
  'M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,' +
  '13.41L17.59,19L19,17.59L13.41,12L19,6.41Z';

// mdi:pencil — edit a single completion's metadata from the history list.
export const MDI_EDIT =
  'M20.71,7.04C21.1,6.65 21.1,6 20.71,5.63L18.37,3.29C18,2.9 17.35,2.9 16.96,' +
  '3.29L15.12,5.12L18.87,8.87M3,17.25V21H6.75L17.81,9.93L14.06,6.18L3,17.25Z';

// `ha-icon` name for the same glyph, used as the trailing "opens in a new tab" hint on
// a document row's link (the string-template rows take an icon name, not a path).
export const MDI_OPEN_IN_NEW_ICON = 'mdi:open-in-new';

// mdi:open-in-new — open a document (link or signed file URL) in a new tab.
export const MDI_OPEN_IN_NEW =
  'M14,3V5H17.59L7.76,14.83L9.17,16.24L19,6.41V10H21V3M19,19H5V5H12V3H5C3.89,' +
  '3 3,3.9 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V12H19V19Z';

// mdi:calendar-edit — move (re-timestamp) a single completion entry.
export const MDI_MOVE_DATE =
  'M19,19H5V8H19M16,1V3H8V1H6V3H5C3.89,3 3,3.9 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,' +
  '19V5C21,3.89 20.1,3 19,3H18V1M12.78,11.09L9,14.87L9,17H11.13L14.91,13.22L12.78,' +
  '11.09M16.31,10.44C16.5,10.25 16.5,9.94 16.31,9.75L15.16,8.6C14.97,8.41 14.66,8.41 ' +
  '14.47,8.6L13.44,9.63L15.28,11.47L16.31,10.44Z';

// mdi:autorenew — a wear item (replaced on a recurring schedule).
export const MDI_WEAR =
  'M12,6V9L16,5L12,1V4A8,8 0 0,0 4,12C4,13.57 4.46,15.03 5.24,16.26L6.7,14.8C6.25,' +
  '13.97 6,13 6,12A6,6 0 0,1 12,6M18.76,7.74L17.3,9.2C17.74,10.04 18,11 18,12A6,6 0 0,' +
  '1 12,18V15L8,19L12,23V20A8,8 0 0,0 20,12C20,10.43 19.54,8.97 18.76,7.74Z';

// mdi:package-variant-closed — a consumable spare kept in stock.
export const MDI_CONSUMABLE =
  'M21,16.5C21,16.88 20.79,17.21 20.47,17.38L12.57,21.82C12.41,21.94 12.21,22 12,22C11.79,' +
  '22 11.59,21.94 11.43,21.82L3.53,17.38C3.21,17.21 3,16.88 3,16.5V7.5C3,7.12 3.21,6.79 3.53,' +
  '6.62L11.43,2.18C11.59,2.06 11.79,2 12,2C12.21,2 12.41,2.06 12.57,2.18L20.47,6.62C20.79,' +
  '6.79 21,7.12 21,7.5V16.5M12,4.15L6.04,7.5L12,10.85L17.96,7.5L12,4.15M5,15.91L11,19.29V12.58L5,' +
  '9.21V15.91M19,15.91V9.21L13,12.58V19.29L19,15.91Z';
