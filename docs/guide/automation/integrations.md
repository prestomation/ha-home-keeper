# Integrations

Home Keeper supports contributions from other integrations. An integration can
add its own recurring tasks and stay in sync with completions. Installing a
compatible integration can populate and maintain the task list automatically. A
battery integration can schedule a "replace battery" task. A pet tracker can
schedule a "give medicine" task.

#### Known integrations

| Integration | Description | How it integrates |
|---|---|---|
| [Home Keeper - Battery Notes](https://github.com/prestomation/ha-home-keeper-battery-notes) | Glue between [Battery Notes](https://github.com/andrew-codechimp/HA-Battery-Notes) and Home Keeper | Uses the **triggered** task type. A *"Replace battery"* task is armed when a battery goes low and cleared when the battery is replaced. A completion on either side is recorded on both. |
| [Pawsistant](https://github.com/prestomation/pawsistant) | Pet-care logger for tracking recurring pet activities | Attaches floating tasks to pet care schedules such as *"medicine every 2 weeks"*. A completion in Home Keeper is logged in Pawsistant. A completion in Pawsistant completes the Home Keeper task. |
| [Home Keeper - Bambu Lab](https://github.com/prestomation/ha-home-keeper-bambu-lab) | Glue between [Bambu Lab](https://github.com/greghesp/ha-bambulab) 3D printers and Home Keeper | Uses Home Keeper's **triggered** task type to track a printer's firmware-update status as a read-only *"Update firmware: …"* task, armed when an update is available and cleared once it is installed. Optionally also creates a per-printer maintenance-task catalog (lead-screw greasing, filter replacement, and more, following Bambu Lab's own published schedule), gated on each printer's detected model. |

The panel's **[Companions](../views/settings.md#companions)** section, under the Settings tab, lists
installed companions and links to each one's settings. Home Keeper suggests the
Battery Notes bridge when Battery Notes is installed without the glue
integration.

> **Author an integration?** To push tasks into Home Keeper from a Home
> Assistant integration, see the developer guide,
> [docs/INTEGRATING.md](../../INTEGRATING.md). It documents the contract, the
> `source` field, the `home_keeper_task_completed` event, two-way completion
> sync, and `home_keeper.register_companion` to register under **Companions**.
> See [docs/GLUE_INTEGRATIONS.md](../../GLUE_INTEGRATIONS.md) for the glue
> integration pattern that connects an existing integration, such as Battery
> Notes, to Home Keeper.

> The [API reference](https://prestomation.github.io/ha-home-keeper/developer/api)
> is the generated list of every service, event, and payload.
