# muster-agent

A long-lived, headless Muster agent. It names itself, probes its host
capabilities (GPUs, installed tools, declared hosts/accounts/labels), opens a
single WebSocket to the control plane, registers, heartbeats its status, and runs
incoming jobs through **Claude Code headless** — streaming partial results and a
final outcome back over the same socket. It reconnects with exponential backoff
and re-registers when the socket drops.

## Design

Every external boundary is injected, so the whole register/heartbeat/job loop is
exercised with **no network, no `claude` binary, and no GPU**:

| Boundary | Production | Tests |
| --- | --- | --- |
| Control-plane socket | `connect_websocket` (`websockets`) | `FakeTransport` |
| Job execution | `ClaudeCodeRunner` (subprocess) | `FakeRunner` |
| GPU probe | `nvidia-smi` via `subprocess.run` | injected `run` |
| Tool probe | `shutil.which` | injected `which` |
| Sleep / backoff | `asyncio.sleep` | injected `sleep` |

All wire I/O goes through `muster-contracts` models and `parse_message`; raw JSON
is never hand-built or hand-parsed.

Scope note: capabilities are *collected and reported only* — reading or matching
on them belongs to the control plane. Jobs run one at a time.

## Configuration

Settings are environment-driven with the `MUSTER_AGENT_` prefix (nested values
use `__`), e.g.:

```bash
export MUSTER_AGENT_CONTROL_PLANE_URL=ws://hub.zero:8000/agent
export MUSTER_AGENT_AGENT_NAME=atlas
export MUSTER_AGENT_LABELS__zone=homelab
```

## Run

```bash
uv sync
uv run muster-agent        # probes, connects, registers, serves
uv run pytest              # 100% coverage enforced
uv run mypy --strict src/muster_agent
```
