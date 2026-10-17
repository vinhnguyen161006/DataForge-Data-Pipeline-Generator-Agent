from typing import Any, Literal

from langgraph.runtime import Runtime

from app.graph.context import GraphContext
from app.graph.state import PipelineState


async def profile_node(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """TODO: enqueue a sandbox "profile" job, interrupt until the job result is delivered.

    Enqueue with idempotency_key "profile:<run_id>" and commit before interrupting with
    JobWait, because the node re-runs from the top on resume. The resume value is a
    JobOutcome; a succeeded result is validated as DataProfile, a failure sets `error`.
    """
    raise NotImplementedError


async def modeler_node(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """TODO: call runtime.context.propose_design; persist a DesignVersion or pending questions.

    A design is stored as the next DesignVersion with content_hash from
    runtime.context.hash_design and resets `design_approved`; questions go to `questions`.
    """
    raise NotImplementedError


async def clarify_node(state: PipelineState) -> dict[str, Any]:
    """TODO: interrupt with ClarificationRequest; append the ClarificationReply answers."""
    raise NotImplementedError


async def design_gate_node(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """TODO: gate 1 (FR-06): interrupt with DesignGateRequest; resume value is DesignGateReply.

    An edited design becomes a new DesignVersion (edited_by_user). Record an Approval
    bound to the hash of the design actually decided on, skipping an identical record
    left by a re-run.
    """
    raise NotImplementedError


async def codegen_node(state: PipelineState) -> dict[str, Any]:
    """TODO: refuse unless the design is approved; retrieve examples, generate, assemble a
    CodeVersion.
    """
    raise NotImplementedError


async def execute_node(state: PipelineState) -> dict[str, Any]:
    """TODO: enqueue a sandbox "dbt_build" job and interrupt until its report is delivered."""
    raise NotImplementedError


async def optimize_node(state: PipelineState) -> dict[str, Any]:
    """TODO: rank slow models, gather rule + LLM candidates within budget, benchmark in sandbox.

    Judge each candidate deterministically, log every rejection, keep the best
    valid version (a new CodeVersion with origin "optimizer" when a rewrite is kept).
    """
    raise NotImplementedError


async def code_gate_node(state: PipelineState) -> dict[str, Any]:
    """TODO: gate 2 (FR-13): interrupt with diff, tests, perf table and dashboard config.

    Store the Approval with the VersionParts fingerprint; in team mode the
    reviewer must differ from the engineer, in solo mode flag no independent review.
    """
    raise NotImplementedError


async def publish_node(state: PipelineState) -> dict[str, Any]:
    """TODO: verify the approval still matches, enqueue a publisher "publish" job, wait for it."""
    raise NotImplementedError


async def dashboard_node(state: PipelineState) -> dict[str, Any]:
    """TODO: enqueue a publisher "metabase_sync" job, wait, store the dashboard URL."""
    raise NotImplementedError


def route_after_profile(state: PipelineState) -> Literal["modeler", "__end__"]:
    """TODO: end the run when the profile job failed; otherwise go to the Modeler."""
    raise NotImplementedError


def route_after_modeler(state: PipelineState) -> Literal["clarify", "design_gate"]:
    """TODO: go to clarify when the Modeler returned questions."""
    raise NotImplementedError


def route_after_design_gate(state: PipelineState) -> Literal["codegen", "modeler"]:
    """TODO: codegen only when approved; otherwise back to the Modeler with feedback."""
    raise NotImplementedError


def route_after_execute(state: PipelineState) -> Literal["optimize", "codegen", "__end__"]:
    """TODO: on failure retry codegen within max_fix_attempts, else end with an error."""
    raise NotImplementedError


def route_after_code_gate(state: PipelineState) -> Literal["publish", "codegen"]:
    """TODO: publish only when approved; otherwise back to Codegen with feedback."""
    raise NotImplementedError
