/**
 * The panel's stylesheet — one `<style>` block, adopted whole by `_render` into the
 * shadow root. It is pure text with a single interpolation (`TASK_CARD_INLINE_CHIPS`,
 * declared here because the chip-overflow rules are written in terms of it), so it
 * lives in its own module rather than as 1,300 lines wedged between the panel's
 * imports and its class.
 */

/** How many descriptive chips a list row shows beside the task name before the rest
 *  collapse into a "+n". Two keeps the title line readable at any width; the hidden
 *  chips stay in the DOM (and on the task's detail page) rather than being dropped.
 *  Declared above STYLES because the stylesheet interpolates it. */
export const TASK_CARD_INLINE_CHIPS = 2;

export const STYLES = `
  /* ── Design tokens ─────────────────────────────────────────────────────────
     One vocabulary for every surface, so the panel reads as a single system
     rather than a pile of independently-styled sections.

     Every token resolves to a Home Assistant theme variable, or to a color-mix
     off one. Nothing here is a literal colour: the design comp was drawn in HA's
     default *light* palette, and hard-coding those hexes would break dark mode
     and every custom theme. The soft/line variants exist because HA publishes a
     semantic colour but no tint of it, and a 12%-over-surface mix reads the same
     way in both themes (in dark, the surface it mixes into is dark, so the tint
     darkens with it instead of glowing).

     --hk-tap is the WCAG 2.5.5 minimum touch target, used by the controls that
     shrink on desktop but must stay thumb-sized on a phone. */
  :host {
    --hk-accent: var(--primary-color);
    --hk-accent-fg: var(--text-primary-color, #fff);
    --hk-accent-soft: color-mix(in srgb, var(--primary-color) 12%, var(--card-background-color, #fff));
    --hk-accent-line: color-mix(in srgb, var(--primary-color) 45%, transparent);
    --hk-accent-ink: color-mix(in srgb, var(--primary-color) 58%, var(--primary-text-color));
    --hk-danger: var(--error-color, #db4437);
    --hk-danger-soft: color-mix(in srgb, var(--error-color, #db4437) 12%, var(--card-background-color, #fff));
    --hk-danger-ink: color-mix(in srgb, var(--error-color, #db4437) 58%, var(--primary-text-color));
    --hk-warn: var(--warning-color, #ffa600);
    --hk-warn-soft: color-mix(in srgb, var(--warning-color, #ffa600) 14%, var(--card-background-color, #fff));
    --hk-warn-ink: color-mix(in srgb, var(--warning-color, #ffa600) 58%, var(--primary-text-color));
    --hk-ok: var(--success-color, #43a047);
    --hk-ok-soft: color-mix(in srgb, var(--success-color, #43a047) 14%, var(--card-background-color, #fff));
    --hk-ok-ink: color-mix(in srgb, var(--success-color, #43a047) 58%, var(--primary-text-color));
    --hk-surface: var(--card-background-color, #fff);
    --hk-page: var(--secondary-background-color);
    --hk-line: var(--divider-color);
    --hk-line-soft: color-mix(in srgb, var(--divider-color) 55%, transparent);
    --hk-ink: var(--primary-text-color);
    --hk-ink-2: var(--secondary-text-color);
    --hk-r-card: 12px;
    --hk-r-row: 10px;
    --hk-r-btn: 8px;
    --hk-r-pill: 999px;
    --hk-tap: 44px;
    --hk-shadow-card: 0 1px 3px rgba(0,0,0,.08);
    --hk-shadow-float: 0 4px 18px rgba(0,0,0,.16);
    display: block;
  }

  /* An uppercase micro-label above a group of related controls. The comp uses
     this on every board — form sections, list group headers, callout captions —
     so it is one class rather than five near-identical rules. */
  .hk-eyebrow {
    font-size: 0.69rem; font-weight: 700; letter-spacing: 0.09em;
    text-transform: uppercase; color: var(--hk-ink-2);
  }
  .hk-eyebrow.accent { color: var(--hk-accent-ink); }

  /* Fields that only exist because of a choice made above them, indented behind a
     rule so the dependency is visible rather than implied by ordering. Used by the
     task form's recurrence fields and by Settings -> problem-sensor exclusions. */
  .hk-indent { display: flex; gap: 14px; }
  .hk-indent::before {
    content: ''; flex: none; width: 3px; border-radius: 2px;
    background: var(--hk-accent-line);
  }
  .hk-indent-body { flex: 1; min-width: 0; }
  .hk-indent-head { margin-bottom: 10px; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
  .hk-indent-note { font-size: 0.78rem; color: var(--hk-ink-2); }

  .hk-toolbar {
    display: flex; align-items: center; gap: 12px; height: 56px;
    padding: 0 16px;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, var(--text-primary-color, #fff));
    --mdc-icon-button-size: 40px;
    box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0,0,0,.1));
  }
  .hk-toolbar-title { font-size: 1.25rem; font-weight: 400; flex: 1; }
  /* The shell is the page's max-width container so the drawer can be a flex sibling
     of the content column rather than an overlay on top of it.

     Wider than the old 920px: a filter row, a list and a 472px drawer side by side
     do not fit in 920. The Settings column caps itself lower (820px) because long
     prose is what it holds. */
  .hk-shell { display: flex; align-items: flex-start; max-width: 1200px; margin: 0 auto; }
  .hk-wrap { padding: 16px; flex: 1 1 auto; min-width: 0; }

  /* ── Edit drawer ───────────────────────────────────────────────────────────
     Sticky, not fixed: sticky is positioned by its own scroll container, so it
     survives whatever transformed or contained ancestor Home Assistant wraps a
     custom panel in — the same reason the confirm scrim is appended to the body
     rather than positioned from in here.

     An empty drawer takes no space at all, so a closed one cannot leave a gutter
     down the side of the list.

     The column and the sticky panel are two elements on purpose: the column
     stretches to the shell's full height so it reads as a column all the way down a
     long list, while the panel inside it is what sticks. Making the column itself
     sticky would size it to the viewport, leaving a bare gap beside everything
     below the fold. */
  /* A closed drawer is removed from the layout outright rather than collapsed to
     zero width: a zero-width box still carries a sticky, scrollable child, which is
     enough to take part in sizing the page. */
  .hk-drawer { display: none; }
  .hk-drawer[data-open] {
    display: block; flex: 0 0 auto; align-self: stretch;
    width: clamp(340px, 40vw, 472px);
    border-left: 1px solid var(--hk-line);
    background: var(--hk-surface);
    box-shadow: -8px 0 24px color-mix(in srgb, var(--hk-ink) 12%, transparent);
  }
  .hk-drawer-sticky {
    position: sticky; top: 0; max-height: 100vh;
    display: flex; flex-direction: column;
    overflow-y: auto; overscroll-behavior: contain;
  }
  .hk-drawer ha-card.hk-form-card {
    margin: 0; border: 0; border-radius: 0;
    --ha-card-box-shadow: none; --ha-card-border-width: 0;
    display: flex; flex-direction: column; min-height: 100%;
  }
  /* The drawer's own header stays put while the form scrolls under it, so Save is
     always one tap away however long the form is. */
  .hk-drawer-head {
    position: sticky; top: 0; z-index: 2;
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px; border-bottom: 1px solid var(--hk-line);
    background: var(--hk-surface);
  }
  .hk-drawer-close { flex: none; --mdc-icon-button-size: 40px; color: var(--hk-ink-2); }
  .hk-drawer-titles { flex: 1; min-width: 0; }
  .hk-drawer-title {
    font-size: 1rem; font-weight: 500; display: flex; align-items: center; gap: 6px;
  }
  .hk-drawer-sub {
    font-size: 0.78rem; color: var(--hk-ink-2); margin-top: 1px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .hk-drawer-head ha-button { flex: none; }
  /* Destructive and navigational actions, as far from Save as the drawer allows. */
  .hk-drawer-foot {
    margin-top: auto; display: flex; align-items: center; gap: 8px;
    padding: 10px 14px; border-top: 1px solid var(--hk-line);
    position: sticky; bottom: 0; z-index: 2; background: var(--hk-surface);
  }
  .hk-drawer-foot-spacer { flex: 1; }
  /* With the drawer open the list recedes, except the row being edited — which is
     the point of editing beside the list rather than on top of it.

     The recession is *only* visual. Everything stays clickable: with the old inline
     form open the whole list was live, so disabling it here would take away marking
     another task done, opening another row, and collapsing a group — a regression
     dressed up as a redesign. Clicking away discards an open form, but it did that
     before this change too, and quietly fixing it is not a restyle's job.

     The dimming is applied per element rather than to the whole column: opacity
     creates a stacking context, so a fully-opaque child of a faded parent is still
     faded — the edited row could never have been exempted that way.

     A detail page is exempt from all of it. There the drawer edits the one thing the
     page is about, and the page is the context for the edit — its history, its notes,
     its parts. Dimming it would be dimming the reason the form is open here. */
  .hk-shell-drawer .hk-wrap:not([data-detail]) > *:not(#hk-list),
  .hk-shell-drawer .hk-wrap:not([data-detail]) #hk-list > ha-alert,
  .hk-shell-drawer .hk-wrap:not([data-detail]) #hk-list .hk-group-head,
  .hk-shell-drawer .hk-wrap:not([data-detail]) #hk-list ha-card:not(.hk-editing) {
    opacity: 0.72;
  }
  /* .hk-editing lights the row the drawer is editing while the rest of the list
     recedes. It is staged, not live: the class is only ever set when the drawer edits
     an existing object from a *list*, and today the only way into the drawer is
     .d-edit on an object's own page — so no list ever has a lit row, and neither this
     rule nor _mountDrawerForm's scrollIntoView fires. Kept deliberately: a row-level
     Edit affordance would make all of it live at once. Don't delete it as dead code
     without deciding against that first. */
  .hk-shell-drawer .hk-wrap:not([data-detail]) #hk-list ha-card.hk-editing {
    border: 2px solid var(--hk-accent);
    --ha-card-border-radius: var(--hk-r-row);
    box-shadow: 0 2px 12px color-mix(in srgb, var(--hk-accent) 28%, transparent);
  }
  /* An appliance is read beside its list, and the form is a third column the shell
     has no room for. The list steps aside for as long as the form is open — the same
     move it makes below 1000px, where there was never room for it either.

     Only where the drawer is a column: below 1150px it is a sheet over the whole
     page, so there is nothing to make room for, and this would hide the list for a
     narrow reader who closes the sheet. Stated as a min-width rather than undone in
     the sheet query, because "no third column to fit" is what the rule is about. */
  @media (min-width: 1151px) {
    .hk-shell-drawer .hk-wrap[data-detail="asset"] .hk-master,
    .hk-shell-drawer .hk-wrap[data-detail="asset"] .hk-master-controls { display: none; }
  }
  ha-tab-group { margin-bottom: 16px; }
  ha-card.hk-card { margin-bottom: 12px; position: relative; }
  .hk-card-row {
    display: flex; align-items: center; gap: 14px; padding: 13px 16px;
  }
  .hk-card-row .grow { flex: 1; min-width: 0; }
  .hk-name {
    font-weight: 500; display: flex; align-items: center; gap: 8px;
    flex-wrap: wrap;
  }
  .hk-meta { color: var(--hk-ink-2); font-size: 0.85rem; margin-top: 2px; }
  /* A finished one-off is struck through and faded wherever it appears. Group by
     Status tucked it into a collapsed section, but every other grouping left it
     mid-list looking like work still to do — and which grouping you chose should not
     change what appears to be in your active list. Faded per element rather than on
     the row: opacity on the card would make a stacking context and drag the status
     pill and the chips down with it. */
  .hk-card.hk-task-done .hk-name { text-decoration: line-through; opacity: 0.62; }
  .hk-card.hk-task-done .hk-meta { opacity: 0.62; }
  .hk-card-actions { display: flex; align-items: center; gap: 4px; }
  /* Any action the panel greys out rather than hides — a completion-blocked Done on a
     synced problem sensor, a Duplicate on a task Home Keeper doesn't own. The inner
     ha-button is natively disabled (greyed), and the wrapping span stays clickable so
     a tap can explain why. */
  .done-blocked-wrap, .hk-blocked-wrap { cursor: pointer; display: inline-flex; }
  .done-blocked-wrap ha-button, .hk-blocked-wrap ha-button { pointer-events: none; }
  /* Soft-tinted rather than solid: an overdue row already carries a red rule down its
     left edge, and a solid red block beside it read as an alarm on every line. The
     dark-red-on-pale-red pairing keeps the contrast while letting the row's own
     primary action stay the loudest thing in it. */
  ha-assist-chip.hk-overdue {
    --ha-assist-chip-container-color: var(--hk-danger-soft);
    --ha-assist-chip-filled-container-color: var(--hk-danger-soft);
    --md-assist-chip-label-text-color: var(--hk-danger-ink);
    --ha-assist-chip-label-text-color: var(--hk-danger-ink);
    --md-assist-chip-outline-color: transparent;
    --ha-assist-chip-outline-color: transparent;
    font-weight: 500;
  }
  /* "Managed by X" and "Auto-synced" carry no rule at all: they take the stock
     outlined chip, the same as the device chip beside them. They were a solid fill
     the same weight as "Add task", which put the loudest thing in a task row on the
     one piece of it you cannot act on — the eye reached the integration's name before
     the task's. The integration's own icon carries the identity instead, which
     _managedChip already renders. Filled white-on-mid-tone also measured 3.08:1. */
  /* Soft container, ink label — the same pairing the overdue chip uses. White on
     amber measured 1.96:1 and white on grey 1.88:1: not marginal, unreadable. */
  ha-assist-chip.hk-orphaned {
    --ha-assist-chip-container-color: var(--hk-warn-soft);
    --ha-assist-chip-filled-container-color: var(--hk-warn-soft);
    --md-assist-chip-label-text-color: var(--hk-warn-ink);
    --ha-assist-chip-label-text-color: var(--hk-warn-ink);
    --md-assist-chip-outline-color: transparent;
    font-weight: 500;
  }
  ha-assist-chip.hk-archived {
    --ha-assist-chip-container-color: var(--hk-page);
    --ha-assist-chip-filled-container-color: var(--hk-page);
    --md-assist-chip-label-text-color: var(--hk-ink-2);
    --ha-assist-chip-label-text-color: var(--hk-ink-2);
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
  /* The orphan banner's action is a long label in a narrow slot, which flex was
     shrinking until "Remove orphaned tasks" wrapped onto three lines. The label
     can't be shortened (it is translated in 17 locales), so stop the shrink. */
  .hk-orphan-banner ha-button { min-width: max-content; flex: none; }
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
  /* A heading between two runs of fields. ha-form renders its own rows and has no
     slot between them, so each section is its own form and these sit in the gaps. */
  .hk-form-section { margin: 20px 0 6px; }
  .hk-form-section:first-child { margin-top: 4px; }
  #hk-task-form .hk-indent { margin: 8px 0 4px; }
  #hk-task-form ha-form { display: block; }
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
    color: var(--hk-ink-2); font-size: 0.9rem;
    margin-bottom: 16px; line-height: 1.4;
  }
  /* What this section is currently set to, stated under its name so the page can be
     read without opening anything. */
  .hk-settings-value {
    color: var(--hk-ink); font-size: 0.88rem; margin: 2px 0 8px;
  }

  /* ── Settings: anchor rail beside the sections ─────────────────────────────
     Settings is a long page, and the questions people bring to it ("is the mirror
     on? do I have notifications?") are answered by the rail rather than by
     scrolling. It sticks; the column beside it scrolls with the page. */
  .hk-settings-layout { display: flex; align-items: flex-start; gap: 28px; }
  .hk-settings-rail {
    flex: 0 0 228px; position: sticky; top: 8px;
    display: flex; flex-direction: column; gap: 2px;
    max-height: calc(100vh - 24px); overflow: auto;
  }
  /* Long prose reads badly at full width, so the sections cap out well short of the
     shell — the rail takes the space that frees up. */
  .hk-settings-col { flex: 1 1 auto; min-width: 0; max-width: 820px; }
  .hk-rail-link {
    appearance: none; border: 0; background: transparent; cursor: pointer;
    font: inherit; font-size: 0.85rem; color: var(--hk-ink);
    text-align: start; padding: 10px 13px; border-radius: var(--hk-r-btn);
    display: flex; align-items: center; gap: 8px; width: 100%;
  }
  .hk-rail-link:hover { background: var(--hk-page); }
  .hk-rail-link[aria-current] {
    background: var(--hk-accent-soft); color: var(--hk-accent-ink); font-weight: 500;
  }
  .hk-rail-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .hk-rail-dot { flex: none; width: 7px; height: 7px; border-radius: 50%; }
  .hk-rail-dot.on { background: var(--hk-ok); }
  .hk-rail-dot.warn { background: var(--hk-warn); }
  .hk-rail-count {
    flex: none; font-size: 0.75rem; color: var(--hk-ink-2);
    font-variant-numeric: tabular-nums;
  }
  .hk-rail-foot {
    margin-top: 10px; padding: 10px 13px 2px; border-top: 1px solid var(--hk-line);
    display: flex; flex-direction: column; gap: 4px;
    font-size: 0.75rem; color: var(--hk-ink-2);
  }
  .hk-rail-foot a { color: var(--hk-accent); text-decoration: none; }
  .hk-rail-foot a:hover { text-decoration: underline; }
  .hk-settings-card .hk-indent { margin-top: 4px; }

  /* ── Settings: the phone's section index ───────────────────────────────────
     A screen with no room for the rail beside six expanded sections has no room
     for the six sections either, so it gets the list first and opens one at a
     time. Both are always in the DOM; the media queries far below decide which
     one is showing, so nothing in the panel's JS has to know the viewport. */
  .hk-settings-index { display: none; flex-direction: column; width: 100%; }
  /* The rail and the index both close with the version, so the page-wide one below
     them would say it twice on the Settings tab. */
  .hk-wrap[data-view="settings"] > .ver { display: none; }
  .hk-index-card { overflow: hidden; }
  .hk-index-row {
    appearance: none; border: 0; border-bottom: 1px solid var(--hk-line-soft);
    background: transparent; cursor: pointer; font: inherit; color: var(--hk-ink);
    text-align: start; width: 100%; padding: 12px 14px;
    display: flex; align-items: center; gap: 12px; min-height: var(--hk-tap);
  }
  .hk-index-row:last-child { border-bottom: 0; }
  .hk-index-row:hover { background: var(--hk-accent-soft); }
  .hk-index-text { flex: 1 1 auto; min-width: 0; }
  .hk-index-name { display: block; font-size: 0.95rem; font-weight: 500; }
  .hk-index-sum { display: block; font-size: 0.8rem; color: var(--hk-ink-2); }
  /* A triangle rather than a glyph, matching the tree chevron the panel already
     draws, so the row needs no icon font and no new asset. */
  .hk-index-chev {
    flex: none; width: 0; height: 0;
    border-top: 4px solid transparent; border-bottom: 4px solid transparent;
    border-left: 5px solid var(--hk-ink-2);
  }
  /* The header over one open section: the way back, and which one this is. */
  .hk-settings-backbar {
    display: none; align-items: center; gap: 10px; margin-bottom: 10px;
  }
  .hk-settings-backtitle { font-size: 1.05rem; font-weight: 500; }
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
  /* A profile's nested "Sync to a to-do list" group, and the chip on the collapsed
     profile row that names the list it syncs to. Deliberately not an .hk-item-card:
     a nested one would make every "how many rows?" selector ambiguous. */
  .hk-sync-group {
    border: 1px solid var(--divider-color); border-radius: 8px;
    margin-top: 4px; overflow: hidden;
  }
  .hk-sync-group > .hk-item-header .hk-item-name { font-weight: 400; }
  .hk-sync-group .hk-settings-intro { margin: 12px 0 0; }
  .hk-sync-chip {
    display: inline-flex; align-items: center; gap: 4px; flex: 0 1 auto;
    max-width: 45%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font-size: 0.8rem; font-weight: 400; color: var(--secondary-text-color);
    background: var(--secondary-background-color);
    border-radius: 999px; padding: 1px 8px;
  }
  .hk-item-actions { display: flex; justify-content: flex-end; gap: 8px; }
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
  /* Autosave status, beside the name of the card that saved. Quiet by default — it
     reports something the user did not ask about — and only coloured when it needs
     acting on. It replaces a toast, so it must not take a line of its own or push the
     header around: no background, no border, and it never grows or shrinks. */
  .hk-save-status {
    display: none; font-size: 0.8rem; color: var(--secondary-text-color);
    font-weight: 400; flex: 0 0 auto; white-space: nowrap;
  }
  /* The element is always in the header so it can announce its own changes, but it
     takes no room until the card has actually saved: an empty flex item would still
     draw the parent's gap and shift every header that has never been saved. */
  .hk-save-status.on { display: inline; }
  .hk-save-status.failed { color: var(--error-color); font-weight: 500; }
  .hk-section-chevron {
    color: var(--secondary-text-color); flex: 0 0 auto;
    transition: transform 0.2s ease; transform: rotate(-90deg);
  }
  .hk-section-chevron.open { transform: rotate(0deg); }
  /* Soft container, ink label — the pairing the overdue and orphaned chips already
     use. White on the mid-tone success fill measured 3.30:1. The suggested chip moves
     with it: the two sit side by side in the Companions list, and fixing only one
     would read as the other being broken. */
  ha-assist-chip.hk-comp-connected {
    --ha-assist-chip-container-color: var(--hk-ok-soft);
    --ha-assist-chip-filled-container-color: var(--hk-ok-soft);
    --md-assist-chip-label-text-color: var(--hk-ok-ink);
    --ha-assist-chip-label-text-color: var(--hk-ok-ink);
    --md-assist-chip-outline-color: transparent;
    --ha-assist-chip-outline-color: transparent;
    font-weight: 500;
  }
  ha-assist-chip.hk-comp-suggested {
    --ha-assist-chip-container-color: var(--hk-warn-soft);
    --ha-assist-chip-filled-container-color: var(--hk-warn-soft);
    --md-assist-chip-label-text-color: var(--hk-warn-ink);
    --ha-assist-chip-label-text-color: var(--hk-warn-ink);
    --md-assist-chip-outline-color: transparent;
    --ha-assist-chip-outline-color: transparent;
    font-weight: 500;
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
  /* Each part answers the same three questions — how often, when last, how many
     spares — so each gets its own cell and they always appear in that order. The
     comp draws this as a five-column table; in the real panel the appliance list
     sits beside the detail, leaving roughly 700px of pane, which is not enough for
     five columns without wrapping "Every 12 months" onto two lines. (Nor would a
     per-row grid line up: each row is its own grid container, so content-sized
     columns are sized per row.) Fixed order in a wrapping row keeps what the table
     was for — reading the same fact in the same place on every part. */
  .hk-part-cell { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; min-width: 0; }
  .hk-part-cell:empty { display: none; }
  /* How much of the reorder point is left. "1 of 2" is a number to work out, and a
     half-empty amber bar is a glance.

     Qualified with .hk-meter so these beat the generic meter rules further down the
     sheet: on their own they tie on specificity and lose to whichever comes last,
     which is how the spares bar was drawing in the accent colour instead of saying
     anything about the stock level. */
  .hk-meter.hk-part-meter { margin: 0; width: 72px; height: 5px; flex: none; }
  .hk-meter.hk-part-meter > span { background: var(--hk-ok); }
  .hk-meter.hk-part-meter.low > span { background: var(--hk-warn); }
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
  .hk-loading { display: flex; justify-content: center; padding: 48px 0; }
  .ver { color: var(--secondary-text-color); font-size: 0.7rem; text-align: right; margin-top: 16px; }
  .hk-card-row .grow.clickable { cursor: pointer; }
  /* A list row is a flat bordered card, not a floating one — a page of shadows reads
     as noise. Status lives in the left rule, so the radius opens on that edge. */
  ha-card.hk-card {
    --ha-card-box-shadow: none;
    --ha-card-border-radius: var(--hk-r-row);
    margin-bottom: 8px;
  }
  ha-card.hk-card.overdue {
    border-left: 3px solid var(--hk-danger);
    --ha-card-border-radius: 0 var(--hk-r-row) var(--hk-r-row) 0;
  }
  /* A task row reads left to right: what it is, what qualifies it, how late it is,
     what to do about it.

     The chips sit beside the title but *outside* the row's clickable text block, not
     inside it. Nesting them in the opener put an interactive chip under the middle of
     a link that spans the row, so where a click landed depended on how long the task
     name happened to be. Keeping them a separate column means the text block is only
     ever the text, and a device chip is only ever the chip. */
  .hk-card-row.hk-row-task > .grow { flex: 0 1 auto; }
  .hk-row-spacer { flex: 1 1 auto; min-width: 8px; }
  .hk-name-text { min-width: 0; overflow-wrap: anywhere; }
  .hk-chips.hk-chips-inline {
    margin-top: 0; gap: 6px; flex-wrap: nowrap; flex: 0 1 auto;
    align-items: center; min-width: 0; overflow: hidden;
  }
  /* A chip is a qualifier, not the point of the row: when the column is too narrow to
     hold one honestly it steps aside rather than overlapping the status pill. Its
     content is never lost — the task's detail page lists every chip. */
  /* Not hidden while the drawer is open: the drawer only exists above 1150px, where
     the list still has the width to carry a chip, and hiding them changed the list
     into a different list at the moment it was meant to hold still. */
  .hk-chips.hk-chips-inline ha-assist-chip { --ha-assist-chip-container-height: 26px; }
  /* Everything past the second chip is folded behind the "+n" beside it. The chips
     stay in the DOM: this is a density decision about one row, not a decision to
     withhold what the task is tagged with — the detail page still lists them all. */
  /* The "+n" control is itself a child of this row, so it has to be exempted or the
     rule folds away the very thing that unfolds it. */
  .hk-chips.hk-chips-inline > *:nth-child(n + ${TASK_CARD_INLINE_CHIPS + 1}):not(.hk-chip-more) {
    display: none;
  }
  /* Unfolded: the row wraps to hold them all rather than pushing the status pill off.
     The selector mirrors the hide rule above rather than being simpler than it — a
     plain child selector loses the specificity tie and the chips stay folded. */
  .hk-chips.hk-chips-inline.hk-chips-open { flex-wrap: wrap; }
  .hk-chips.hk-chips-inline.hk-chips-open > *:nth-child(n + ${TASK_CARD_INLINE_CHIPS + 1}) {
    display: inline-flex;
  }
  /* A control, not a caption — several of the chips it hides are clickable. */
  .hk-chip-more {
    flex: none; appearance: none; border: 1px solid var(--hk-line);
    background: var(--hk-surface); cursor: pointer; font: inherit;
    font-size: 0.78rem; font-weight: 500; color: var(--hk-ink-2);
    font-variant-numeric: tabular-nums;
    border-radius: var(--hk-r-pill); padding: 3px 9px; line-height: 1.4;
  }
  .hk-chip-more:hover { background: var(--hk-page); color: var(--hk-ink); }
  .hk-chip-more:focus-visible { outline: 2px solid var(--hk-accent); outline-offset: 2px; }
  /* The due/overdue pill sits at the end of the row, next to the action it argues
     for, rather than among the descriptive chips. */
  .hk-status { flex: none; display: flex; align-items: center; }
  /* No outline on a status pill. A tonal Done and an outlined "Monitored" sat side by
     side at the same height and radius, and the one with the border was the one you
     could not press — enclosure now means pressable, and status reads as text.
     Scoped away from the overdue chip, which carries a colour of its own, so removing
     the outline does not also remove what the colour was saying. */
  .hk-status ha-assist-chip { --ha-assist-chip-container-height: 28px; }
  .hk-status ha-assist-chip:not(.hk-overdue) {
    --ha-assist-chip-outline-width: 0px;
    --md-assist-chip-outline-width: 0px;
    --ha-assist-chip-outline-color: transparent;
    --md-assist-chip-outline-color: transparent;
    --ha-assist-chip-container-color: var(--hk-page);
    --ha-assist-chip-filled-container-color: var(--hk-page);
  }
  /* Every tonal button, not just Done. HA's tonal label sits at 2.85:1 on its own
     fill — under the 4.5:1 for text and even the 3:1 for a control — so the label is
     restated from our own accent ink, which measures 6.02:1 on the same fill.
     ha-button exposes its inner button as part "base", and that is the only lever
     that reaches the label: every colour custom property it reads is a fill token.
     Keyed off the weight rather than a class so a button cannot opt out of it by
     being written somewhere new. */
  [data-hk-weight="secondary"]::part(base) { color: var(--hk-accent-ink); }
  /* …and Done additionally gets the ring, so the row's one control is drawn as one. */
  .done-btn { --ha-button-border-radius: var(--hk-r-pill); }
  .done-btn::part(base) { box-shadow: inset 0 0 0 1px var(--hk-accent-line); }
  ha-card.hk-card.hk-tree-child {
    margin-left: calc(var(--hk-tree-depth, 0) * 32px);
    border-left: 3px solid color-mix(in srgb, var(--primary-color) calc(40% + var(--hk-tree-depth, 0) * 15%), transparent);
    background: color-mix(in srgb, var(--primary-color) calc(var(--hk-tree-depth, 0) * 4%), var(--card-background-color, #fff));
  }
  .hk-tree-group { margin: 0; }
  .hk-tree-group:not(.hk-tree-open) > .hk-tree-children { display: none; }
  .hk-chevron {
    position: absolute;
    top: 8px;
    right: 8px;
    display: flex; align-items: center; justify-content: center;
    width: 24px; height: 24px;
    border-radius: 6px;
    cursor: pointer;
    background: var(--secondary-background-color);
    z-index: 1;
  }
  .hk-chevron:hover { background: var(--divider-color); }
  .hk-chevron::after {
    content: '';
    display: inline-block;
    width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid var(--secondary-text-color);
    transition: transform 0.15s ease;
  }
  .hk-tree-group:not(.hk-tree-open) .hk-chevron::after {
    transform: rotate(-90deg);
  }

  /* ── Filter / group-by controls ───────────────────────────────────────────
     One row: the scope pills lead, refinements follow, and the single primary
     action closes it. It wraps rather than scrolls when the viewport can't hold
     it, so no control is ever unreachable. */
  .hk-controls {
    display: flex; align-items: center; gap: 12px 16px; flex-wrap: wrap;
    margin-bottom: 16px;
  }
  .hk-controls-spacer { flex: 1 1 auto; min-width: 0; }
  .hk-control { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .hk-seg-label {
    font-size: 0.8rem; font-weight: 600; color: var(--hk-ink-2);
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  .hk-seg {
    display: inline-flex; border: 1px solid var(--hk-line);
    border-radius: var(--hk-r-pill); overflow: hidden; background: var(--hk-surface);
  }
  .hk-seg-btn {
    appearance: none; border: 0; background: transparent; cursor: pointer;
    font: inherit; font-size: 0.85rem; padding: 7px 15px;
    color: var(--hk-ink); white-space: nowrap;
    border-left: 1px solid var(--hk-line);
    display: inline-flex; align-items: center; gap: 7px;
  }
  .hk-seg-btn:first-child { border-left: 0; }
  /* The count reads as a companion figure, not part of the label: lighter, and
     tinted to the button's own foreground so it stays legible when active. */
  .hk-seg-count { font-size: 0.78rem; opacity: 0.72; font-variant-numeric: tabular-nums; }
  /* A scope with nothing in it recedes rather than disappearing, so the row keeps its
     shape as tasks come and go and the count stays legible — "0" is the answer to a
     question worth asking. */
  .hk-seg-btn.hk-seg-empty { opacity: 0.5; }
  .hk-seg-btn.hk-seg-empty:hover { opacity: 0.75; }
  /* Label + value + caret, sized like the pills beside it. A refinement with more
     than a couple of options states its current value instead of showing them all. */
  .hk-menu { gap: 0; border: 1px solid var(--hk-line); border-radius: var(--hk-r-btn);
    background: var(--hk-surface); padding: 0 10px 0 12px; cursor: pointer; }
  .hk-menu .hk-seg-label { font-size: 0.72rem; letter-spacing: 0.05em; flex: none; }
  .hk-menu-select, .hk-profile-select {
    appearance: none; font: inherit; font-size: 0.85rem; font-weight: 500;
    padding: 8px 20px 8px 8px; border: 0; background: transparent;
    color: var(--hk-ink); cursor: pointer; max-width: 200px;
    text-overflow: ellipsis;
    background-image: linear-gradient(45deg, transparent 50%, var(--hk-ink-2) 50%),
                      linear-gradient(135deg, var(--hk-ink-2) 50%, transparent 50%);
    background-position: right 8px top 55%, right 3px top 55%;
    background-size: 5px 5px, 5px 5px;
    background-repeat: no-repeat;
  }
  .hk-menu-select:focus-visible, .hk-profile-select:focus-visible {
    outline: 2px solid var(--hk-accent); outline-offset: 2px; border-radius: 4px;
  }
  /* The closed control blends into its chip via a transparent background, but the
     popup list it opens is the browser's own UI surface — Chromium and Firefox both
     honor a color/background-color set on <option>, so without one the popup falls
     back to its OS default (grey text on white) even in a dark theme. */
  .hk-menu-select option, .hk-profile-select option {
    background-color: var(--hk-surface); color: var(--hk-ink);
  }
  .hk-seg-btn:hover { background: var(--hk-page); }
  /* White on the accent measures 3.26:1 — under the 4.5:1 a 12px label needs. The
     soft/ink pairing clears it, and the inset edge means selection is not carried by
     hue alone for anyone who cannot separate the two fills. */
  .hk-seg-btn.active {
    background: var(--hk-accent-soft);
    color: var(--hk-accent-ink); font-weight: 600;
    box-shadow: inset 0 0 0 1px var(--hk-accent);
  }
  /* The one primary action per surface. */
  .hk-add-btn { flex: none; }

  /* ── Collapsible group sections ───────────────────────────────────────────
     An eyebrow, its count, then a hairline that carries the eye to a chevron at
     the far end — so a long list reads as sections rather than one run of rows. */
  details.hk-group { margin-bottom: 12px; }
  details.hk-group > summary {
    list-style: none; cursor: pointer; display: flex; align-items: center;
    gap: 10px; padding: 8px 2px; user-select: none;
  }
  details.hk-group > summary::-webkit-details-marker { display: none; }
  details.hk-group > summary::before {
    content: ''; width: 0; height: 0; flex: none;
    border-left: 5px solid var(--hk-ink-2);
    border-top: 4px solid transparent; border-bottom: 4px solid transparent;
    transition: transform 0.15s ease; transform: rotate(0deg);
  }
  details.hk-group[open] > summary::before { transform: rotate(90deg); }
  .hk-group-title {
    font-size: 0.69rem; font-weight: 700; letter-spacing: 0.09em;
    text-transform: uppercase; color: var(--hk-ink-2);
  }
  .hk-group-count {
    font-size: 0.69rem; font-weight: 700; color: var(--hk-ink-2);
    background: var(--hk-page);
    border-radius: var(--hk-r-pill); padding: 2px 8px;
    font-variant-numeric: tabular-nums;
  }
  .hk-group-rule { flex: 1; height: 1px; background: var(--hk-line-soft); min-width: 12px; }
  .hk-group-toggle {
    flex: none; width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid var(--hk-ink-2);
    transition: transform 0.15s ease;
  }
  details.hk-group[open] > summary .hk-group-toggle { transform: rotate(180deg); }
  /* Overdue is the section people are looking for, so its header carries the same
     red as the rows beneath it. */
  /* The ink, not the raw hue: at 9.7px/700 the hue itself measured 4.11:1, and the
     count beside it already reads from the ink. */
  details.hk-group[data-bucket="overdue"] > summary .hk-group-title {
    color: var(--hk-danger-ink);
  }
  details.hk-group[data-bucket="overdue"] > summary .hk-group-count {
    color: var(--hk-danger-ink); background: var(--hk-danger-soft);
  }

  /* ── Appliances: the list stays beside the appliance ───────────────────────
     An appliance is almost always read in comparison with its siblings ("which
     one had the overdue part?"), so drilling in keeps the list rather than
     replacing it. The pane scrolls independently of the detail beside it. */
  .hk-master-detail { display: flex; align-items: flex-start; gap: 20px; }
  .hk-master {
    flex: 0 0 268px; position: sticky; top: 8px;
    max-height: calc(100vh - 24px); overflow: auto; overscroll-behavior: contain;
  }
  .hk-detail-pane { flex: 1 1 auto; min-width: 0; }
  /* In the pane the rows are a picker, not the page: tighter, and the selected one
     is marked the way the drawer marks the row it is editing. */
  .hk-master ha-card.hk-card { margin-bottom: 6px; }
  .hk-master .hk-card-row { padding: 10px 12px; gap: 8px; }
  .hk-master ha-card.hk-card.hk-selected {
    border-left: 3px solid var(--hk-accent);
    background: var(--hk-accent-soft);
    --ha-card-border-radius: 0 var(--hk-r-row) var(--hk-r-row) 0;
  }

  /* ── Appliance sub-tabs ────────────────────────────────────────────────────
     Seven stacked sections became a page you scrolled; as tabs, each is one click
     and one URL. The strip scrolls sideways rather than wrapping, so the tab you
     want is never on a second line. */
  .hk-subtabs {
    display: flex; gap: 2px; padding: 0 8px;
    border-top: 1px solid var(--hk-line);
    background: var(--hk-page);
    overflow-x: auto; scrollbar-width: none;
  }
  .hk-subtabs::-webkit-scrollbar { display: none; }
  .hk-subtab {
    appearance: none; border: 0; background: transparent; cursor: pointer;
    font: inherit; font-size: 0.85rem; color: var(--hk-ink-2);
    padding: 12px 14px 10px; white-space: nowrap;
    border-bottom: 2px solid transparent;
    display: inline-flex; align-items: center; gap: 7px;
  }
  .hk-subtab:hover { color: var(--hk-ink); }
  .hk-subtab.active {
    color: var(--hk-accent-ink); font-weight: 500;
    border-bottom-color: var(--hk-accent);
  }
  .hk-subtab-count {
    font-size: 0.7rem; font-weight: 700; border-radius: var(--hk-r-pill);
    padding: 1px 7px; background: var(--hk-page);
    background: color-mix(in srgb, var(--hk-ink) 8%, transparent);
    font-variant-numeric: tabular-nums;
  }
  .hk-subtab.active .hk-subtab-count {
    background: color-mix(in srgb, var(--hk-accent) 22%, transparent);
  }
  /* The header card owns the tab strip, so it loses its bottom padding to it. */
  ha-card.hk-asset-head { margin-bottom: 12px; }
  ha-card.hk-asset-head .hk-subtabs { margin-top: 4px; }
  /* The first section inside a tab body already sits under the strip, so it does
     not need the leading margin a stacked section carried. */
  .hk-subtab-body > .hk-section:first-child { margin-top: 0; }

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
  /* An id is a uuid: monospace so it can be read and checked character by character,
     and allowed to wrap rather than widen the card on a phone. */
  .hk-id-row .v { display: flex; align-items: center; gap: 4px; }
  .hk-id-row code {
    font-family: var(--code-font-family, monospace); font-size: 0.8rem;
    color: var(--secondary-text-color); overflow-wrap: anywhere;
  }
  .hk-id-row ha-icon-button {
    --mdc-icon-button-size: 32px; --mdc-icon-size: 18px;
    color: var(--secondary-text-color); flex: 0 0 auto;
  }
  /* The compact form, for the part and document rows. */
  .hk-id-inline { display: flex; align-items: center; gap: 2px; margin-top: 2px; }
  .hk-id-inline code {
    font-family: var(--code-font-family, monospace); font-size: 0.72rem;
    color: var(--secondary-text-color); opacity: 0.85; overflow-wrap: anywhere;
  }
  .hk-id-inline ha-icon-button {
    --mdc-icon-button-size: 24px; --mdc-icon-size: 14px;
    color: var(--secondary-text-color); flex: 0 0 auto;
  }
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
  /* The destructive one of the three reads as destructive on approach rather than at
     rest: three red trashcans down a history list is an alarm, and the row is a
     record, not a control panel. */
  ha-icon-button.hk-hist-del:hover, ha-icon-button.hk-hist-del:focus-visible {
    color: var(--hk-danger-ink);
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

  /* ── Phone-width tab bar ───────────────────────────────────────────────────
     Hidden by default and swapped in for ha-tab-group below the phone breakpoint,
     so exactly one navigation control exists at any width. */
  .hk-bottombar { display: none; }
  .hk-bottomtab {
    appearance: none; border: 0; background: transparent; cursor: pointer;
    font: inherit; font-size: 0.72rem; color: var(--hk-ink-2);
    flex: 1; padding: 8px 4px 0; min-height: var(--hk-tap);
    display: flex; flex-direction: column; align-items: center; gap: 7px;
  }
  .hk-bottomtab.active { color: var(--hk-accent); font-weight: 500; }
  .hk-bottomtab-mark {
    width: 26px; height: 4px; border-radius: 2px; background: transparent;
  }
  .hk-bottomtab.active .hk-bottomtab-mark { background: var(--hk-accent); }

  /* Someone who has asked their system for less motion gets none of ours. The upload
     sweep in particular is an unbounded animation that runs for the whole transfer. */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      transition-duration: 0.01ms !important;
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      scroll-behavior: auto !important;
    }
  }

  /* ── Responsive ────────────────────────────────────────────────────────────
     Viewport media queries, not container queries: container-type would make
     :host a containing block for fixed descendants, which is exactly what the
     bottom bar and the drawer must not be anchored to. Home Assistant collapses
     its own sidebar below ~870px, so the phone rules can run full-bleed. */
  /* No room for a rail beside the sections, and none for six expanded sections
     either. So Settings becomes two screens: an index of the six, and one section
     at a time with a back arrow — the same master/detail move an appliance makes,
     and deep-linked the same way.

     All three parts are in the DOM at every width; only these rules decide which
     shows. The layout carries a data-section attribute when the URL names one, and
     the card it names carries .hk-sec-current, so this is decidable in CSS without
     any JS reading the viewport. */
  @media (max-width: 1000px) {
    .hk-settings-layout { flex-direction: column; align-items: stretch; gap: 12px; }
    .hk-settings-rail { display: none; }
    .hk-settings-index { display: flex; }
    .hk-settings-col { max-width: none; width: 100%; }
    /* The index is the screen while no section is open. */
    .hk-settings-layout:not([data-section]) .hk-settings-col { display: none; }
    /* One section is the screen while one is. */
    .hk-settings-layout[data-section] .hk-settings-index { display: none; }
    .hk-settings-layout[data-section] .hk-settings-backbar { display: flex; }
    .hk-settings-layout[data-section] .hk-settings-col ha-card:not(.hk-sec-current) {
      display: none;
    }
    /* Both copies of the version live in the rail and the index, and with a section
       open neither is on screen — so the page-wide one is the only one left. */
    .hk-settings-layout[data-section] ~ .ver { display: block; }
  }

  /* No room for the list beside the appliance — the appliance takes the column and
     the back button in its bar is the way back to the list. */
  /* Same reasoning as the drawer below: the query measures the viewport, the panel
     gets the viewport minus HA's sidebar. Under 1000px a 268px pane plus a detail is
     two columns too many. The controls go with the pane they filter. */
  @media (max-width: 1000px) {
    .hk-master-detail { display: block; }
    .hk-master { display: none; }
    .hk-master-controls { display: none; }
    .hk-detail-pane { min-width: 0; }
    /* The sub-tabs no longer have a 700px pane to sit in, so let them scroll rather
       than clip Related and History off the edge with no cue that they exist. */
    .hk-subtabs {
      flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none;
      -webkit-overflow-scrolling: touch;
      mask-image: linear-gradient(to right, #000 calc(100% - 24px), transparent);
    }
    .hk-subtabs::-webkit-scrollbar { display: none; }
    .hk-subtab { flex: none; }
  }

  @media (max-width: 700px) {
    ha-tab-group { display: none; }
    .hk-bottombar {
      display: flex;
      position: fixed; inset-inline: 0; bottom: 0; z-index: 4;
      background: var(--hk-surface);
      border-top: 1px solid var(--hk-line);
      padding-bottom: max(8px, env(safe-area-inset-bottom));
    }
    /* Clear the bar, plus the floating Add button that sits above it. */
    .hk-wrap { padding: 12px 12px 132px; }
    /* The controls wrap onto as many rows as they need — nothing scrolls sideways,
       because a control parked off the edge of a phone screen is a control nobody
       finds. The joined segment can't wrap (it is one pill with hairlines between
       the buttons), so at this width it comes apart into separate chips, which can.
       That also survives a locale whose labels are half again as long as English. */
    .hk-controls { gap: 10px 8px; }
    /* A segment gets a row to itself and wraps within it; the dropdowns are narrow
       enough to share the row under it. */
    .hk-control:not(.hk-menu) { flex: 1 1 100%; min-width: 0; }
    .hk-menu { flex: 0 1 auto; min-width: 0; }
    .hk-seg {
      flex-wrap: wrap; gap: 8px;
      border: 0; border-radius: 0; background: transparent; overflow: visible;
    }
    .hk-seg-btn {
      border: 1px solid var(--hk-line); border-radius: var(--hk-r-pill);
      background: var(--hk-surface); padding: 9px 14px;
      min-height: var(--hk-tap); box-sizing: border-box;
    }
    /* The filter chips and the group-by dropdown are the two things a thumb reaches
       for most on a phone list, and both sat under the tap target this file defines. */
    .hk-menu { min-height: var(--hk-tap); }
    .hk-menu-select, .hk-profile-select { min-height: calc(var(--hk-tap) - 2px); }
    .hk-add-btn { --ha-button-height: var(--hk-tap); }
    /* Restore only the width the joined-segment rule zeroes out. Matching that rule's
       first-child specificity here would also tie with the .active rule and, as the
       later rule, repaint the active chip's background white under white text. */
    .hk-seg-btn:first-child { border-left-width: 1px; }
    .hk-seg-btn.active { border-color: var(--hk-accent); }
    .hk-controls-spacer { display: none; }
    /* Add becomes a floating action button clear of the tab bar. */
    .hk-add-btn {
      position: fixed; right: 16px; bottom: calc(72px + env(safe-area-inset-bottom));
      z-index: 5;
      --ha-button-border-radius: 14px;
      box-shadow: var(--hk-shadow-float);
      border-radius: 14px;
    }
    /* A phone row stacks: title, meta, the chips, then status and Done on one line.
       The chips take a row of their own rather than sharing with the status pill, so
       the pill and the button it argues for always end up side by side. */
    .hk-card-row { flex-wrap: wrap; row-gap: 10px; }
    .hk-card-row .grow { flex: 1 1 100%; }
    .hk-chips.hk-chips-inline { flex: 1 1 100%; flex-wrap: wrap; order: 1; }
    .hk-status { order: 2; }
    .hk-card-actions { order: 3; margin-inline-start: auto; }
    /* The spacer pushes Done to the right end of a *single-line* row. Once the row
       wraps, the actions' margin-inline-start: auto does that job instead — and the
       spacer, left at order 0 while .grow beside it is flex: 1 1 100%, cannot share
       a line with anything and takes a whole empty one of its own. */
    .hk-row-spacer { display: none; }
  }

  /* ── Narrow: the drawer becomes a bottom sheet ─────────────────────────────
     Below this width there is no room for a column beside the list, so the drawer
     covers it instead. Fixed rather than sticky here because a sheet is anchored to
     the viewport, not to the document it is covering — and unlike the desktop
     drawer it is a full overlay, so a containing-block surprise would be obvious
     rather than subtle.

     The threshold is 1150px, not the 900px the other narrow rules use, because a
     media query measures the *viewport* while the panel gets the viewport minus
     Home Assistant's ~256px sidebar. At a 1000px window the shell is ~744px and a
     clamp(340px, 40vw, 472px) drawer claims 400px of it — wider than the list left
     beside it, which then breaks task names one character per line. Anything under
     1150px has no room for two columns, whatever the viewport says. */
  @media (max-width: 1150px) {
    .hk-drawer[data-open] {
      position: fixed; inset-inline: 0; bottom: 0; top: auto; z-index: 6;
      width: auto; min-width: 0; max-height: 92dvh;
      display: flex; flex-direction: column;
      border-left: 0; border-top: 1px solid var(--hk-line);
      border-radius: 22px 22px 0 0;
      box-shadow: 0 -8px 32px color-mix(in srgb, var(--hk-ink) 26%, transparent);
      padding-top: 10px;
    }
    /* The grab handle that says "this sheet moves". Decorative — the header's
       close button is the actual affordance. */
    .hk-drawer[data-open]::before {
      content: ''; flex: none; align-self: center;
      width: 36px; height: 4px; border-radius: 2px; margin-bottom: 6px;
      background: var(--hk-line);
    }
    /* The sheet is already anchored to the viewport, so its inner panel scrolls
       within it rather than sticking to anything. */
    .hk-drawer[data-open] .hk-drawer-sticky {
      position: static; max-height: none; flex: 1 1 auto; min-height: 0;
    }
    .hk-drawer ha-card.hk-form-card { min-height: 0; }
    /* The list behind a full-width sheet is covered, not consulted — so it keeps
       its normal contrast rather than being dimmed under an opaque surface. */
    .hk-shell-drawer .hk-wrap:not([data-detail]) > *:not(#hk-list),
    .hk-shell-drawer .hk-wrap:not([data-detail]) #hk-list > ha-alert,
    .hk-shell-drawer .hk-wrap:not([data-detail]) #hk-list .hk-group-head,
    .hk-shell-drawer .hk-wrap:not([data-detail]) #hk-list ha-card:not(.hk-editing) {
      opacity: 1;
    }
  }
`;
