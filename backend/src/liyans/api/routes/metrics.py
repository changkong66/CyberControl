from __future__ import annotations

from fastapi import APIRouter, Request, Response

router = APIRouter(tags=["operations"])


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    platform_metrics = request.app.state.metrics
    return Response(
        content=platform_metrics.render(),
        media_type=platform_metrics.content_type,
    )
