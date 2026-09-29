from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    run_id: str
    project_id: str
    batch_id: str
    request_text: str

    profile: dict[str, Any]
    clarification_answers: list[dict[str, str]]
    design_version_id: str
    design: dict[str, Any]
    design_approved: bool
    design_feedback: str | None

    code_version_id: str
    execution_job_id: str
    execution_report: dict[str, Any]
    fix_attempts: int

    rewrite_log: list[dict[str, Any]]

    code_approval_id: str
    code_approved: bool
    code_feedback: str | None

    published_version_id: str
    dashboard_url: str
    error: str | None
