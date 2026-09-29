import argparse
from pathlib import Path

from metrics import TaskScore
from tasks import EvalTask


def run_task(
    task: EvalTask, *, retrieval: bool, optimizer: bool, generate_tests: bool
) -> TaskScore:
    """TODO: run the full pipeline offline for one task and score it.

    Retrieval must exclude the task's dataset and task variants to avoid answer leakage.
    """
    raise NotImplementedError


def run_ablation(tasks: list[EvalTask], out_dir: Path) -> None:
    """TODO: run with and without retrieval, optimizer and test generation; write a report."""
    raise NotImplementedError


def main() -> None:
    parser = argparse.ArgumentParser(description="DataForge offline evaluation")
    parser.add_argument("--out", type=Path, default=Path("eval_results"))
    parser.add_argument("--ablation", action="store_true")
    parser.parse_args()
    raise NotImplementedError("TODO: load tasks and dispatch to run_task or run_ablation")


if __name__ == "__main__":
    main()
