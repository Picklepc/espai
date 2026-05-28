# ESPAI Agent Bench

Agent Bench is an optional feature that lets you use AI coding agents
(Claude Code, Codex, or manual copy/paste) to develop ESPAI projects
from within the hub interface.

## How it works

1. Enable in Settings → Agent Bench
2. Create a task from any Project page
3. ESPAI generates a scoped prompt using `.agent` rules and project context
4. Agent works in an isolated workspace (never touches production state)
5. Diffs, build results, and messages are captured
6. You review and approve before any merge

## Directory layout

```
agent-bench/
  task-templates/     — Starter templates for common task types
  review-checklists/  — What to verify before approving a task
  generated/          — Task workspaces (gitignored; created at runtime)
```

## Security

Agents are constrained by `agents/policies/default-agent-policy.yaml`:
- Cannot read secrets or private configs
- Cannot OTA production devices
- Cannot promote releases
- All file writes are logged

## Enabling

In the hub UI: Settings → Agent Bench → Enable
Or set `ESPAI_AGENT_BENCH=true` in `.env`
