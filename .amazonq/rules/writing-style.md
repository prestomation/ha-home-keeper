# Home Keeper — writing style (ASD-STE100)

All English text in this project follows **ASD-STE100 Simplified Technical English**
(STE). This applies to:

- User documentation: `README.md`, `CHANGELOG.md`, the canonical `docs/*.md`,
  `website/docs/intro.md`.
- User-facing strings: `strings.json`, `services.yaml`, the English frontend locale
  (`locales/en.json`), log messages, and exception text.
- Code comments and docstrings.
- PR titles and bodies, PR comments, and review replies.
- Replies to the maintainer in chat.

Other locales are translations. They do not follow STE. Keep their placeholders and
keys the same as the English source (see "Translations" in
`testing-and-workflow.md`).

## The rules

### Words

- Use one approved word for one thing. Do not use synonyms for variety. The project
  names are in the glossary below.
- Use a word for one meaning only. Example: "close" is a verb, not an adjective.
- Use the shortest common word. Write "start", not "initiate". Write "use", not
  "utilize". Write "show", not "surface" or "expose".
- Do not use slang, idiom, or metaphor. No "side door", "on the floor", "reach for",
  "under the hood".
- Do not use contractions. Write "do not", not "don't".
- Write numbers as numerals. Write "3 tasks", not "three tasks". The exception is a
  number that starts a sentence.
- Use "must" for a requirement. Use "can" for a possibility. Do not use "may",
  "might", "should", or "could".
- Use "if" for a condition. Use "when" for a point in time.
- Use "make sure that", not "ensure".
- Do not put more than 3 nouns in a row. Write "the list of tasks that are due", not
  "the due task list summary view".

### Sentences

- Keep a sentence to 20 words or fewer in instructions. Keep a sentence to 25 words or
  fewer in descriptive text.
- Give one instruction per sentence. Give one idea per sentence.
- Use the active voice. Write "Home Keeper creates a device", not "a device is
  created".
- Use the simple present tense for descriptions. Use the imperative for instructions.
- Do not use verb forms that end in "-ing" as verbs. Write "before you start the
  container", not "before starting the container". A name such as "Settings" or
  "the pending review" is a technical name and is permitted.
- Do not omit articles. Write "open the panel", not "open panel".
- Do not omit "that" after "make sure", "confirm", and "check".
- Put a condition before its instruction. Write "If the task has a device, the
  panel shows a link", not "The panel shows a link if the task has a device".
- Do not use parentheses for a second thought. Write it as a separate sentence, or
  remove it.
- Do not use em dashes. Do not use semicolons in prose.
- Do not use rhetorical questions.

### Paragraphs and structure

- Keep a paragraph to 6 sentences or fewer. Start with the topic sentence.
- Give one topic per paragraph.
- Use a numbered list for steps in sequence. Use a bulleted list for items with no
  sequence. Do not put more than 2 items in a series inside one sentence. Use a
  list instead.
- Put a warning or caution before the step it applies to. Write it as a command:
  "Do not delete the config directory while the container runs."
- Use a table for data with 2 or more attributes per row. Do not put full
  sentences in a table cell if a short phrase is enough.
- Write a heading as a noun phrase or a command. Write "Admin operations" or
  "Install the panel".

### Tone

- Do not write for effect. Do not use "simply", "just", "note that", or
  "it is important to note".
- Do not tell a story. Write what the software does and what the user does.
- Do not repeat a point in different words.
- The `vale` job in `lint.yml` still runs. STE and the `ai-tells` style agree on
  most points. If they disagree, STE wins, and you disable the vale rule for that
  line with an inline comment.

## Glossary of approved names

Use these names and no others for these things.

| Use this | Not this | Note |
| --- | --- | --- |
| task | chore, item, reminder, job | |
| appliance | asset, thing, device record | The service identifiers keep `asset`. |
| part | spare, spare part | A part has a type. "consumable" is one of the types, so "consumable part" is correct. |
| document | file, attachment | A manual is a document type. |
| panel | sidebar panel, admin UI, management UI | The panel is in the Home Assistant sidebar. Say that as a sentence, not as a name. |
| card | dashboard card, Lovelace card, task card | |
| profile | household member, person | |
| notification | alert, reminder, push | |
| complete (a task) | tick off, mark done, finish, check off | |
| snooze (a task) | postpone, defer, push back | |
| skip (a task) | dismiss, cancel | |
| due, overdue | late, past due | A task is "due" on its due date. A task past its due date is "overdue". |
| admin | administrator, owner | |
| user | member, household member | "non-admin user" is permitted. |
| Home Assistant | HA | `HA` is permitted in code comments and PR text. |
| service | action | Home Assistant renamed services to actions. This project keeps "service". |
| websocket command | ws command, socket call | |
| config entry | integration entry, entry | |
| device | | A device is a Home Assistant device. Do not call an appliance a device. |
| companion | | An integration that Home Keeper lists under Settings, Companions. |
| glue integration | glue, bridge, connector | The pattern name for a small integration that connects another integration to Home Keeper. A glue integration is one kind of companion. |

Service and code names keep their current identifiers. `add_asset` stays `add_asset`
in code and in a code span. The prose around it says "appliance".

Add a row when a new name appears. A name in this table is a technical name, so it
can be a noun or a verb as listed, and it can appear in a heading.

## Special budgets that still apply

- **CHANGELOG bullets** stay at 3 sentences or fewer. See `testing-and-workflow.md`.
- **`services.yaml` descriptions** stay at 1 or 2 sentences. The first sentence says
  what the service does. The second says a constraint, if there is one.
- **UI labels** in `locales/en.json` and `strings.json` are 1 to 4 words. A tooltip
  or help text is 1 sentence.

## Checklist before you commit prose

1. Read each sentence. Count the words. Split any sentence over the limit.
2. Find every "-ing" verb, every "may", "should", "ensure", and every contraction.
   Replace them.
3. Find every synonym for a glossary name. Replace it.
4. Find every parenthesis, em dash, and semicolon. Remove or split.
5. Check that every instruction is a command in the active voice.
6. Run `vale <file>` on a documentation file.
