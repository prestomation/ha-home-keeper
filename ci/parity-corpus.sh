#!/usr/bin/env bash
# Write tests/fixtures/parity_corpus.json again: Hypothesis draws the inputs and the
# Python side gives the answers. Run it after a change to a rule that the parity
# registry marks `corpus`, then commit the file. See tests/unit/test_parity_corpus.py.
set -euo pipefail
cd "$(dirname "$0")/.."
HK_PARITY_WRITE=1 python -m pytest tests/unit/test_parity_corpus.py -q
