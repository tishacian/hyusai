"""Apply resource ceilings in a fresh process before executing a trusted harness.

This bootstrap is launched with ``-I -S`` and imports only the standard library.
The supervisor creates the process group and supplies the restricted environment;
exec preserves both, the PID and all limits for the harness and its descendants.
"""

from __future__ import annotations

import os
import resource
import sys


def _limit(kind: int, soft: int, hard: int) -> None:
    """Preserve a stricter inherited ceiling instead of trying to raise it."""
    _, inherited_hard = resource.getrlimit(kind)
    if inherited_hard != resource.RLIM_INFINITY:
        hard = min(hard, inherited_hard)
    resource.setrlimit(kind, (min(soft, hard), hard))


def main(args: list[str]) -> int:
    """Install all ceilings before replacing this process with the harness."""
    try:
        if len(args) < 5 or args[3] != "--":
            raise ValueError("invalid arguments")
        memory_mb, cpu_s, file_mb = (int(value) for value in args[:3])
        if min(memory_mb, cpu_s, file_mb) <= 0:
            raise ValueError("invalid limits")
        _limit(resource.RLIMIT_CPU, cpu_s, cpu_s + 5)
        _limit(resource.RLIMIT_AS, memory_mb * 1024**2, memory_mb * 1024**2)
        _limit(resource.RLIMIT_FSIZE, file_mb * 1024**2, file_mb * 1024**2)
        os.execvpe(args[4], args[4:], os.environ)
    except (OSError, ValueError, OverflowError):
        # Do not print command arguments or environment contents into evidence.
        print("process_limit_setup_or_exec_failed", file=sys.stderr, flush=True)
        return 126
    return 126  # exec never returns on success.


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
