from pydantic import BaseModel


class PipelineExample(BaseModel):
    example_id: str
    source: str
    dataset: str
    task_id: str
    description: str
    model_sql: str


class ExampleStore:
    def __init__(self, qdrant_url: str, collection: str, embedding_model: str, api_key: str):
        self.qdrant_url = qdrant_url
        self.collection = collection
        self.embedding_model = embedding_model
        self.api_key = api_key

    async def ensure_collection(self) -> None:
        """TODO: create the Qdrant collection with the embedding dimension if missing."""
        raise NotImplementedError

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """TODO: embed texts with gemini-embedding-001."""
        raise NotImplementedError

    async def upsert(self, examples: list[PipelineExample]) -> None:
        """TODO: embed descriptions and upsert points with dataset/task_id payload."""
        raise NotImplementedError

    async def search(
        self, description: str, top_k: int, exclude_datasets: list[str] | None = None
    ) -> list[PipelineExample]:
        """TODO: nearest examples, filtering out eval datasets/tasks to prevent answer leakage."""
        raise NotImplementedError
