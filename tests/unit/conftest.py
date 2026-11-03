"""Hypothesis profiles for the property-based tests.

The property files are the only ones that need Hypothesis, and it is an optional
dependency (see ``requirements-test.txt``), so everything here is guarded. Without
Hypothesis installed this module does nothing and the property files skip themselves
at collection, exactly as the PyYAML gates in ``test_api_surface.py`` already do.

Three profiles, chosen by ``HK_HYPOTHESIS_PROFILE``, because the three places these
tests run want different things:

``dev`` (default)
    A workstation. Full shrinking, the ``explain`` phase, and the example database on,
    so a failure arrives minimal and the input that found it is replayed first next
    time. That is the whole value of the tool while you are writing code.

``ci``
    A pull request. ``derandomize`` makes the drawn inputs a pure function of the test
    source, so a red run is a real defect rather than an unlucky seed, and it is
    reproducible on a workstation. Shrinking stays on, because a CI failure is a bug
    report and a bug report has to be minimal. ``print_blob`` puts a
    ``@reproduce_failure`` decorator in the output to paste straight into the file.
    The database is off: see below.

``mutmut``
    Inside the mutation gate. Shrinking is off. A mutant only has to make the test
    *fail*; spending unbounded time reducing that failure to a minimal example buys
    nothing and is the one way these tests could threaten the 45-minute budget. This
    is the setting that makes it safe to score property tests rather than skip them.

**The database is off in ``ci`` and ``mutmut``, and that matters more than the seed.**
mutmut forks concurrent children that each ``cd`` into ``mutants/``, so a directory
database would be shared: a counterexample found while testing one mutant would be
replayed as the first input for the next one *and for the clean run*. A failed clean
run aborts the whole job, so the failure would depend on mutant ordering.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator

import pytest

try:
    from hypothesis import HealthCheck, Phase, settings
except ImportError:  # pragma: no cover - exercised by the bare-pytest install
    pass
else:
    settings.register_profile(
        "dev",
        max_examples=100,
        # No deadline anywhere. A per-example timing limit is the classic Hypothesis
        # flake, and under mutmut a deadline failure on the clean run fails the job.
        # The iteration-cap regression is expressed as "does not raise", which is a
        # statement about behaviour rather than about how fast the machine is.
        deadline=None,
        print_blob=True,
    )
    settings.register_profile(
        "ci",
        max_examples=100,
        deadline=None,
        derandomize=True,
        database=None,
        print_blob=True,
    )
    settings.register_profile(
        "mutmut",
        max_examples=25,
        deadline=None,
        derandomize=True,
        database=None,
        phases=(Phase.explicit, Phase.reuse, Phase.generate),
        # A mutant can easily make an `assume()` filter reject nearly everything. A
        # health check would exit non-zero, which mutmut reads as a kill either way,
        # but suppressing it keeps the *clean* run stable when a filter is marginal.
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.filter_too_much,
            HealthCheck.data_too_large,
        ],
    )
    settings.load_profile(os.environ.get("HK_HYPOTHESIS_PROFILE", "dev"))


# ── Blocking calls on the event loop ─────────────────────────────────────────
# Home Assistant logs "Detected blocking call" at run time (#247, #150). This fixture
# finds the same defect in the unit tests. blockbuster patches file, socket and sleep
# calls and raises BlockingError when one runs in a thread that runs an event loop.
# It does nothing in a test that runs no loop, so it is safe for every unit test: only
# the tests that drive HA-facing code on a loop can trip it. The error names the file
# and line of the call.
#
# blockbuster is optional here, like Hypothesis: a bare install of pytest and the
# pure-core packages (and the schema gate in lint.yml) must still run the suite. Every
# lane that installs requirements-test.txt has it, and tests/unit/test_blocking_calls.py
# proves that the fixture is on there.
try:
    from blockbuster import blockbuster_ctx
except ImportError:  # pragma: no cover - exercised by the bare-pytest install
    blockbuster_ctx = None


@pytest.fixture(autouse=True)
def blockbuster() -> Iterator[object | None]:
    """Fail a test when code blocks the thread of a running event loop."""
    if blockbuster_ctx is None:
        yield None
        return
    with blockbuster_ctx() as bb:
        yield bb


@pytest.fixture(scope="session", autouse=True)
def _locale_data_is_loaded() -> None:
    """Load the locale data that Home Keeper loads at setup, before any test runs.

    ``__init__.async_setup_entry`` asks for ``assets.decimal_mark`` in an executor job
    for the language of the instance, so Babel reads its locale files off the loop.
    A unit test that formats a quantity on a loop has no setup. Without this, the
    first such test of a run reads the files on the loop, and fails under blockbuster
    when the file runs alone, though it passes after any test that warmed the cache.
    """
    try:
        from babel import Locale
        from babel.numbers import get_decimal_symbol
    except ImportError:  # a bare install: no test here formats a quantity
        pass
    else:
        for lang in ("en", "de"):
            get_decimal_symbol(Locale.parse(lang))
    # ``async_setup_entry`` also runs ``backend_i18n.preload`` in an executor, so the
    # string tables are in memory before any call to ``resolve_string`` (#247).
    backend_i18n = sys.modules.get("hk.backend_i18n")
    if backend_i18n is not None:
        backend_i18n.preload("en")
