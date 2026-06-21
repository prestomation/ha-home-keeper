---
sidebar_position: 2
title: Installation
---

# Installation

Home Keeper is a custom integration installed via [HACS](https://hacs.xyz/):

1. In HACS, add this repository as a **custom repository** (category *Integration*):
   `https://github.com/prestomation/ha-home-keeper`.
2. Install **Home Keeper**, then restart Home Assistant.
3. Add the integration from **Settings → Devices & Services → Add Integration →
   Home Keeper**.

A **Home Keeper** panel then appears in the sidebar. Tasks and appliances are stored
locally in a single JSON document (`.storage/home_keeper`).
