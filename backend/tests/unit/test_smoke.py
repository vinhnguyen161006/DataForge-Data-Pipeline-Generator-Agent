from httpx import AsyncClient
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.builder import build_graph


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.json() == {"status": "ok"}


def test_graph_compiles(checkpointer: InMemorySaver) -> None:
    graph = build_graph(checkpointer)
    assert {"profile", "design_gate", "code_gate", "publish", "dashboard"} <= set(graph.nodes)
