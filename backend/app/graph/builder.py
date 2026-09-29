from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph import nodes
from app.graph.state import PipelineState

PipelineGraph = CompiledStateGraph[PipelineState, None, PipelineState, PipelineState]


def build_graph(checkpointer: BaseCheckpointSaver[str]) -> PipelineGraph:
    graph: StateGraph[PipelineState, None, PipelineState, PipelineState] = StateGraph(PipelineState)

    graph.add_node("profile", nodes.profile_node)
    graph.add_node("modeler", nodes.modeler_node)
    graph.add_node("clarify", nodes.clarify_node)
    graph.add_node("design_gate", nodes.design_gate_node)
    graph.add_node("codegen", nodes.codegen_node)
    graph.add_node("execute", nodes.execute_node)
    graph.add_node("optimize", nodes.optimize_node)
    graph.add_node("code_gate", nodes.code_gate_node)
    graph.add_node("publish", nodes.publish_node)
    graph.add_node("dashboard", nodes.dashboard_node)

    graph.add_edge(START, "profile")
    graph.add_edge("profile", "modeler")
    graph.add_conditional_edges("modeler", nodes.route_after_modeler)
    graph.add_edge("clarify", "modeler")
    graph.add_conditional_edges("design_gate", nodes.route_after_design_gate)
    graph.add_edge("codegen", "execute")
    graph.add_conditional_edges("execute", nodes.route_after_execute)
    graph.add_edge("optimize", "code_gate")
    graph.add_conditional_edges("code_gate", nodes.route_after_code_gate)
    graph.add_edge("publish", "dashboard")
    graph.add_edge("dashboard", END)

    return graph.compile(checkpointer=checkpointer)
