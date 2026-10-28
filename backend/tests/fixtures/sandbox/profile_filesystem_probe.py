"""Probe actual filesystem denial without changing the parent's security domain."""

from __future__ import annotations

import errno
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


def main() -> None:
    backend = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(backend))
    from worker.filesystem import confine_profile_filesystem

    workspace, original = Path(sys.argv[1]), Path(sys.argv[2])
    inherited = [key for key in os.environ if key.startswith("DATAFORGE_") or key == "PGPASSWORD"]
    confine_profile_filesystem(workspace, backend)
    actions: dict[str, Callable[[], object]] = {
        "read": lambda: original.read_bytes(),
        "write": lambda: original.write_bytes(b"changed"),
        "rename": lambda: original.rename(workspace / "stolen.csv"),
        "unlink": lambda: original.unlink(),
        "hardlink": lambda: (workspace / "alias.csv").hardlink_to(original),
        "symlink_write": lambda: (workspace / "symlink.csv").write_bytes(b"changed"),
    }
    denied = []
    for name, action in actions.items():
        try:
            action()
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EPERM, errno.EXDEV}:
                raise
            denied.append(name)
        else:
            raise RuntimeError("An outside filesystem operation succeeded: " + name)
    (workspace / "local.txt").write_text("allowed", encoding="utf-8")
    print(json.dumps({"denied": denied, "credentials": inherited}))


if __name__ == "__main__":
    main()
