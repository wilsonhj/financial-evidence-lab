"""Live extraction SSE: bounded reads release their tenant connection between polls."""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.errors import api_error
from app.extraction import events
from app.extraction.routes_runs import Tenant

router = APIRouter(prefix="/v1", tags=["extraction"])


@router.get("/extraction-runs/{runId}/events")
async def stream_events(
    runId: UUID,
    request: Request,
    ctx: Tenant,
    last_event_id: Annotated[
        str, Header(alias="Last-Event-ID", max_length=16, pattern=r"^(0|[1-9][0-9]*)$")
    ] = "0",
) -> StreamingResponse:
    after = int(last_event_id)
    if after > 2**53 - 1:
        raise api_error(422, "VALIDATION_ERROR", "Resume ID is outside the supported range.")
    initial = await run_in_threadpool(events.fetch, ctx, str(runId), after, check_resume=True)

    async def content() -> AsyncIterator[str]:
        last = after
        batch, status = initial
        heartbeat = time.monotonic()
        yield ": connected\n\n"
        while True:
            for event in batch:
                if await request.is_disconnected():
                    return
                yield events.frame(event)
                last = event["id"]
                if event["type"] in events.TERMINAL_EVENTS:
                    return
            if not batch and status in ("succeeded", "failed", "cancelled"):
                return
            if await request.is_disconnected():
                return
            if time.monotonic() - heartbeat >= 20:
                yield ": heartbeat\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(0.2)
            batch, status = await run_in_threadpool(events.fetch, ctx, str(runId), last)

    return StreamingResponse(
        content(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
