from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class VersionParts(BaseModel):
    design_hash: str
    code_hash: str
    tests_hash: str
    batch_id: str
    execution_job_id: str
    report_hash: str

    def fingerprint(self) -> str:
        """TODO: return canonical_json_hash of all parts."""
        raise NotImplementedError


class StaleApprovalError(Exception):
    def __init__(self, changed: list[str]):
        self.changed = changed
        super().__init__(f"Approval is stale; changed parts: {', '.join(changed)}")


def sha256_bytes(data: bytes) -> str:
    """TODO: return the hex sha256 digest of data."""
    raise NotImplementedError


def canonical_json_hash(value: Any) -> str:
    """TODO: hash JSON (or a Pydantic model dump) with sorted keys and compact separators."""
    raise NotImplementedError


def hash_file_map(files: Mapping[str, bytes]) -> str:
    """TODO: order-independent hash of {relative posix path: content}."""
    raise NotImplementedError


def read_tree(root: Path) -> dict[str, bytes]:
    """TODO: read every file under root into {relative posix path: content}."""
    raise NotImplementedError


def assert_approval_matches(approved: VersionParts, current: VersionParts) -> None:
    """TODO: raise StaleApprovalError listing every part that differs (FR-13)."""
    raise NotImplementedError
