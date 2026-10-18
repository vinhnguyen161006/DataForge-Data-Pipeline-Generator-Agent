import asyncio
import os

import httpx


class MetabaseSpike:
    """Spike for Metabase API: auth, sync, and creating dashboard or cards.

    Run this to understand Metabase API behaviors, especially sync delays
    and ID references.
    """

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url
        self.username = username
        self.password = password
        self.client = httpx.AsyncClient(base_url=self.base_url)
        self.headers: dict[str, str] = {}

    async def login(self) -> None:
        """Authenticate and set session headers."""
        response = await self.client.post(
            "/api/session",
            json={"username": self.username, "password": self.password},
        )
        response.raise_for_status()
        session_id = response.json()["id"]
        self.headers = {
            "X-Metabase-Session": session_id,
            "Content-Type": "application/json",
        }

    async def sync_database(self, db_id: int) -> None:
        """Trigger schema sync for a specific database ID.

        Note: Metabase sync is asynchronous. The API returns immediately,
        but the schema might take several seconds to appear.
        """
        response = await self.client.post(
            f"/api/database/{db_id}/sync_schema",
            headers=self.headers,
        )
        response.raise_for_status()

    async def create_dashboard(self, name: str) -> int:
        """Create a dashboard and return its ID."""
        response = await self.client.post(
            "/api/dashboard",
            headers=self.headers,
            json={"name": name},
        )
        response.raise_for_status()
        return int(response.json()["id"])

    async def create_card(self, db_id: int, name: str) -> int:
        """Create a sample KPI card and return its ID."""
        payload = {
            "name": name,
            "dataset_query": {
                "type": "query",
                "database": db_id,
                "query": {"aggregation": [["count"]]},
            },
            "display": "scalar",
            "visualization_settings": {},
        }
        response = await self.client.post(
            "/api/card",
            headers=self.headers,
            json=payload,
        )
        response.raise_for_status()
        return int(response.json()["id"])

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()


async def main() -> None:
    """Execute the spike flow."""
    password = os.environ.get("DATAFORGE_METABASE_PASSWORD", "dummy_password")
    spike = MetabaseSpike(
        base_url="http://localhost:3000",
        username="admin@dataforge.local",
        password=password,
    )
    try:
        await spike.login()
        await spike.sync_database(db_id=2)
        dashboard_id = await spike.create_dashboard("DataForge Spike Dashboard")
        card_id = await spike.create_card(db_id=2, name="Total Records KPI")
        print(f"Created Dashboard ID: {dashboard_id}")
        print(f"Created Card ID: {card_id}")
        print("Note: Check the Metabase UI to verify.")
    finally:
        await spike.close()


if __name__ == "__main__":
    asyncio.run(main())
