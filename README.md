# Muster

A fleet of named, headless [Claude Code](https://docs.anthropic.com/en/docs/claude-code) agents coordinated by a central control plane.

Each **agent** is a long-lived async process running on one of your boxes (homelab
nodes over ZeroTier, RunPod, etc.). It names itself, probes its capabilities,
opens a single WebSocket to the **control plane**, registers, heartbeats its
liveness, and runs free-text jobs through Claude Code headless — streaming results
back over the same socket. The control plane tracks the fleet and dispatches jobs;
chat **connectors** (Slack, Teams) will feed jobs in and route results back.

## Repository layout

This is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/);
one virtual environment and one `uv.lock` cover every package.

```
muster/
├─ packages/
│  ├─ contracts/      muster-contracts    — the wire protocol (pure Pydantic models)
│  ├─ controlplane/   muster-controlplane — FastAPI hub: registry, heartbeat, dispatch
│  └─ agent/          muster-agent        — Claude Code headless wrapper
└─ tests/integration/                     — real agent ↔ live control plane round-trip
```

### `muster-contracts`
The single shared dependency every other package compiles against: the
`Register` / `Heartbeat` / `Job` / `Result` message envelopes, the (opaque-for-now)
capability manifest, and the `Ingress` ABC every connector will implement. Pure
models with no I/O.

### `muster-controlplane`
A FastAPI hub. Agents connect to the `/agent` WebSocket and register; the hub keeps
a `name → {capabilities, status, last_seen}` registry, derives liveness from a
heartbeat TTL, and dispatches jobs to any live agent (capability matching comes
later). A small HTTP surface (`POST /jobs`, `GET /jobs/{id}`, `GET /agents`) stands
in for the chat connectors until those exist.

### `muster-agent`
Names itself, probes host capabilities (GPUs via `nvidia-smi`, tools on `PATH`,
declared hosts/accounts/labels), connects to the control plane, registers, and
heartbeats. Incoming jobs run through Claude Code headless, streaming partial then
final results. Reconnects with exponential backoff and re-registers on drop. Every
external boundary (socket, subprocess, GPU probe, sleep) is injected, so the whole
loop is testable with **no network, no `claude` binary, and no GPU**.

## Design principles

- **Contract-first.** All wire I/O goes through `muster-contracts` models and
  `parse_message`; raw JSON is never hand-built or hand-parsed.
- **Inject every boundary.** Transports, subprocesses, clocks and sleeps are
  injected, keeping each package unit-testable in isolation at 100% coverage.
- **Async end to end.** No blocking calls in the event loop.

## Getting started

```bash
uv sync                       # create the workspace venv from uv.lock
```

### Run the test suites

Each package enforces 100% branch coverage:

```bash
uv run --directory packages/contracts    pytest
uv run --directory packages/agent        pytest
uv run --directory packages/controlplane pytest
uv run pytest tests/integration          # real agent ↔ live hub, end to end
```

The integration test boots `muster-controlplane` under uvicorn on an ephemeral
port and drives the real `Agent` (with its real WebSocket client) through a full
register → dispatch → stream-results loop. The only stand-in is the job runner, so
it needs neither the `claude` binary nor a GPU.

### Type checking

```bash
uv run --directory packages/agent        mypy --strict src/muster_agent
uv run --directory packages/controlplane mypy --strict src/muster_controlplane
```

### Run a component

```bash
# Control plane (defaults to 0.0.0.0:8000)
uv run --directory packages/controlplane muster-controlplane

# Agent — point it at a control plane
MUSTER_AGENT_CONTROL_PLANE_URL=ws://localhost:8000/agent \
  uv run --directory packages/agent muster-agent
```

Agent configuration is environment-driven with the `MUSTER_AGENT_` prefix; see
[`packages/agent/README.md`](packages/agent/README.md) for the full list.

## Status

Built: `contracts`, `controlplane` (minimal hub), `agent`, and the end-to-end
integration test. Not yet built: `muster-common`, the connector ingress surface,
the Slack/Teams connectors, and `deploy/` (compose + systemd units + Dockerfiles).
