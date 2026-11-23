# Setup `/review-pr`

Run this interactive setup on first use (when `<STATE_DIR>/config.json` does not exist) or whenever the user asks to configure `/review-pr`.

Keep it conversational and fast — ask concise questions, show detected defaults, and write a clean `<STATE_DIR>/config.json` + `<STATE_DIR>/voice.md`.

## Step 1: Detect environment

Run:
```
python3 -I <SKILL_DIR>/scripts/doctor.py --detect-json
```

Show a 3-line summary of what was detected:
- GitHub login (`gh_login`) and current repo (`gh_repo`)
- Available AI CLIs (`available_ai_clis`)
- Local state directory (`state_dir`)

If `gh` is missing or unauthenticated, tell the user to run `gh auth login` first.

## Step 2: Configure AI providers & models per task

Offer presets based on `available_ai_clis`, then let the user accept defaults or customize any role:

| Preset | Design | Reuse | General | General (escalated / sensitive) | Claim |
|---|---|---|---|---|---|
| **Native (current AI only)** | `native` (default, low) | `native` (default, low) | `native` (default, low) | `native` (stronger/default, medium) | `native` (default, low) |
| **Claude-only** | `claude` / `sonnet` (low) | `claude` / `sonnet` (low) | `claude` / `sonnet` (low) | `claude` / `opus` (low, medium if sensitive) | `claude` / `sonnet` (low) |
| **Codex-only** | `codex` / default (low) | `codex` / default (low) | `codex` / default (low) | `codex` / default (medium) | `codex` / default (low) |
| **Multi-AI ensemble** *(when multiple CLIs detected)* | `claude` / `sonnet` (low) | `grok` / `grok-4` (low) | `claude` / `sonnet` (low) | `claude` / `opus` (low, medium if sensitive) | `codex` / default (low) |
| **Custom** | User picks provider (`native`, `claude`, `codex`, `grok`, `gemini`, or custom command) + model + effort per role | | | | |

Notes:
- Remind the user they can disable any role (`enabled: false`) — e.g. disable `design` if they don't do frontend/Figma reviews.
- Exact model names are stored in `config.json` so users can pin any model ID their CLI supports.

## Step 3: PR documentation mode

Ask how they want reviewed PRs documented:
1. **`skill` (Recommended default)** — Keep PR notes and structured `round-*.json` files inside `<STATE_DIR>/reviews/<owner>__<repo>/` (gitignored, self-contained, enables local `outcomes.py` stats).
2. **`folder`** — Store PR notes and `.data/` in a custom folder (e.g. an Obsidian vault or notes directory). Ask for the folder path and whether to organize by repo subfolder (`per_repo_subfolder: true/false`).
3. **`none`** — Don't write PR notes locally; rely on the AI session and GitHub comment history. (Rechecks still work by inferring the last reviewed commit from GitHub.)

## Step 4: Author mannerisms, issue tracker, and design checks

Ask briefly about these three options (with sensible defaults):
1. **Author mannerisms (`author_notes.mode`):**
   - `propose` *(Recommended)* — Automatically track who you review in `<STATE_DIR>/authors/<login>.md` and propose factual, PR-cited review mannerisms for your approval after reviews/rechecks.
   - `auto` — Record factual observations automatically without asking.
   - `off` — Disable author profiles.
2. **Issue tracker (`issue_tracker.type`):**
   - `github` *(Default — zero extra setup, uses `gh issue view`)*
   - `azure-devops` (ask for `org`, `project`, and ticket pattern e.g. `AB#(\d+)`)
   - `jira` (ask for ticket pattern e.g. `([A-Z]{2,10}-\d+)`)
   - `linear` (ask for ticket pattern e.g. `([A-Z]{2,10}-\d+)`)
   - `none`
3. **Design review (`design.mode`):**
   - `off` *(Default for backend/non-Figma repos)*
   - `screenshots-only` (compares PR screenshots and UI code without Figma MCP)
   - `figma-mcp` (full Figma MCP + optional headless browser; ask if they have a Figma map file or local preview URL)

## Step 5: Voice calibration

Offer two ways to create `<STATE_DIR>/voice.md`:
1. **Learn from my GitHub history (Recommended):** If the user agrees, fetch their last 15–20 PR review comments across recent PRs (`gh api` search/comments), distill 6–10 concrete tone/formatting rules + 3–5 anonymized before/after examples, show the draft for approval, and save to `<STATE_DIR>/voice.md`.
2. **Start from a preset:** Copy [templates/voice.example.md](templates/voice.example.md) to `<STATE_DIR>/voice.md` (offer *Concise & direct*, *Collaborative / coaching*, or *Thorough* tweak).

## Step 6: Save & verify

1. Write `<STATE_DIR>/config.json` with `python3 -I` and `json.dump`.
2. Create empty `<STATE_DIR>/past-reviews.md` if it doesn't exist yet.
3. Run:
   ```
   python3 -I <SKILL_DIR>/scripts/doctor.py
   ```
4. Show the doctor output and tell the user they're ready to run `/review-pr <number>` (and that they can create optional per-repo rules in `<STATE_DIR>/repos/<owner>__<repo>.md` anytime).
