from google import genai
from qdrant_client import QdrantClient, models

from app.core.config import get_api_settings


def main() -> None:
    settings = get_api_settings()
    client = QdrantClient(url=settings.qdrant_url, timeout=10)

    try:
        print(client.get_collections())
    finally:
        client.close()

    api_key = settings.gemini_api_key.get_secret_value()
    if not api_key:
        raise ValueError("DATAFORGE_GEMINI_API_KEY must be configured.")

    gemini = genai.Client(api_key=api_key)

    try:
        response = gemini.models.embed_content(
            model=settings.gemini_embedding_model,
            contents="Design a fact table for student outcomes by module.",
        )

        if not response.embeddings:
            raise ValueError("Gemini returned no embeddings.")

        vector = response.embeddings[0].values
        if not vector:
            raise ValueError("Gemini returned an empty vector.")

        print("Model:", settings.gemini_embedding_model)
        print("Dimensions:", len(vector))
        print("First 5 values:", vector[:5])
    finally:
        gemini.close()

    collection_name = "spike_embedding_2"
    client = QdrantClient(url=settings.qdrant_url, timeout=10)

    try:
        if not client.collection_exists(collection_name):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=len(vector),
                    distance=models.Distance.COSINE,
                ),
            )

        client.upsert(
            collection_name=collection_name,
            points=[
                models.PointStruct(
                    id=1,
                    vector=vector,
                    payload={
                        "text": "Design a fact table for student outcomes by module.",
                        "embedding_model": settings.gemini_embedding_model,
                    },
                )
            ],
            wait=True,
        )

        print("Stored points:", client.count(collection_name, exact=True).count)
        result = client.query_points(
            collection_name=collection_name,
            query=vector,
            limit=1,
            with_payload=True,
        )

        for point in result.points:
            print("Matched ID:", point.id)
            print("Similarity:", point.score)
            print("Payload:", point.payload)
    finally:
        client.close()


if __name__ == "__main__":
    main()
