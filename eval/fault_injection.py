from pathlib import Path

FAULTS = (
    "null_key",
    "duplicate_key",
    "orphan_child",
    "unknown_status",
    "bad_date",
    "negative_amount",
)


def inject(csv_dir: Path, out_dir: Path, fault: str, seed: int) -> Path:
    """TODO: copy the clean CSVs and inject one deliberate fault; return the faulty dir."""
    raise NotImplementedError
