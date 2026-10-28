"""Close both application lifetimes around real profile execution and gate decisions."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

import pytest

from app.agents.schemas import ModelerOutput
from app.core.config import get_api_settings
from app.core.security import hash_password
from app.versioning import canonical_json_hash
from tests.recovery_backend import RecoveryScenario, registration_design

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from tests.recovery_backend import Backend, RunEvidence

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "linux", reason="Linux confined profile worker"),
]


@pytest.fixture(scope="module")
def recovery_password_hash() -> str:
    return hash_password("recovery-fixture-password")


@pytest.fixture
async def scenario(
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recovery_password_hash: str,
) -> AsyncIterator[RecoveryScenario]:
    recovery = RecoveryScenario(database_url, tmp_path / "storage", recovery_password_hash)
    try:
        await recovery.initialize()
        recovery.configure(monkeypatch)
        yield recovery
    finally:
        await recovery.cleanup()
        get_api_settings.cache_clear()


@pytest.fixture
async def paused_run(scenario: RecoveryScenario) -> RunEvidence:
    async with scenario.backend([ModelerOutput(design=registration_design())]) as backend_a:
        before = await backend_a.reach_gate()
    backend_a.lifetime.assert_closed()
    assert backend_a.app is None
    assert backend_a.client is None
    with pytest.raises(RuntimeError, match="closed"):
        backend_a.http()
    return before


def decision_body(view: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {
        "interrupt_id": view["interrupt_id"],
        "design_version_id": view["pending"]["design_version_id"],
        "decision": "approve",
        **changes,
    }


def revised_design_output() -> ModelerOutput:
    design = registration_design()
    design.metrics[0].definition = "Registrations excluding withdrawn students"
    return ModelerOutput(design=design)


async def assert_restored(backend: Backend, before: RunEvidence) -> None:
    assert backend.lifetime.generation == 2
    assert await backend.evidence(before.run_id) == before
    assert len(backend.scenario.lifetimes) == 2
    backend.scenario.lifetimes[0].assert_closed()
    assert backend.lifetime.engine_count == backend.lifetime.saver_count == 1
    assert backend.lifetime.graph_count == backend.lifetime.context_count == 1
    assert not backend.lifetime.engine_disposed
    assert not backend.lifetime.saver_closed


async def test_restart_preserves_gate_and_approval_executes_codegen_once(
    scenario: RecoveryScenario, paused_run: RunEvidence
) -> None:
    async with scenario.backend() as backend_b:
        await assert_restored(backend_b, paused_run)
        response = await backend_b.decide(paused_run.run_id, decision_body(paused_run.view))
        assert response.status_code == 200, response.text
        await backend_b.wait_for_codegen(paused_run.run_id)
        records = await backend_b.records(paused_run.run_id)
        assert records["jobs"] == paused_run.records["jobs"]
        assert records["designs"] == paused_run.records["designs"]
        assert len(records["approvals"]) == len(records["intents"]) == 1
        approval = records["approvals"][0]
        assert approval["actor_id"] == str(scenario.engineer_id)
        assert approval["decision"] == "approved"
        assert approval["fingerprint"] == paused_run.records["designs"][0]["hash"]
        assert (
            approval["parts"]["design_version_id"]
            == paused_run.view["pending"]["design_version_id"]
        )
        assert records["intents"][0]["actor_id"] == str(scenario.engineer_id)
        assert scenario.codegen_runs == [str(paused_run.run_id)]
        assert len(scenario.modeler_calls) == scenario.worker_executions == 1
    backend_b.lifetime.assert_closed()
    assert backend_b.app is None
    assert backend_b.client is None


async def test_restart_edited_approval_binds_new_version_and_keeps_presented_design(
    scenario: RecoveryScenario, paused_run: RunEvidence
) -> None:
    async with scenario.backend() as backend_b:
        await assert_restored(backend_b, paused_run)
        edited = registration_design()
        edited.facts[0].grain = "One confirmed registration per student, module and presentation"
        edited_json = edited.model_dump(mode="json")
        response = await backend_b.decide(
            paused_run.run_id, decision_body(paused_run.view, edited_design=edited_json)
        )
        assert response.status_code == 200, response.text
        await backend_b.wait_for_codegen(paused_run.run_id)
        records = await backend_b.records(paused_run.run_id)
        assert len(records["designs"]) == 2
        presented, approved = records["designs"]
        assert presented == paused_run.records["designs"][0]
        assert approved["id"] != presented["id"]
        assert approved["version"] == 2
        assert approved["edited"] is True
        assert approved["content"] == edited_json
        assert approved["hash"] == canonical_json_hash(edited_json)
        assert len(records["approvals"]) == len(records["intents"]) == 1
        approval = records["approvals"][0]
        assert approval["fingerprint"] == approved["hash"]
        assert approval["parts"]["design_version_id"] == approved["id"]
        assert approval["parts"]["presented_design_version_id"] == presented["id"]
        assert approval["actor_id"] == str(scenario.engineer_id)
        assert records["jobs"] == paused_run.records["jobs"]
        assert scenario.codegen_runs == [str(paused_run.run_id)]
        assert len(scenario.modeler_calls) == scenario.worker_executions == 1
    backend_b.lifetime.assert_closed()


async def test_restart_return_revisits_modeler_without_codegen(
    scenario: RecoveryScenario, paused_run: RunEvidence
) -> None:
    output = revised_design_output()
    async with scenario.backend([output]) as backend_b:
        await assert_restored(backend_b, paused_run)
        response = await backend_b.decide(
            paused_run.run_id,
            decision_body(paused_run.view, decision="return", comment="  Exclude withdrawals  "),
        )
        assert response.status_code == 200, response.text
        current = await backend_b.wait_for_gate(paused_run.run_id, version=2)
        records = await backend_b.records(paused_run.run_id)
        assert current["interrupt_id"] != paused_run.view["interrupt_id"]
        assert (
            current["pending"]["design_version_id"]
            != paused_run.view["pending"]["design_version_id"]
        )
        assert len(records["designs"]) == 2
        assert records["designs"][0] == paused_run.records["designs"][0]
        assert output.design is not None
        assert records["designs"][1]["content"] == output.design.model_dump(mode="json")
        assert len(records["approvals"]) == len(records["intents"]) == 1
        assert records["approvals"][0]["decision"] == "returned"
        assert records["approvals"][0]["actor_id"] == str(scenario.engineer_id)
        assert records["approvals"][0]["comment"] == "Exclude withdrawals"
        assert records["jobs"] == paused_run.records["jobs"]
        assert scenario.modeler_calls[-1] == {
            "generation": 2,
            "returned_design": paused_run.view["pending"]["design"],
            "reviewer_feedback": "Exclude withdrawals",
        }
        assert len(scenario.modeler_calls) == 2
        assert scenario.worker_executions == 1
        assert scenario.codegen_runs == []
    backend_b.lifetime.assert_closed()


@pytest.mark.parametrize("decision", ["approve", "return"])
async def test_repeated_decision_after_restart_does_not_duplicate_work(
    scenario: RecoveryScenario, paused_run: RunEvidence, decision: str
) -> None:
    outputs = [revised_design_output()] if decision == "return" else []
    async with scenario.backend(outputs) as backend_b:
        await assert_restored(backend_b, paused_run)
        body = decision_body(
            paused_run.view,
            decision=decision,
            **({"comment": "Exclude withdrawals"} if decision == "return" else {}),
        )
        first = await backend_b.decide(paused_run.run_id, body)
        assert first.status_code == 200, first.text
        if decision == "return":
            await backend_b.wait_for_gate(paused_run.run_id, version=2)
        else:
            await backend_b.wait_for_codegen(paused_run.run_id)
        accepted = await backend_b.evidence(paused_run.run_id)
        repeated = await backend_b.decide(paused_run.run_id, body)
        assert repeated.status_code == 409, repeated.text
        assert await backend_b.evidence(paused_run.run_id) == accepted
        assert len(accepted.records["approvals"]) == len(accepted.records["intents"]) == 1
        assert accepted.records["jobs"] == paused_run.records["jobs"]
    backend_b.lifetime.assert_closed()


@pytest.mark.parametrize("stale_field", ["interrupt_id", "design_version_id", "both"])
async def test_stale_design_identity_after_restart_and_return_is_rejected(
    scenario: RecoveryScenario, paused_run: RunEvidence, stale_field: str
) -> None:
    async with scenario.backend([revised_design_output()]) as backend_b:
        await assert_restored(backend_b, paused_run)
        returned = await backend_b.decide(
            paused_run.run_id,
            decision_body(paused_run.view, decision="return", comment="Exclude withdrawals"),
        )
        assert returned.status_code == 200, returned.text
        current = await backend_b.wait_for_gate(paused_run.run_id, version=2)
        accepted = await backend_b.evidence(paused_run.run_id)
        stale = decision_body(current)
        if stale_field in {"interrupt_id", "both"}:
            stale["interrupt_id"] = paused_run.view["interrupt_id"]
        if stale_field in {"design_version_id", "both"}:
            stale["design_version_id"] = paused_run.view["pending"]["design_version_id"]
        response = await backend_b.decide(paused_run.run_id, stale)
        assert response.status_code == 409, response.text
        assert await backend_b.evidence(paused_run.run_id) == accepted
        assert scenario.codegen_runs == []
        assert len(scenario.modeler_calls) == 2
        assert scenario.worker_executions == 1
    backend_b.lifetime.assert_closed()
