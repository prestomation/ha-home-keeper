---
title: QR code labels
summary: Prints QR code labels that link to an appliance or task page in the panel.
implements:
  - custom_components/home_keeper/frontend/src/qr-labels.ts
  - custom_components/home_keeper/frontend/src/panel-labels.ts
  - custom_components/home_keeper/frontend/src/qrcodegen.ts
related: [frontend, appliances]
source_hash: 2d049b0ee905
---

# QR code labels

An admin prints a QR code label and puts it on an appliance. A scan opens the page of that
appliance or task in the panel. The labels are a frontend feature: no service, no stored
field and no event.

## Goals

- **G1. Stable links.** A printed label keeps working for as long as the panel route does.
- **G2. Many labels at once.** An admin prints a whole sheet from 1 checklist.
- **G3. Stock sheets.** Each label lands on the die-cut shape of a common label sheet.
- **G4. No runtime dependency.** The encoder is in `src/`, like the rest of the panel.

## Non-goals

- A scan by a user who is not an admin. The panel is admin-only, so the link is too.
  To complete a task with a scan, use a Home Assistant tag (`tag_listener.py`).
- A server-made PDF. The browser's print dialog gives Save as PDF.

## Design

### The link

A code holds `<base><prefix>/appliances/<id>` or `<base><prefix>/tasks/<id>`, from
`p._hrefFor` and `utils.buildPath`, which leave out the default sub-tab. `<base>` comes from
`qr-labels.labelBaseUrl`: HA's external URL, then its internal URL, then the browser address.
The frontend reads them from `hass.config`, so no backend call is needed. `hass.config` has
no Home Assistant Cloud address, so a cloud-only instance gets the browser address.

### The dialog

`panel-labels.ts` holds 1 dialog with 2 forms:

- **1 object.** The **QR label** button on an appliance or a task page opens it with a
  preview, the link with a copy button, and Download PNG.
- **A checklist.** **Print labels** beside **Add** opens it with what the list shows: the
  active or archived appliances, or the tasks, narrowed by the search box. Nothing starts
  checked. For appliances, a checkbox adds a label for each of their tasks
  (`utils.tasksForAsset`), and a shared task prints once.

Both forms choose the sheet, how many used labels to skip and which text lines to print
(`qr-labels.LABEL_LINES`). The sheet and the lines are kept per browser under
`panel-types.LS_LABELS`, and `qr-labels.parseLabelOpts` reads an unknown value as the
default. The first sheet follows the HA country (`qr-labels.defaultPaper`).

### The print

`qr-labels.labelSheetHtml` builds the whole print document. `qr-labels.LAYOUTS` holds the
geometry of 2 stock sheets, and each label has an absolute position in the sheet's own unit.
`@page` sets the paper size and no margin. All label text goes through `escapeHTML`.
The panel puts the document in a hidden iframe and calls `print()` on it, so the browser
prints only the labels. The frame goes after `afterprint`.

### The code

`qrcodegen.ts` is the Nayuki QR Code generator (MIT), vendored with `export` added.
`qr-labels.qrSvg` draws its modules as 1 SVG path, black on white at every theme, with a
quiet zone of 2 modules (`qr-labels.QR_BORDER`). Error correction is level M. Download PNG
draws the same SVG on a canvas.

## Trade-offs

- **A browser print** over a PDF library: no dependency and Save as PDF for free, at the
  cost of a hint that asks for no margins and 100% scale.
- **The external URL** over the browser address: a label works away from home, but an
  instance with a wrong external URL prints a wrong link.
- **A checklist in the dialog** over a selection mode in each list layout: 1 surface for
  rows, tiles, the board and the appliance tree.

## One-way doors

- The link shape on printed labels. It is the panel route ([frontend](frontend.md)).
- The `localStorage` key `home-keeper.labels`. An unknown value reads as the default.
