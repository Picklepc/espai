# Codex CLI Adapter

Runs ESPAI Agent Bench tasks via the [OpenAI Codex CLI](https://github.com/openai/codex).

## Setup

```sh
npm install -g @openai/codex
export OPENAI_API_KEY=sk-...   # or set in your shell profile
```

Verify: `codex --version`

## How it works

1. ESPAI generates a scoped task prompt from the task definition + project context.
2. The prompt is written to a temp file in the task workspace.
3. ESPAI spawns: `codex exec --json <prompt-file>`
4. stdout JSON lines are captured as task messages.
5. File changes are diff'd against the pre-run snapshot.

## Prompt templates

- `prompts/system.md` — injected as the system context
- `prompts/task.md`   — Jinja2 template for the per-task user prompt
