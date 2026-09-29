from typing import Any


class MetabaseClient:
    def __init__(self, base_url: str, user: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.password = password

    async def login(self) -> None:
        """TODO: POST /api/session and keep the session token."""
        raise NotImplementedError

    async def sync_database_schema(self, database_id: int) -> None:
        """TODO: POST /api/database/{id}/sync_schema and wait until the new tables are visible."""
        raise NotImplementedError

    async def create_card(self, spec: dict[str, Any]) -> int:
        """TODO: POST /api/card and return the new card id."""
        raise NotImplementedError

    async def update_card(self, card_id: int, spec: dict[str, Any]) -> None:
        """TODO: PUT /api/card/{id}."""
        raise NotImplementedError

    async def run_card_query(self, card_id: int) -> dict[str, Any]:
        """TODO: POST /api/card/{id}/query and return the result payload."""
        raise NotImplementedError

    async def create_dashboard(self, name: str) -> int:
        """TODO: POST /api/dashboard and return the new dashboard id."""
        raise NotImplementedError

    async def set_dashboard_cards(self, dashboard_id: int, card_ids: list[int]) -> None:
        """TODO: PUT /api/dashboard/{id} with a deterministic grid layout."""
        raise NotImplementedError

    def dashboard_url(self, dashboard_id: int) -> str:
        """TODO: public link returned to the Engineer."""
        raise NotImplementedError
