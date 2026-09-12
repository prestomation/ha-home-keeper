# Home Keeper

[![Integration Usage][usage-shield]][usage]
[![GitHub Downloads][downloads-shield]][releases]
[![GitHub Release][release-shield]][releases]
[![GitHub Release Date][release-date-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)
[![hacs][hacs-shield]][hacs]
![Project Maintenance][maintenance-shield]
[![ko-fi][kofi-shield]][kofi]
[![HACS Validation][hacs-validation-shield]][hacs-validation]
[![HA Version][ha-version-shield]][ha-version]
[![Docs][docs-shield]][docs]

Home Keeper tracks home maintenance and chores in Home Assistant. This includes
fridge and furnace filter changes, water filters, taking medicine, and anything
else that recurs.

> 📖 **Full documentation** (a browsable User Guide and Developer Guide) lives at
> **<https://prestomation.github.io/ha-home-keeper/>**. The site is generated from
> `docs/`, so the two never drift.

![Home Keeper task list](docs/images/1-panel-task-list.png)

## What people say

<!-- Quotes are other people's words, so they are reproduced as written. -->
<!-- vale ai-tells.OverusedVocabulary = NO -->

> It's exceptionally well thought out, fills a real gap in the Home Assistant
> ecosystem, and has great potential to become the go-to maintenance tracker for
> many users.
>
> *[@psym88](https://github.com/prestomation/ha-home-keeper/issues/101)*

> So happy to finally see such a thorough solution to this problem. I hope this
> really takes off and becomes a core component of HA.
>
> *[@peng1can](https://community.home-assistant.io/t/home-keeper-extensible-home-maintenance-tracking/1014673/6)*

> It is currently much closer to the maintenance tracker I had been looking for
> than anything else I tried.
>
> *[@Tomblarom](https://github.com/prestomation/ha-home-keeper/issues/305)*

<!-- vale ai-tells.OverusedVocabulary = YES -->

## Features at a glance

- Tasks support 5 recurrence types. These are floating, fixed, one-off, triggered,
  and sensor-based. See [Concepts](https://prestomation.github.io/ha-home-keeper/docs/guide/concepts).
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
  documents. A CSV appliance report is available for insurance.
- Home Keeper fires a bus event for every state change and provides device
  triggers such as "Task became overdue" for the visual automation editor.
- Every data action is a `home_keeper.*` service for automations and scripts and
  voice.
- Home Keeper is localized in 16 languages and follows the Home Assistant
  language setting.
- Other integrations can contribute their own recurring tasks and stay in sync
  with completions.

## Installation

Home Keeper is a custom integration installed with [HACS](https://hacs.xyz/):

1. In HACS, add this repository as a custom repository, category
   Integration: `https://github.com/prestomation/ha-home-keeper`.
2. Install Home Keeper and restart Home Assistant.
3. Add the integration from **Settings → Devices & Services → Add Integration →
   Home Keeper**.

A Home Keeper panel then appears in the sidebar. Tasks and appliances are
stored locally in a single JSON document, `.storage/home_keeper`.

## Documentation

- [User Guide](https://prestomation.github.io/ha-home-keeper/docs/intro): every
  feature, with screenshots. The pages are written in [`docs/guide/`](docs/guide).
- [Developer Guide](https://prestomation.github.io/ha-home-keeper/developer/integrating):
  how another integration contributes tasks, plus the API reference.
- [Release notes](https://prestomation.github.io/ha-home-keeper/docs/release-notes).

## Development

- Backend: `custom_components/home_keeper/`. The recurrence engine is in
  `recurrence.py`.
- Panel frontend: `custom_components/home_keeper/frontend/`, built with
  TypeScript and Rollup.
- Tests: `pytest` unit tests in `tests/unit`, Docker integration tests in
  `tests/integration`, Playwright end-to-end tests in `tests/e2e`, and vitest
  frontend tests.
- Typing: `mypy custom_components/home_keeper`, configured in `pyproject.toml`
  and enforced by `lint.yml`. Home Assistant must be installed for its types to
  resolve.

See [AGENTS.md](AGENTS.md) for workflow and [RELEASE.md](RELEASE.md) for
releases.

[usage-shield]: https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https%3A%2F%2Fanalytics.home-assistant.io%2Fcustom_integrations.json&query=%24.home_keeper.total&style=for-the-badge
[usage]: https://analytics.home-assistant.io/
[downloads-shield]: https://img.shields.io/github/downloads/prestomation/ha-home-keeper/total.svg?style=for-the-badge
[releases]: https://github.com/prestomation/ha-home-keeper/releases
[release-shield]: https://img.shields.io/github/release/prestomation/ha-home-keeper.svg?style=for-the-badge
[release-date-shield]: https://img.shields.io/github/release-date/prestomation/ha-home-keeper?style=for-the-badge
[commits-shield]: https://img.shields.io/github/last-commit/prestomation/ha-home-keeper?style=for-the-badge
[commits]: https://github.com/prestomation/ha-home-keeper/commits/main
[license-shield]: https://img.shields.io/github/license/prestomation/ha-home-keeper.svg?style=for-the-badge
[hacs-shield]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge
[hacs]: https://github.com/hacs/integration
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40prestomation-blue.svg?style=for-the-badge
[hacs-validation-shield]: https://github.com/prestomation/ha-home-keeper/actions/workflows/hacs.yml/badge.svg
[hacs-validation]: https://github.com/prestomation/ha-home-keeper/actions/workflows/hacs.yml
[ha-version-shield]: https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg?style=for-the-badge
[ha-version]: https://www.home-assistant.io/
[docs-shield]: https://img.shields.io/badge/docs-website-03a9f4.svg?style=for-the-badge
[docs]: https://prestomation.github.io/ha-home-keeper/
[kofi-shield]: https://img.shields.io/badge/Ko--fi-donate-FF5E5B?style=for-the-badge&logo=kofi&logoColor=white
[kofi]: https://ko-fi.com/prestomation
