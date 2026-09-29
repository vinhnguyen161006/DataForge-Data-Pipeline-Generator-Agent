from pathlib import Path

from pydantic import BaseModel

GOLDEN_ROOT = Path(__file__).parent / "golden"


class EvalTask(BaseModel):
    task_id: str
    dataset: str
    request_text: str
    csv_dir: Path
    golden_design: Path
    golden_tables: Path


def load_tasks(root: Path = GOLDEN_ROOT) -> list[EvalTask]:
    """TODO: read golden/<dataset>/<task_id>/task.json for OULAD and the two public datasets."""
    raise NotImplementedError
