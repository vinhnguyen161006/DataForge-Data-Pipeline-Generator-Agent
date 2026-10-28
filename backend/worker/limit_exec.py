"""Trusted Linux launcher: lower limits, then replace this process with the job."""

import os
import signal
import sys
from pathlib import Path

LAUNCH_FAILURE_EXIT_CODE = 125


def main() -> int:
    """Load only the trusted contract and execute no job if bootstrap fails."""
    if sys.platform != "linux":
        sys.stderr.write("Sandbox setup failed: Linux is required\n")
        return LAUNCH_FAILURE_EXIT_CODE
    try:
        import resource

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from worker.sandbox_limits import MEBIBYTE, SandboxLaunchRequest

        if len(sys.argv) != 2:
            raise ValueError("Invalid launcher arguments")
        request = SandboxLaunchRequest.model_validate_json(sys.argv[1])
        limits = request.limits
        settings = (
            (resource.RLIMIT_AS, limits.memory_mb * MEBIBYTE, limits.memory_mb * MEBIBYTE),
            (resource.RLIMIT_CPU, limits.cpu_seconds, limits.cpu_seconds + 1),
            (resource.RLIMIT_FSIZE, limits.max_file_mb * MEBIBYTE, limits.max_file_mb * MEBIBYTE),
            (resource.RLIMIT_NOFILE, limits.max_open_files, limits.max_open_files),
            (resource.RLIMIT_NPROC, limits.max_processes, limits.max_processes),
            (resource.RLIMIT_CORE, 0, 0),
        )
        for kind, soft, hard in settings:
            inherited_hard = resource.getrlimit(kind)[1]
            if inherited_hard != resource.RLIM_INFINITY and hard > inherited_hard:
                raise ValueError("The requested limit exceeds the inherited hard limit")
            resource.setrlimit(kind, (soft, hard))
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
        os.execv(request.command[0], request.command)
    except Exception:
        sys.stderr.write("Sandbox setup failed: limits or execution could not be applied\n")
        return LAUNCH_FAILURE_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
