# Claude Code CLI Adapter

Runs ESPAI Agent Bench tasks via the [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code).

## Setup

```sh
npm install -g @anthropic-ai/claude-code
claude login   # stores auth via browser OAuth
```

Verify: `claude --version`

## How it works

1. ESPAI generates a scoped task prompt from the task definition + project context.
2. ESPAI spawns: `claude --print --dangerously-skip-permissions`
3. The prompt is piped to stdin.
4. stdout is captured as task messages in real time.
5. File changes are diff'd against the pre-run snapshot.

## Note on `--dangerously-skip-permissions`

This flag is required for non-interactive use. ESPAI's own permission model (allowed
paths, blocked secrets, dev-only device deploy) enforces the security boundary
independently of Claude's internal permission prompts.
