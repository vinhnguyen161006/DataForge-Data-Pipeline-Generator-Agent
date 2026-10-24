from fastapi import APIRouter, Request, Response, status

from app.core.readiness import JobDeliveryStatus

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request, response: Response) -> dict[str, str]:
    delivery: JobDeliveryStatus | None = getattr(request.app.state, "job_delivery_status", None)
    if delivery is not None and not delivery.healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}
    return {"status": "ok"}
