# Exploration tools: a home with many tasks

These tools are for exploration only. They are not product code and no test runs them.

## Tools

- `gen_config.py N OUT` copies the e2e config and writes N generated tasks (mixed types,
  areas, labels, long and Unicode names, long histories on some tasks).
- `run_stack.sh N [WORKDIR]` builds the config, starts Home Assistant in Docker, and runs
  the Playwright global setup, so `tests/e2e/.auth/token.json` exists.
- `measure_backend.mjs` measures list calls, entities, to-do, calendar, add, complete and a burst.
- `probe_blocking.mjs` pings the websocket while an operation runs, to find event loop stalls.
- `logs.sh` prints start-up lines and warnings from the Home Assistant log.
- `tests/e2e/explore-many-tasks.capture.ts` measures the panel and the card. It prints
  `EXPLORE {json}` lines and saves screenshots.

## Run

    bash ci/build-panel.sh
    bash tools/explore-many-tasks/run_stack.sh 1000 /tmp/hk-explore
    node tools/explore-many-tasks/measure_backend.mjs --container integration-homeassistant-1
    node tools/explore-many-tasks/probe_blocking.mjs
    bash tools/explore-many-tasks/logs.sh
    cd tests/e2e && VP=desktop SHOT_DIR=/tmp/shots LABEL=n1000 \
      npx playwright test --config=explore-many-tasks.config.ts --reporter=line

`VP` is `desktop` or `phone`. `ONLY` is `panel` or `card`. `STEPS` is a comma list of
`scroll,search,memory,change,layout,filter,detail`. Stop the stack with
`(cd tests/integration && HA_CONFIG=<dir> docker compose down -v)`.

## Known gaps in the tools

- The `filter` step uses `localStorage` values that do not all map to a scope. Only `overdue` did.
- The `Add task` button selector did not match, so the add form pickers are not measured.
- The `board` item count uses a selector that matches nothing. Read the node counts.
- The card editor step did not open the editor.
