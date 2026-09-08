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
