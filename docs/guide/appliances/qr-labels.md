# QR code labels

Home Keeper supports QR code labels for appliances and tasks. Each code is a link to the
page of its appliance or task in the Home Keeper panel. Print the labels on a label sheet
or on a label printer. Put a label on the appliance.
Then scan it with a phone camera to open the page in the panel.

The panel is for admins only, so the link opens only for an admin. To complete a task
with a scan, use a Home Assistant tag. See [NFC and RFID tags](../tasks/nfc-tags.md).

## Print 1 label

1. Open the page of an appliance or a task.
2. Select **QR label**.
3. Optional: change the print settings. See [Label sizes](#label-sizes) and
   [Text on the label](#text-on-the-label).
4. Select **Print 1 label**. The print dialog of the browser opens.

![The QR label button on the page of an appliance](../../images/79j-panel-qr-label-detail-button.png)

![The QR label dialog of an appliance, with the code, the link and the print settings](../../images/79c-panel-qr-label-appliance.png)

The dialog also has these buttons:

- **Copy link** copies the link in the code.
- **Download PNG** saves the whole label, the code and its text, as an image at the
  label size. See [Label printers](#label-printers).

## Print many labels

1. On the **Appliances** tab or on the **Tasks** tab, select **Print labels**.
2. Select the appliances or the tasks to print. **Select all** selects all of the list.
3. Optional: for appliances, select **Also print a label for each task of these
   appliances**.
4. Select **Print**. The print dialog of the browser opens.

The dialog shows the same appliances or tasks as the list. To print fewer, type in the
**Search** box before you select **Print labels**.

![The Print labels dialog with 2 appliances selected and their tasks added](../../images/79b-panel-qr-labels-picker.png)

## Label sizes

Select the size in **Label size**. Home Keeper prints on label sheets and on the label
rolls of label printers.

### Label sheets

Home Keeper prints on 2 common label sheets:

| Sheet | Labels | Label size | Same layout as |
|---|---|---|---|
| US Letter | 30 | 2⅝ × 1 in | Avery 5160 |
| A4 | 21 | 63.5 × 38.1 mm | Avery L7160 |

The first sheet comes from the country in the Home Assistant settings. The panel keeps
your choice of size and text in this browser.

If a sheet is part used, set **Skip used labels** to the number of used labels. The
first label then prints on the next free label.

In the print dialog, do these steps, or the labels do not align with the sheet:

1. Set the margins to **None**.
2. Set the scale to **100%**.

To make a PDF file, select **Save as PDF** as the printer.

![A printed sheet with labels for 2 appliances and the tasks of 1 of them](../../images/79e-panel-qr-label-sheet.png)

### Label printers

A small label printer, such as a Niimbot B1, prints on a roll of labels. Its app
opens an image or a PDF file. Home Keeper makes both at the size of 1 label.

Select 1 of these sizes in **Label size**:

| Size | Width × height |
|---|---|
| Label roll | 50 × 30 mm |
| Label roll | 40 × 30 mm |
| Label roll | 50 × 20 mm |
| Label roll | 30 × 15 mm |
| Label roll, custom size | You type the width and the height, from 10 to 300 mm |

To make a PDF file:

1. Select the size of your labels.
2. Select **Print**. The print dialog of the browser opens.
3. Select **Save as PDF** as the printer. Set the margins to **None** and the scale to
   **100%**.
4. Open the PDF file in the app of your label printer. Each label is 1 page.

To make an image of 1 label:

1. Open the **QR label** dialog of the appliance or the task.
2. Select the size of your labels.
3. In **PNG resolution**, select the resolution of your printer. Most small thermal
   printers use 203 dpi (8 dots per mm). The PNG then has 1 pixel for each dot.
4. Select **Download PNG**. Open the file in the app of your label printer.

The text goes next to the code on a wide label and below the code on a tall label. On a
label that is too small for text, Home Keeper prints only the code.

If the label comes out of the printer on its side, select **Rotate the label 90°**.

![The QR label dialog with a 50 × 30 mm label roll and the PNG resolution](../../images/79l-panel-qr-label-roll.png)

![A 50 × 30 mm label as the PDF holds it](../../images/79m-panel-qr-label-roll-page.png)

## Text on the label

Select the lines to print next to the code:

| Line | Appliance | Task |
|---|---|---|
| Name | Name | Name |
| Model or appliance | Manufacturer and model | Appliance of the task |
| Area | Area | Area of the task, or of its appliance |
| Schedule | None | How the task repeats |

## The link

The code holds the external URL of Home Assistant, then the path of the page. For
example: `https://ha.example.com/home-keeper/appliances/<id>`. If Home Assistant has no
external URL, the code holds the internal URL. If it has neither, the code holds the
address of the browser that printed the label.

Set the URLs in **Settings → System → Network** before you print. If the URL changes
later, print the labels again. A label of an appliance or a task that you delete opens a
page that tells you so.

## On a phone

![The Print labels button on the Appliances tab of a phone](../../images/79f-panel-mobile-qr-labels-button.png)

![The QR label dialog of an appliance on a phone](../../images/79h-panel-mobile-qr-label-appliance.png)
