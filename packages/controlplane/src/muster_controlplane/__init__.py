"""muster-controlplane: the central hub agents register and report to.

Re-exports the hub's public surface — the app factory plus the registry,
connection, dispatch and result primitives the WebSocket and HTTP routes compose.
"""

from muster_controlplane.agent_ws import (
    AgentConnection,
    ConnectionManager,
    handle_agent,
)
from muster_controlplane.app import JobRequest, create_app
from muster_controlplane.dispatch import NoAvailableAgent, ResultStore, dispatch_job
from muster_controlplane.heartbeat import ingest, is_live, live_records
from muster_controlplane.registry import AgentRecord, Registry

__all__ = [
    "AgentConnection",
    "AgentRecord",
    "ConnectionManager",
    "JobRequest",
    "NoAvailableAgent",
    "Registry",
    "ResultStore",
    "create_app",
    "dispatch_job",
    "handle_agent",
    "ingest",
    "is_live",
    "live_records",
]
