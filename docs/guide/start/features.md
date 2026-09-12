# Features at a glance

- Tasks support 5 recurrence types. These are floating, fixed, one-off, triggered,
  and sensor-based. See [Concepts](./concepts.md).
- Home Keeper provides native Home Assistant entities. A `todo` list and an
  upcoming-tasks `calendar` and per-device entities on a task's device page.
- Home Keeper syncs the tasks of a profile to any `todo` entity as they become
  due. A completion on that list completes the task in Home Keeper.
- The bundled dashboard card `custom:home-keeper-card` has a Done button and
  inline add and edit. It supports filtering and grouping.
- Every notes field on a task or appliance or part or completion is Markdown
  with a live preview.
- A task can link to a Home Assistant tag so that a scan completes it. The task
  can require the scan.
- An appliance has a device page with structured metadata and optional
  tracked-date sensors. It has parts and wear items and spare-part inventory and
  documents. A CSV home-inventory export is available for insurance.
- Home Keeper fires a bus event for every state change and provides device
  triggers such as "Task became overdue" for the visual automation editor.
- Every data action is a `home_keeper.*` service for automations and scripts and
  voice.
- Home Keeper is localized in 16 languages and follows the Home Assistant
  language setting.
- Other integrations can contribute their own recurring tasks and stay in sync
  with completions.
