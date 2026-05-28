# ESPAI Agent Bench — Adapters & Policies

This directory contains the adapter definitions, prompt templates, and policies
that govern how AI agents interact with the ESPAI platform.

## Structure

```
agents/
  adapters/          — One subdirectory per supported agent type
    codex/           — OpenAI Codex CLI adapter
    claude-code/     — Anthropic Claude Code CLI adapter
  tasks/             — JSON schema for task definitions
  policies/          — Security and permission policies
```

## Security Model

- Agents work in isolated workspaces under `agent-bench/generated/`
- Agents cannot read `secrets/`, `*.private.yaml`, `*.private.json`, `.env`
- Agents cannot OTA production or stable devices
- Agents cannot promote releases — humans do that
- All agent actions are logged in the hub database
- Imported or agent-generated workers start quarantined

## Adding a New Adapter

1. Create `agents/adapters/<name>/adapter.yaml`
2. Add prompts under `agents/adapters/<name>/prompts/`
3. Register via the hub UI: Settings → Agent Bench → Add Adapter
