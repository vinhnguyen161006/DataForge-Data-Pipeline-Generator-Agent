"""A failed drill must retain partial evidence without reporting successful completion."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from scripts import check_backend_recovery as recovery

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("failure", ["second_case", "restore"])
def test_failed_drill_keeps_evidence_and_cannot_report_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    drill = Mock(spec=recovery.Drill)
    drill.started = True
    drill.project_id = "fixture-project"
    drill.http = Mock()
    clean = {"mode": "clean", "checks_passed": True}
    abrupt = {"mode": "abrupt", "checks_passed": True}
    drill.execute_case.side_effect = (
        [clean, RuntimeError("injected failure")] if failure == "second_case" else [clean, abrupt]
    )
    if failure == "restore":
        drill.restore.side_effect = RuntimeError("injected failure")
    monkeypatch.setattr(recovery, "Drill", lambda output, base_url: drill)
    monkeypatch.setattr(sys, "argv", ["check_backend_recovery.py", "--output", str(tmp_path)])
    with pytest.raises(RuntimeError, match="injected failure"):
        recovery.main()
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["passed"] is False
    assert summary["cases"][0] == clean
    assert summary["restored_default_backend"] is (failure == "second_case")
    drill.http.close.assert_called_once()


def test_process_snapshot_normalizes_mount_order_but_preserves_mount_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drill = recovery.Drill.__new__(recovery.Drill)
    monkeypatch.setattr(drill, "compose", lambda args: "fixture-container")
    state = {
        "Status": "running",
        "Pid": 123,
        "StartedAt": "fixture-start",
        "FinishedAt": "",
        "ExitCode": 0,
    }
    mounts = [
        {"Type": "bind", "Source": "/fixture/app.py", "Destination": "/app/recovery_app.py"},
        {"Type": "volume", "Source": "/fixture/data", "Destination": "/data", "Name": "data"},
    ]
    changed = [*mounts[:1], {**mounts[1], "Source": "/different/data"}]
    responses = [
        json.dumps(value)
        for value in (state, mounts, state, list(reversed(mounts)), state, changed)
    ]
    monkeypatch.setattr(drill, "command", Mock(side_effect=responses))
    before = drill.state("backend")
    assert drill.state("backend") == before
    assert drill.state("backend") != before
