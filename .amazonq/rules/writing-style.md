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
- **Name the noun. Do not write "nothing", "anything", or "something"** where a real
  noun fits. Write "a record that matches no stored record", not "a record that
  matches nothing". Write "the import reports every field it did not read", not "the
  import reports anything it did not read". A vague pronoun makes the reader guess
  which thing is meant.
- **Say what a thing does, not what it does not do.** Write "Preview only reports what
  would change", not "Preview reports what would change and writes nothing". A trailing
  negative reads as an afterthought and leaves the reader to work out the point. Use a
  negative only when the absence *is* the point, such as a limitation.

### Sentences

- Keep a sentence to 20 words or fewer in instructions. Keep a sentence to 25 words or
  fewer in descriptive text.
- Give one instruction per sentence. Give one idea per sentence.
- Prefer the active voice when the reader is the actor. See "Voice" below for
  when the passive voice is acceptable.
- Use the simple present tense for descriptions. Use the imperative for instructions.
- Do not use a verb form that ends in "-ing" as the main verb. Write "before you
  start the container", not "before starting the container". As a noun it is
  acceptable: "synchronizing the tasks".
- Do not omit articles. Write "open the panel", not "open panel".
- **A product or platform name takes no article.** This is the one exception to the rule
  above. Write "iPhone shows this color behind the icon", not "An iPhone shows this
  color". Write "on iPhone", not "on an iPhone". The name is a proper noun, so it reads
  the way "Android" already does, and a sentence that names both platforms stays
  parallel. The same goes for Home Assistant, HACS, and Home Keeper itself.
  - The article still belongs to a common noun that the name modifies. "An Android
    channel keeps the settings it was created with" is correct, because the article is
    for "channel", not for "Android".
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

### Voice

- State the fact first. Start a feature section with what the software supports
  or does: "Home Keeper supports synchronizing the tasks from a profile to any
  `todo` entity." Then say what it is useful for. Do not open with why a reader
  can care, a problem statement, or a scene from a household.
- Write about the software and the configuration, not about people. Write "The
  profile designates which tasks are synchronized to the configured to-do list",
  not "The profile carries the sync".
- Do not personify the software. It does not carry, know, want, learn, remember,
  or refuse. It supports, stores, reads, writes, adds, removes, and marks.
- Do not describe the UI. The user can see it. Do not describe a rail, a dot, a
  color, a layout, or how a page looks on a phone. Write what the user does and
  what the software does in response: "Select a list in the To-do list picker."
- Do not invent a reason for a behavior. Write what the software does today. Do
  not write why, unless the maintainer stated the reason. "Items that a user adds
  are not imported" is a fact. "Because a to-do item cannot hold a recurrence" is
  an invented reason.
- Do not invent context that the software does not have. A to-do list has no
  concept of home or work. A task has no concept of a child.
- The passive voice is acceptable when the actor is obvious or is the software:
  "the item is marked complete on the list". Prefer the active voice when the
  reader is the actor: "select a list".
- A verb form that ends in "-ing" is acceptable as a noun: "synchronizing the
  tasks" and "for tracking these tasks". Do not use it as the main verb of a
  sentence.

### Tone

- Do not write for effect. Do not use "simply", "just", "note that", or
  "it is important to note".
- Do not tell a story. Write what the software does and what the user does.
- Do not repeat a point in different words.
- The house rules above are enforced by the `HomeKeeper` Vale style in
  `styles/HomeKeeper/`. It is committed, and `.vale.ini` loads it next to
  `ai-tells`. Add a token there when a new banned word appears in review.
- The `vale` job in `lint.yml` still runs. STE and the `ai-tells` style agree on
  most points. If they disagree, STE wins, and you disable the vale rule for that
  line with an inline comment.
- Vale reads a whole list as one block, and its regexes cross sentence ends. Keep
  commas out of list items. Two commas in one list can trip `VerbTricolon` even
  when they are in different bullets. Do not start 2 sentences in a row with the
  same word, or `StackedAnaphora` fires. The local `vale` binary misses some hits
  that CI reports, so match the regexes in `styles/ai-tells/*.yml` by hand.
- Do not start a list item with a bold noun phrase and a colon, such as
  "**The dashboard card**: ...". `LabelAndExplain` fires on "The X:" and "A X:".
  Write the item as a sentence. A bold UI name followed by a colon, such as
  "**Two-way sync**: turn this off ...", is acceptable because it has no article.

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
| AI agent | assistant, AI assistant, chatbot, LLM, model | Use it for any tool a user asks to write or read Home Keeper data on their behalf. "Home Assistant" is unrelated and keeps its name. |

Service and code names keep their current identifiers. `add_asset` stays `add_asset`
in code and in a code span. The prose around it says "appliance".

Add a row when a new name appears. A name in this table is a technical name, so it
can be a noun or a verb as listed, and it can appear in a heading.

## Special budgets that still apply

- **CHANGELOG bullets** stay at 3 sentences or fewer. See `testing-and-workflow.md`.
- **A CHANGELOG bullet's bold lead** is a label, not a sentence. Write a noun phrase
  of 2 to 5 words. Do not write more than 8 words. Write "**Declarative
  companions.**", not "**Home Keeper can now open a task for every entity that
  matches a recipe.**". The sentence after the lead says what a user notices.
- **A bold lead is a heading, so it does not take articles or prepositions.** Write
  "**Seasonal tasks.**", not "**Seasons on a task.**". The rule "Do not omit
  articles" applies to a sentence. It does not apply to a heading.
- **A CHANGELOG bullet says what a user gets. It does not say how the feature
  works.** Write the lead and 1 or 2 short sentences. Do not write which buttons the
  feature hides, what it rewrites, or which fields it adds. Put that in `README.md`.
  If a short bullet loses necessary information, write 2 bullets.
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
