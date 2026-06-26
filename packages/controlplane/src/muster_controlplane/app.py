"""FastAPI entrypoint wiring the hub: agent WS surface + minimal job API.

:func:`create_app` builds an app with its own registry, connection manager and
result store, exposes the ``/agent`` WebSocket for agents, and offers a small HTTP
surface (submit a job, read its results, list agents) standing in for the ingress
connectors until those exist. The collaborators are attached to ``app.state`` so
tests and future routers can reach them.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel

from muster_contracts import Origin

from muster_controlplane.agent_ws import ConnectionManager, handle_agent
from muster_controlplane.dispatch import NoAvailableAgent, ResultStore, dispatch_job
from muster_controlplane.registry import Registry


class JobRequest(BaseModel):
    """A request to dispatch one instruction to the fleet."""

    instruction: str
    origin: Origin


def create_app() -> FastAPI:
    """Build a hub application with fresh, isolated state."""
    app = FastAPI(title="muster-controlplane")
    registry = Registry()
    connections = ConnectionManager()
    results = ResultStore()
    app.state.registry = registry
    app.state.connections = connections
    app.state.results = results

    @app.websocket("/agent")
    async def agent_socket(websocket: WebSocket) -> None:
        """Serve one agent connection: register, heartbeats, results."""
        await handle_agent(websocket, registry, connections, results.add)

    @app.post("/jobs")
    async def submit_job(request: JobRequest) -> dict[str, str]:
        """Dispatch an instruction to any live agent, returning its job id."""
        try:
            job = await dispatch_job(connections, request.instruction, request.origin)
        except NoAvailableAgent as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"job_id": str(job.job_id)}

    @app.get("/jobs/{job_id}")
    async def read_job(job_id: UUID) -> dict[str, object]:
        """Return the results collected so far for a job, and whether it is done."""
        collected = results.results(job_id)
        return {
            "final": results.final(job_id) is not None,
            "results": [
                {"status": r.status.value, "content": r.content, "final": r.final}
                for r in collected
            ],
        }

    @app.get("/agents")
    async def list_agents() -> list[dict[str, object]]:
        """Return a snapshot of every registered agent."""
        return [
            {
                "name": r.name,
                "status": r.status.value,
                "current_job_id": str(r.current_job_id) if r.current_job_id else None,
                "capabilities": r.capabilities.model_dump(),
            }
            for r in registry.all()
        ]

    return app


app = create_app()
"""Module-level app instance for ASGI servers (``uvicorn muster_controlplane.app:app``)."""


def main() -> None:  # pragma: no cover
    """Run the hub under uvicorn (container/systemd entrypoint)."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
