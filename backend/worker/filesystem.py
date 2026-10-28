"""Apply a fail-closed Landlock filesystem policy before loading profile modules."""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from pathlib import Path

CREATE_RULESET = 444
ADD_RULE = 445
RESTRICT_SELF = 446
RULE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38
MINIMUM_ABI = 3
READ_ACCESS = (1 << 2) | (1 << 3)
WRITE_ACCESS = sum(1 << bit for bit in (1, 4, 5, 7, 8, 13, 14))
HANDLED_ACCESS = (1 << 15) - 1


class RulesetAttributes(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class PathAttributes(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def landlock_abi() -> int:
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "aarch64", "riscv64"}:
        raise OSError("Profile filesystem confinement requires supported Linux")
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    abi = int(library.syscall(CREATE_RULESET, None, 0, 1))
    if abi < MINIMUM_ABI:
        raise OSError("Profile filesystem confinement requires Landlock ABI 3 or newer")
    return abi


def confine_profile_filesystem(workspace: Path, backend: Path) -> None:
    """Allow workspace reads/writes and trusted runtime reads, denying other handled access.

    Called in a single-threaded child before importing DuckDB. Existing descriptors
    are not revoked. Metadata operations such as chmod are outside this policy.
    No degraded mode is permitted when the kernel or container denies Landlock.
    """
    landlock_abi()
    if len(list(Path("/proc/self/task").iterdir())) != 1:
        raise OSError("Profile confinement must be applied before creating threads")
    root = workspace.resolve(strict=True)
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    attributes = RulesetAttributes(HANDLED_ACCESS)
    ruleset = int(
        library.syscall(CREATE_RULESET, ctypes.byref(attributes), ctypes.sizeof(attributes), 0)
    )
    if ruleset < 0:
        raise OSError(ctypes.get_errno(), "Cannot create profile filesystem ruleset")
    try:
        readonly = [
            Path(sys.prefix).resolve(),
            Path(sys.base_prefix).resolve(),
            backend / "app",
            backend / "worker",
            Path("/usr"),
            Path("/lib"),
            Path("/lib64"),
            Path("/etc/ld.so.cache"),
            Path("/etc/localtime"),
            Path("/dev/null"),
            Path("/dev/urandom"),
            Path("/proc/self"),
            Path("/proc/meminfo"),
            Path("/proc/cpuinfo"),
            Path("/sys/devices/system/cpu"),
            Path("/sys/fs/cgroup"),
        ]
        for path, access in [
            (root, READ_ACCESS | WRITE_ACCESS),
            *[(path.resolve(), READ_ACCESS) for path in readonly if path.exists()],
        ]:
            descriptor = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                allowed = access if path.is_dir() else access & ~(1 << 3)
                rule = PathAttributes(allowed, descriptor)
                if library.syscall(ADD_RULE, ruleset, RULE_PATH_BENEATH, ctypes.byref(rule), 0):
                    raise OSError(ctypes.get_errno(), "Cannot add profile filesystem rule")
            finally:
                os.close(descriptor)
        if library.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0):
            raise OSError(ctypes.get_errno(), "Cannot restrict profile privileges")
        if library.syscall(RESTRICT_SELF, ruleset, 0):
            raise OSError(ctypes.get_errno(), "Cannot enforce profile filesystem rules")
    finally:
        os.close(ruleset)
