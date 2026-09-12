# Quality scale

Home Keeper targets Home Assistant's
[**Platinum** integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
The per-rule self-assessment is in
[`custom_components/home_keeper/quality_scale.yaml`](../../../custom_components/home_keeper/quality_scale.yaml).
Home Keeper is a local, deviceless service integration with no network and no
external dependency, so the networking, discovery, and authentication rules are
exempt. The remaining rules are met. Strict typing is met: the integration
includes `py.typed`, and CI runs `mypy` against it with Home Assistant
installed. An async, single-coordinator core is met.

> Error messages raised by services and entities use Home Assistant translation
> keys, `strings.json` under `exceptions`. Most exception messages are
> translated in every locale, and 11 messages are still English in every
> locale. A drift-guard unit test, `tests/unit/test_exception_translations.py`,
> checks that every new raise stays localizable.
