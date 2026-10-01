# Type stub only. Home Assistant 2026.9 and later alias `voluptuous` to probatio at
# runtime, and 2026.10 types its APIs with probatio classes. This stub makes mypy
# read `import voluptuous` the same way, as Home Assistant core does in its own
# `stubs/voluptuous`. Runtime imports are not changed.
from probatio import *  # noqa: F403
