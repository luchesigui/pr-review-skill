# `/review-pr` — Evidence-Based AI Pull Request Review Skill

A portable, read-only pull request review skill for **Claude Code**, **Codex**, and **Antigravity**.

## What It Does

Most AI PR reviews skim a diff once and produce noisy, generic, or hallucinated comments. `/review-pr` is built to produce **high-signal, low-noise reviews in your own voice**:

- **Read-only by design** — never edits your repo, pushes, posts comments, or approves unless you explicitly ask.
- **Evidence-first** — every comment must anchor on a real diff line, quote real code from the PR head, and cite verified file paths/symbols.
- **Multi-perspective & model-flexible** — runs up to four focused specialist reviewers in parallel, each configurable to whichever AI provider and model you want (single-provider or multi-model ensemble).
- **Self-challenging** — runs a deterministic gate script and a Devil's Advocate pass before showing you anything, filtering out duplicates, already-raised threads, out-of-scope nits, and false positives.
- **Learns over time** — calibrates to your review voice, measures which drafted comments you actually posted vs. rewrote/dropped, and tracks factual per-author review mannerisms (proposed for your confirmation).
- **Flexible documentation** — choose whether to store PR review logs nowhere (`none`), inside the skill (`skill`), or in an external folder/vault (`folder`), with optional hooks for external dashboards or schedulers.

---

## How It Works

```text
PR # / URL
   │
   ▼
1. Deterministic Gather (scripts/gather.py)
   ├─ Fetches PR metadata, diff, and paginated review threads via `gh`
   ├─ Checks out an isolated git worktree pinned to `headRefOid`
   ├─ Loads repo instruction chain (AGENTS.md / CLAUDE.md), repo profile,
   │  linked ticket, related PR history, author notes, and extra linters
   └─ Computes routing metadata (small-diff fast path, sensitive/cross-stack escalation)
   │
   ▼
2. Parallel Specialist Agents (agents.md + scripts/run_agent.py)
   ├─ Design  (optional) ── Figma / screenshots vs. implementation
   ├─ Reuse              ── existing utils, components, types, i18n messages
   ├─ General            ── correctness, failure paths, security, schemas, tests, conventions
   │                        (auto-escalates model/effort or splits by stack on large/sensitive PRs)
   └─ Claim              ── ticket acceptance criteria, prior decisions, next-story friction, PR claims
   │
   ▼
3. Deterministic Gate (scripts/gate.py) — no LLM, pure Python
   ├─ Verifies diff line anchors (and re-anchors or rejects un-commentable lines)
   ├─ Verifies every backticked code quote exists in the diff or PR head
   ├─ Verifies every cited `path:line` and symbol exists at PR head
   └─ Rejects no-op or overlapping ```suggestion blocks
   │
   ▼
4. Devil's Advocate (orchestrator)
   ├─ Deduplicates findings and checks overlap against existing PR threads
   ├─ Argues for the code as written against the real checkout, ticket scope, and author notes
   └─ Keeps only STANDS / DEFENSIBLE findings (moves uncertain items to Unverified)
   │
   ▼
5. Voice & Output (local/voice.md)
   ├─ Rewrites surviving comments in your tone with ready-to-paste suggestion blocks
   ├─ Validates final round JSON with `gate.py --validate-round --fill-hunks`
   ├─ Cleans up the temporary worktree
   └─ Documents per your chosen mode (`none` | `skill` | `folder`) + optional hooks
```

### Shareable Core vs. Private Local State

Everything personal or company-specific lives in `local/` (gitignored) — or in `REVIEW_PR_HOME` / `~/.config/review-pr/` if the skill is installed read-only:

```text
review-pr/
├── SKILL.md, setup.md, agents.md, recheck.md   # Public workflow & briefs
├── harness/                                    # Claude Code, Codex, Antigravity adapters
├── scripts/                                    # Stdlib-only Python scripts (gather, gate, run_agent, authors, outcomes, doctor)
├── figma/figma_map.py                          # Optional config-driven Figma index generator
├── templates/                                  # Example config, voice guide, repo profile, author note
└── local/                                      # GITIGNORED — your config, voice, authors, repo profiles, reviews
```

---

## How to Use It

### Prerequisites

- **Python 3.9+** (standard library only — no `pip install` needed)
- **`git`**
- **GitHub CLI (`gh`)**, authenticated (`gh auth login`)
- **An AI coding harness** — Claude Code, Codex, or Antigravity (plus any extra CLIs such as `claude`, `codex`, `grok`, or `gemini` if you want a multi-provider setup)

### 1. Install

Clone into your skills directory (or keep one copy and symlink it across harnesses):

```bash
git clone https://github.com/luchesigui/pr-review-skill.git ~/.claude/skills/review-pr

# Optional: share the exact same skill & local/ state across harnesses
ln -s ~/.claude/skills/review-pr ~/.codex/skills/review-pr
ln -s ~/.claude/skills/review-pr ~/.gemini/config/skills/review-pr
```

### 2. First-Time Setup

Run `/review-pr setup` (or run `/review-pr 123` directly — it launches setup automatically if no config exists).

The setup flow detects your GitHub login and installed AI CLIs, then walks you through:

1. **AI providers & models per task** — pick a preset (`native`, `claude-only`, `codex-only`, `multi-ai`) or assign a provider, model, and reasoning effort per role (`design`, `reuse`, `general`, `general_escalated`, `claim`, `da_overflow`).
2. **PR documentation mode**:
   - `skill` *(default)* — saves PR notes and round JSONs in gitignored `local/reviews/<owner>__<repo>/`.
   - `folder` — writes PR notes and `.data/` to a separate folder (e.g. an Obsidian vault or external dashboard).
   - `none` — writes no PR notes locally; relies on your session and GitHub comment history (rechecks infer the last reviewed commit directly from GitHub).
3. **Author mannerisms (`propose` | `auto` | `off`)** — tracks authors in `local/authors/<github-login>.md` and proposes factual, PR-cited review observations for your approval.
4. **Issue tracker** — `github` (default via `gh`), `azure-devops`, `jira`, `linear`, or `none`.
5. **Design review** — `off`, `screenshots-only`, or `figma-mcp`.
6. **Voice calibration** — generates `local/voice.md` from your last 15–20 GitHub PR comments or copies `templates/voice.example.md`.

Verify your setup anytime:

```bash
python3 -I scripts/doctor.py
```

### 3. Everyday Commands

| Prompt | What it does |
|---|---|
| `/review-pr 123` *(or PR URL)* | Full parallel review (auto-downgrades to shallow on tiny non-UI, non-sensitive diffs) |
| `/review-pr shallow 123` | Fast single-pass review inline (no external subagents, skips Design) |
| `/review-pr recheck 123` | Verifies every posted thread (open **and** resolved) against head code, summarizes open peer threads, detects reverted files and side effects, and proposes new author notes if warranted |
| `/review-pr grow` | Matches drafted comments against what you posted on GitHub and proposes improvements to your voice, repo rules, briefs, and author profiles |
| `/review-pr authors` | Lists tracked PR authors and their review notes |
| `/review-pr setup` | Reconfigure models, docs mode, tracker, or integrations |
| `/review-pr doctor` | Run environment and config health checks |

### 4. Optional Customization

- **Per-repo rules:** Copy `templates/repo-profile.example.md` to `local/repos/<owner>__<repo>.md` for repo-specific conventions and "Not worth raising" items. Add `local/repos/<owner>__<repo>.json` to override stack prefixes, sensitive regexes, extra linters (e.g. Stylelint), issue tracker, or Figma config for that repo.
- **External dashboards & schedulers:** Set `hooks.pre_review`, `hooks.post_review`, and `hooks.outcomes` in `local/config.json` and consume the validated `round-<k>.json` files. Unattended runs (`/review-pr <n> unattended`) skip interactive prompts and hooks automatically.
- **Custom state directory:** Set `REVIEW_PR_HOME=/path/to/dir` to store all personal state outside the skill folder.
