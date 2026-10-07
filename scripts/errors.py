"""The one error type for build-time failures caused by inputs or the environment.

Every entry point catches BuildError, prints its message on one line and exits 1. Anything
else is a bug and keeps its traceback.
"""


class BuildError(Exception):
    pass
