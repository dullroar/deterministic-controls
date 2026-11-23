"""Exit codes and errors."""

EXIT_PASS = 0
EXIT_DEFECTS = 1
EXIT_CONFIG = 2
EXIT_INTERNAL = 3


class ConfigError(Exception):
    """Bad configuration or invocation. Maps to exit code 2."""
