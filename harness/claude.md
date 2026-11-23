# review-pr in Claude Code

- **Work dir** (`<DIR>`): `<scratchpad>/review-<n>/` (the session's scratchpad directory, absolute path), or `/tmp/review-pr/<n>-<YYYYmmdd-HHMM>/` if no scratchpad is active.
- **Session id**: `$CLAUDE_CODE_SESSION_ID` (also the scratchpad's parent folder name). Resume with `cd <repo_dir> && claude --resume <id>`.
- **Unattended**: can be started via `claude -p "/review-pr <n> unattended"` with write tools denied.

## Native subagents (`provider: "native"` or `provider: "claude"` inside Claude Code)

When a role in `config.json` uses `provider: "native"` (or `provider: "claude"` while already running in Claude Code), you can spawn it directly with the `Agent` tool:
- `subagent_type: "general-purpose"`
- `model`: role's configured `model` (if the `Agent` tool rejects a full model id, pass its family alias like `sonnet`/`opus` and prepend `"Reason at <effort> effort."` to the brief)
- `effort`: role's configured `effort` (default `low`)
- Prompt: `"Follow the brief in <DIR>/briefs/<role>.md"`

Start every native subagent and external `run_agent.py` runner (as background Bash commands) in **one turn**.

Any connected MCP servers (e.g. Figma `mcp__plugin_figma_figma__*`, browser `mcp__chrome-devtools__*`) are inherited by `Agent` subagents.

## Tools

- Issue trackers: use read-only MCP tools (`mcp__azure-devops__wit_work_item`, `mcp__azure-devops__search_workitem`, `mcp__azure-devops__wit_query`, or Jira/Linear read tools) or `gh issue view` for GitHub Issues. Never call write tools.
- Figma screenshots (Section 5, when Figma MCP is enabled): `mcp__plugin_figma_figma__get_screenshot`.
