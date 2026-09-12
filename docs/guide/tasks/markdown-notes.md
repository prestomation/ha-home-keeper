# Notes are Markdown

Home Keeper supports **Markdown** in every **Notes** field:

- a task
- an appliance
- a part
- a logged completion

This is useful for structured content, such as a numbered procedure or a
table of settings.

A notes field supports GitHub-flavored Markdown:

- headings
- **bold** and *italic* text
- lists
- links
- tables
- quotes
- code

A user writes Markdown in 2 places:

- **Inline on the detail page.** The Notes card has an **Edit note** button
  that opens an editor with a **live preview**. The preview appears only when
  the text contains Markdown.
- **In the edit form.** The task, appliance, part, and completion editors have
  a notes field with the same live preview.

<img src="docs/images/41-panel-note-editor-preview.png" alt="The inline note editor on a task detail page: a textarea containing Markdown, with a live preview below it rendering the heading and bullet list" width="820">

Home Keeper stores notes as **Markdown source**, not HTML. The raw text is
sent to:

- the `todo` item description
- the `calendar` event description
- anything that reads a task through the services or events

Home Assistant renders those descriptions with its own Markdown support.

The `home_keeper.add_asset` and `update_asset` services set the appliance **Notes**
field. Each **part** also has a notes field.

Home Assistant's `ha-markdown` component renders and sanitizes the notes, so a
note matches the current theme.
