# review-pr in Codex

- **Work dir** (`<DIR>`): `/tmp/review-pr/<n>-<YYYYmmdd-HHMM>/`. Create it first; use the absolute path everywhere.
- **Session id**: the `id` in the first line of the newest `~/.codex/sessions/**/rollout-*.jsonl` whose `cwd` is this repo (also the UUID at the end of its filename). Resume with `cd <repo_dir> && codex resume <id>`.

## Agents & runners

- For roles configured with an external CLI provider (`claude`, `codex`, `grok`, `gemini`, `agy`, or custom), invoke `<SKILL_DIR>/scripts/run_agent.py` in parallel background commands.
- For roles configured with `provider: "native"` (or as a fallback if a configured CLI is unavailable), spawn Codex's own read-only subagents (one per brief) and note any substitution in the `Agents:` line.

## Tools

- Issue trackers: `gh issue view` for GitHub Issues, or read-only MCP tools configured in `.codex/config.toml` (e.g. `azure-devops`, Jira, Linear).
- Figma screenshots (Section 5): if Codex has no Figma MCP connected, either let a `claude`-backed Design runner capture the screenshot or tell the user which frame to capture.
