---
title: QR code labels
summary: Prints QR code labels that link to an appliance or task page in the panel.
implements:
  - custom_components/home_keeper/frontend/src/qr-labels.ts
  - custom_components/home_keeper/frontend/src/panel-labels.ts
  - custom_components/home_keeper/frontend/src/qrcodegen.ts
related: [frontend, appliances]
source_hash: 2a7958cf8f6c
---

# QR code labels

An admin prints a QR code label and puts it on an appliance. A scan opens the page of that
appliance or task in the panel. The labels are a frontend feature: no service, no stored
field and no event.

## Goals

- **G1. Stable links.** A printed label keeps working for as long as the panel route does.
- **G2. Many labels at once.** An admin prints a whole sheet from 1 checklist.
- **G3. Stock sheets and label rolls.** Each label lands on the die-cut shape of a common
  label sheet, or fills 1 label of a label printer roll.
- **G4. No runtime dependency.** The encoder is in `src/`, like the rest of the panel.

## Non-goals

- A scan by a user who is not an admin. The panel is admin-only, so the link is too.
  To complete a task with a scan, use a Home Assistant tag (`tag_listener.py`).
- A server-made PDF or a PDF library. The browser's print dialog gives Save as PDF.
- A driver or a protocol for a label printer. The admin prints from the printer's app.

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

Both forms choose the label size (`qr-labels.LABEL_PAPERS`) and which text lines to print
(`qr-labels.LABEL_LINES`). A sheet also takes how many used labels to skip. A roll also
takes **Rotate 90°**, and `roll_custom` takes a width and a height in mm
(`qr-labels.clampMm`). The 1-object form also chooses the PNG density
(`qr-labels.LABEL_DPIS`). These choices are kept per browser under
`panel-types.LS_LABELS`, and `qr-labels.parseLabelOpts` reads an unknown value as the
default. The first size is a sheet that follows the HA country (`qr-labels.defaultPaper`).

### The print

`qr-labels.labelPrintHtml` builds the whole print document. For a sheet,
`labelSheetHtml` uses `qr-labels.LAYOUTS`, the geometry of 2 stock sheets, and gives each
label an absolute position in the sheet's own unit. For a roll, `rollSheetHtml` makes 1
page for each label, at the label size, so Save as PDF gives 1 page per label. Rotate
turns the page and the label 90° clockwise. `@page` sets the paper size and no margin.
All label text goes through `escapeHTML`.

### The fit

`qr-labels.fitLabel` places the code and the text on a roll label and in a PNG. A wide
label puts the text right of the code, and a tall label puts it below. The code shrinks to
keep a text box of at least 14 × 6 mm, and it never goes below 8 mm. When that fails, or
there is no text, the label holds only the code. The sheets keep their own fixed layout.
The panel puts the document in a hidden iframe and calls `print()` on it, so the browser
prints only the labels. The frame goes after `afterprint`.

### The code

`qrcodegen.ts` is the Nayuki QR Code generator (MIT), vendored with `export` added.
`qr-labels.qrSvg` draws its modules as 1 SVG path, black on white at every theme, with a
quiet zone of 2 modules (`qr-labels.QR_BORDER`). Error correction is level M.

### The PNG

Download PNG draws the whole label, the code and its text, on a canvas at the label size
and the chosen density: 203 dpi (8 dots per mm, most thermal label printers) or 300 dpi.
`qr-labels.qrPixelPlan` makes each module a whole number of dots, so a thermal printer
prints every module the same width. `qr-labels.layoutText` wraps the text with the
canvas's own measure, with the same sizes and row limits as the print.

## Trade-offs

- **A browser print** over a PDF library: no dependency and Save as PDF for free, at the
  cost of a hint that asks for no margins and 100% scale.
- **The external URL** over the browser address: a label works away from home, but an
  instance with a wrong external URL prints a wrong link.
- **A checklist in the dialog** over a selection mode in each list layout: 1 surface for
  rows, tiles, the board and the appliance tree.
- **Preset roll sizes plus a custom size** over a list of printer models: the sizes do not
  go out of date, and no brand name is in the panel.

## One-way doors

- The link shape on printed labels. It is the panel route ([frontend](frontend.md)).
- The `localStorage` key `home-keeper.labels`: `paper`, `lines`, `customW`, `customH`,
  `dpi` and `rotate`. An unknown value reads as the default.
