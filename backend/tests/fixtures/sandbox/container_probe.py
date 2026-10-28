"""Bounded, nonroot cgroup-v2 probe executed only in a disposable Docker container."""

import errno
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    expected_pids = int(sys.argv[1])
    exercise_pids = sys.argv[2] == "exercise"
    cgroup = Path("/sys/fs/cgroup")
    pids = int((cgroup / "pids.max").read_text())
    memory = int((cgroup / "memory.max").read_text())
    quota, period = (cgroup / "cpu.max").read_text().split()
    status = {
        line.split(":", 1)[0]: line.split(":", 1)[1].strip()
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    }
    root_readonly = any(
        line.split()[4] == "/" and "ro" in line.split()[5].split(",")
        for line in Path("/proc/self/mountinfo").read_text().splitlines()
    )
    assert os.getuid() == 10001
    assert pids == expected_pids
    assert memory == 3 * 1024**3
    assert int(quota) == 2 * int(period)
    assert int(status["CapEff"], 16) == 0
    assert status["NoNewPrivs"] == "1"
    assert root_readonly
    source = """
import errno, resource, subprocess, sys
resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
try:
    subprocess.run([sys.executable, "-I", "-c", "pass"], check=True)
except OSError as exc:
    assert exc.errno == errno.EAGAIN
    print("nproc-blocked")
else:
    raise SystemExit("NPROC was not enforced")
"""
    outcome = subprocess.run(
        [sys.executable, "-I", "-c", source], capture_output=True, text=True, timeout=5
    )
    assert outcome.returncode == 0, outcome.stderr
    assert outcome.stdout.strip() == "nproc-blocked"
    blocked = False
    children: list[subprocess.Popen[bytes]] = []
    if exercise_pids:
        try:
            for _ in range(expected_pids + 2):
                try:
                    child = subprocess.Popen(
                        [sys.executable, "-I", "-c", "import time; time.sleep(5)"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    children.append(child)
                except OSError as exc:
                    if exc.errno != errno.EAGAIN:
                        raise
                    blocked = True
                    break
        finally:
            for child in children:
                child.terminate()
            for child in children:
                child.wait(timeout=5)
        assert blocked
    print(
        json.dumps(
            {
                "uid": os.getuid(),
                "pids_max": pids,
                "memory_max": memory,
                "cpu_quota": int(quota),
                "cpu_period": int(period),
                "root_readonly": root_readonly,
                "no_new_privileges": True,
                "capabilities_dropped": True,
                "nproc_enforced": True,
                "cgroup_spawn_blocked": blocked,
                "children_started": len(children),
            }
        )
    )


if __name__ == "__main__":
    main()
