"""Versioning, identity and nested result validation for the profile wire protocol."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.profiler.schemas import DataProfile
from tests.designs import minimal_profile
from tests.profile_jobs import make_profile_job
from worker.profile_protocol import PreparedProfileJob, ProfileChildRequest, ProfileChildResponse

if TYPE_CHECKING:
    from pathlib import Path


def test_request_and_response_round_trip_without_credentials(tmp_path: Path) -> None:
    _, job = make_profile_job(tmp_path)
    request = ProfileChildRequest(job=job)
    assert ProfileChildRequest.model_validate_json(request.model_dump_json()) == request
    response = ProfileChildResponse(identity=job.identity, profile=minimal_profile())
    assert ProfileChildResponse.model_validate_json(response.model_dump_json()) == response
    body = request.model_dump_json()
    assert "storage_path" not in body
    assert "database_url" not in body
    assert "password" not in body


@pytest.mark.parametrize("field", ["schema_version", "identity", "duckdb_limits"])
def test_unknown_request_fields_or_versions_are_rejected(tmp_path: Path, field: str) -> None:
    _, job = make_profile_job(tmp_path)
    body = ProfileChildRequest(job=job).model_dump(mode="json")
    if field == "schema_version":
        body[field] = 2
    elif field == "identity":
        body[field] = {}
    else:
        body[field]["arbitrary_sql"] = "SELECT 1"
    with pytest.raises(ValidationError):
        ProfileChildRequest.model_validate(body)


@pytest.mark.parametrize("field", ["project_id", "batch_id", "attempt"])
def test_identity_must_be_valid_and_match_snapshot(tmp_path: Path, field: str) -> None:
    _, job = make_profile_job(tmp_path)
    body = job.model_dump(mode="json")
    body["identity"][field] = 0 if field == "attempt" else str(uuid4())
    with pytest.raises(ValidationError):
        PreparedProfileJob.model_validate(body)


@pytest.mark.parametrize("field", ["manifest_version", "read_config_confirmed", "relative_path"])
def test_nested_manifest_is_revalidated(tmp_path: Path, field: str) -> None:
    _, job = make_profile_job(tmp_path)
    body = job.model_dump(mode="json")
    if field == "manifest_version":
        body["manifest"][field] = 2
    else:
        body["manifest"]["files"][0][field] = (
            False if field.endswith("confirmed") else "../outside.csv"
        )
    with pytest.raises(ValidationError):
        PreparedProfileJob.model_validate(body)


@pytest.mark.parametrize("value", [-1, True, "3"])
def test_profile_counts_reject_invalid_types_and_values(value: object) -> None:
    body = minimal_profile().model_dump()
    body["tables"][0]["row_count"] = value
    with pytest.raises(ValidationError):
        DataProfile.model_validate(body)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("null_ratio", -0.1),
        ("null_ratio", 1.1),
        ("null_ratio", float("nan")),
        ("distinct_count", -1),
        ("sample_values", ["x"] * 6),
    ],
)
def test_profile_statistics_are_bounded(field: str, value: object) -> None:
    body = minimal_profile().model_dump()
    body["tables"][0]["columns"][0][field] = value
    with pytest.raises(ValidationError):
        DataProfile.model_validate(body)


def test_raw_rows_cannot_be_smuggled_into_result() -> None:
    body = minimal_profile().model_dump()
    body["tables"][0]["raw_rows"] = [["fixture-only"]]
    with pytest.raises(ValueError, match="raw_rows"):
        DataProfile.model_validate_json(json.dumps(body))
