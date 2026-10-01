---
name: preset-upkeep
description: Check the integration presets against their upstream integrations, fix the keys that changed, add presets for new duty keys and for integrations Home Keeper does not cover yet, and open one draft PR. Use for the weekly upkeep run, or when asked to check, refresh or audit the presets against upstream.
---

# Preset upkeep

The integration presets in `custom_components/home_keeper/declarative_presets_catalog.py`
select entities by the `translation_key` that each upstream integration gives them.
Each entry names its English translation file (`source`) and the upstream commit we
last read (`verified.ref`). This skill finds what changed upstream since then, fixes
or extends the catalog, and opens one draft PR. Two scripts do the finding with no
judgment. You do the judgment.

Follow `AGENTS.md` for everything this file does not say: ASD-STE100 English in all
user text, tests before a push, CHANGELOG rules, the beta bump, `/q review` after a
push. Never merge, and never comment on a GitHub issue.

## 1. Start

1. Work on the branch the session gives you. When it gives none, branch from
   `origin/main` as `preset-upkeep-YYYY-MM-DD`.
2. `source .venv/bin/activate` (see `AGENTS.md`, "Session setup").
3. Run the key check and keep the report:

   ```bash
   python ci/check_preset_keys.py --report /tmp/preset-report.json
   ```

4. Get the core translation files and list the candidates:

   ```bash
   rm -rf /tmp/ha-core
   git clone -q --depth 1 --filter=blob:none --sparse \
       https://github.com/home-assistant/core /tmp/ha-core
   git -C /tmp/ha-core sparse-checkout set --no-cone \
       '/homeassistant/components/*/strings.json'
   python ci/find_preset_candidates.py --core /tmp/ha-core --json /tmp/candidates.json
   ```

## 2. Breaks: keys that are gone

For each record in the report with `missing` keys or a `fetch_error`:

- Read the upstream file at `pinned_ref` and at `head_ref`
  (`https://raw.githubusercontent.com/<owner>/<repo>/<ref>/<path>`), and the
  integration's entity code when the file does not say enough.
- A renamed key: change it in the catalog. Keep the task name.
- A removed key: remove it. When a duty loses all its keys, remove the duty.
- Never remove a preset id that is in `tests/unit/shipped_preset_ids.txt`. A saved
  companion keeps its id, and `test_shipped_preset_ids_never_change` fails when one
  goes away. When an entry or a shape loses all its keys, keep it as it is and ask the
  maintainer in the PR.
- `branch ... not found`: the default branch changed. Find it with
  `git ls-remote --symref https://github.com/<owner>/<repo> HEAD` and fix `source`.
- A file that moved: fix `source` to the new path.
- `cannot reach the repository`: a network error, not a change upstream. Run the
  check again for that domain (`python ci/check_preset_keys.py <domain>`). When it
  still fails, leave the entry and list it in the PR.
- `pin_error` (no diff, the pinned commit is gone, for example after a force push):
  the head was still checked. Read the upstream history of the file by hand for new
  keys, then pin the entry as usual.

## 3. New keys in integrations we cover

For each record with `added` keys, start with `hints`:

- Read the entity description upstream: unit, device class, what the value counts,
  and whether the device can reset it.
- When the key is a maintenance duty, add it to the duty that has the same task, or
  add a duty. A duty needs a `shape` from `SHAPES` in `declarative_presets.py`
  (`percent_low`, `life_low`, `wear_high`, `reading_low`, `reading_high`, `alert`) and
  a `limit` (see the catalog docstring). A wear counter that counts events, not
  time, gets `"counted": True`.
- A new task name goes in `DUTY_NAMES` in `declarative_preset_text.py`, in all 16
  languages. Use the words that the other entries use.
- A key that is not a duty (a status, a setting, a mode) is skipped. List it in the
  PR as skipped, with one short reason.

## 4. Integrations we do not cover

`/tmp/candidates.json` lists core integrations with duty-like keys and HACS
repositories added since the last run. Review at most 10 per run, the HACS ones
first, then core in the order listed.

- For a HACS repository, find its translation file
  (`custom_components/<domain>/translations/en.json`) on its default branch.
- When it has a clear duty, add a catalog entry: `domain`, `brand`, `icon`, `source`
  (raw URL on the branch), `duties`. Put it in the section of its kind of device.
- For each preset that you add (a new entry, or a new shape in an entry), add its id
  to `tests/unit/shipped_preset_ids.txt` in sorted order. The id is
  `<domain>_<shape>_<platform>_<state>` (see `_integration_presets` in
  `declarative_presets.py`). Leave out the platform when it is `sensor`, and the
  state when the shape has none: `dreo_percent_low`, `electrolux_alert_Change`,
  `roomba_alert_binary_sensor_on`. The unit test names a missing id. Add a new
  entry's brand to the table in `docs/guide/views/settings.md`
  ("Integration presets").
- Record every candidate you reviewed, added or not, so the next run skips it:

  ```bash
  python ci/find_preset_candidates.py --core /tmp/ha-core --mark core:<domain> "<reason>"
  python ci/find_preset_candidates.py --mark hacs:<owner/repo> "<reason>"
  ```

  The reason says what you decided: "added", or why it is not a duty.
- After the HACS candidates are all reviewed, run
  `python ci/find_preset_candidates.py --pin-hacs`.

## 5. Pin and test

1. Pin every entry you read in this run, also the ones with no change, so the next
   report starts from today:

   ```bash
   python ci/check_preset_keys.py --pin
   ```

   An entry that still has a break is not pinned. Fix it, or say in the PR why not.
2. Run the gates:

   ```bash
   python ci/check_preset_keys.py
   ruff format custom_components ci tests && ruff check custom_components ci tests
   pytest tests/unit -q
   bash ci/test-frontend.sh
   ```

   `tests/unit/test_declarative_companions.py` checks that every duty has a task name
   in every language and that every preset text resolves.

## 6. CHANGELOG and version

Only when users get a change (a fixed, added or removed preset):

- One `### Added` bullet for new presets and one `### Fixed` bullet for repaired
  ones. Name the integrations; no mechanism, no key names. Follow the bullet rules in
  `AGENTS.md`. Run `vale` on the lines you added.
- Bump to the next beta as `AGENTS.md` says (`manifest.json`, `const.py`, the
  CHANGELOG heading), and run `python ci/check-changelog-release-gap.py`.

A run that only moves the pins and records reviews needs no CHANGELOG entry and no
version bump.

## 7. Pull request

- When nothing changed upstream and you recorded no review, open no PR. Reply "No
  upstream change" and stop.
- Otherwise commit, push, and open a **draft** PR titled
  `Preset upkeep YYYY-MM-DD`. The body has these sections: Fixed, Added, Skipped keys,
  Candidates reviewed, Candidates left, and Pins moved (a count).
- Open the PR against `main`, not against another branch. The CI workflows run only
  for a PR to `main`, and a later change of the base does not start them.
- Post `/q review` on the PR with a request that names the integrations you changed.
- Reply with a short summary in ASD-STE100 English: what you fixed, what you added,
  and the PR link.
