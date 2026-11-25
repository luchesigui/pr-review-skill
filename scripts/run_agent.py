#!/usr/bin/env python3
"""Provider-agnostic read-only agent runner and routing planner for /review-pr.

Dispatches a specialist brief to the CLI/provider configured in local/config.json:
  claude | codex | grok | gemini | agy | custom | native

Usage:
    # Print planned agents, providers, models, and effort for a gathered PR:
    python3 -I run_agent.py --plan --meta <DIR>/meta.json

    # Run one agent role in read-only mode:
    python3 -I run_agent.py --role <design|reuse|general|general_escalated|claim|da_overflow> \
        --brief <DIR>/briefs/<role>.md --cwd <DIR>/head --out <DIR>/<role>.md \
        [--repo-dir <repo>] [--effort low|medium|high] [--timeout 900] [--gh-repo owner/repo]
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

CLAUDE_RO_TOOLS = [
    "Read", "Grep", "Glob",
    "Bash(git log:*)", "Bash(git show:*)", "Bash(git grep:*)",
    "Bash(git -C * log:*)", "Bash(git -C * show:*)", "Bash(git -C * grep:*)",
    "Bash(rg:*)",
]


def resolve_role(cfg, role_name):
    roles = (cfg.get("agents") or {}).get("roles") or {}
    return dict(roles.get(role_name) or {})


def print_plan(meta_path):
    meta = json.load(open(meta_path, encoding="utf-8"))
    cfg = common.effective_config(meta.get("gh_repo"))
    design_cfg = resolve_role(cfg, "design")
    reuse_cfg = resolve_role(cfg, "reuse")
    gen_key = "general_escalated" if meta.get("escalate_general") else "general"
    gen_cfg = resolve_role(cfg, gen_key)
    claim_cfg = resolve_role(cfg, "claim")

    parts = []
    if meta.get("small_diff_eligible"):
        print("small-diff fast path eligible -> inline shallow review (override if ticket has complex AC)")
        return 0

    if meta.get("has_ui") and meta.get("design_mode", "off") != "off" and design_cfg.get("enabled") is not False:
        parts.append(f"design: {design_cfg.get('provider')}/{design_cfg.get('model')} {design_cfg.get('effort', 'low')} ({meta.get('ui_files_count')} UI files)")
    else:
        reason = "no UI files" if not meta.get("has_ui") else f"design mode={meta.get('design_mode', 'off')}"
        parts.append(f"design: skipped ({reason})")

    if reuse_cfg.get("enabled") is not False:
        parts.append(f"reuse: {reuse_cfg.get('provider')}/{reuse_cfg.get('model')} {reuse_cfg.get('effort', 'low')}")

    eff = meta.get("general_effort") or gen_cfg.get("effort", "low")
    split_note = " (split by stack)" if meta.get("split_general_by_language") else ""
    parts.append(f"general: {gen_cfg.get('provider')}/{gen_cfg.get('model')} {eff}{split_note}")

    if claim_cfg.get("enabled") is not False:
        t_note = f"ticket {meta['main_ticket']}" if meta.get("main_ticket") else "if claim narrows scope / related decisions"
        parts.append(f"claim: {claim_cfg.get('provider')}/{claim_cfg.get('model')} ({t_note})")
    else:
        parts.append("claim: disabled")

    print("; ".join(parts))
    return 0


def build_command(provider, role_cfg, brief_path, cwd, work_dir, effort, repo_dir, custom_commands):
    model = role_cfg.get("model") or ""
    extra_tools = role_cfg.get("mcp_tools") or []

    if provider == "claude":
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("`claude` CLI not found in PATH")
        allowed = list(CLAUDE_RO_TOOLS) + list(extra_tools)
        cmd = [
            exe, "-p", f"Follow the brief in {brief_path}",
            "--permission-mode", "dontAsk",
            "--no-session-persistence",
            "--add-dir", work_dir,
            "--allowedTools", *allowed,
        ]
        if model:
            cmd += ["--model", model]
        if effort:
            cmd += ["--effort", effort]
        # Run from repo_dir when available so project MCPs (Figma/browser) load
        return cmd, (repo_dir or cwd), None

    if provider == "codex":
        exe = shutil.which("codex")
        if not exe:
            raise RuntimeError("`codex` CLI not found in PATH")
        cmd = [exe, "exec", "--ephemeral", "-s", "read-only", "-C", cwd]
        if model:
            cmd += ["-m", model]
        cmd.append("-")
        brief_text = open(brief_path, encoding="utf-8").read()
        return cmd, cwd, brief_text

    if provider == "grok":
        exe = shutil.which("grok")
        if not exe:
            raise RuntimeError("`grok` CLI not found in PATH")
        cmd = [
            exe, "--verbatim", "--no-subagents", "--disable-web-search",
            "--sandbox", "read-only", "--permission-mode", "dontAsk",
            "--cwd", cwd, "--max-turns", str(role_cfg.get("max_turns") or 40),
            "--prompt-file", brief_path,
        ]
        if model:
            cmd += ["--model", model]
        if effort:
            cmd += ["--reasoning-effort", effort]
        return cmd, cwd, None

    if provider == "agy":
        exe = shutil.which("agy")
        if not exe:
            raise RuntimeError("`agy` CLI not found in PATH")
        cmd = [exe, "--mode", "plan", "--sandbox", "--disable-slash-commands"]
        if model:
            cmd += ["--model", model]
        # Catalog IDs can encode an effort tier. Honor the selected variant as-is.
        if effort and not model.endswith(("-low", "-medium", "-high", "-xhigh", "-max")):
            cmd += ["--effort", effort]
        brief_text = open(brief_path, encoding="utf-8").read()
        cmd += ["--print", brief_text]
        return cmd, cwd, None

    if provider == "gemini":
        exe = shutil.which("gemini")
        if not exe:
            raise RuntimeError("`gemini` CLI not found in PATH")
        brief_text = open(brief_path, encoding="utf-8").read()
        cmd = [exe, "-p", brief_text]
        if model:
            cmd += ["-m", model]
        return cmd, cwd, None

    if provider in (custom_commands or {}):
        tpl = custom_commands[provider]
        fmt_vars = {
            "brief": brief_path,
            "cwd": cwd,
            "dir": work_dir,
            "model": model,
            "effort": effort or "low",
        }
        if isinstance(tpl, str):
            cmd = shlex.split(tpl.format(**fmt_vars))
        else:
            cmd = [part.format(**fmt_vars) for part in tpl]
        return cmd, cwd, None

    raise RuntimeError(f"Unsupported provider: {provider!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="Print agent routing summary from meta.json")
    ap.add_argument("--meta", help="Path to <DIR>/meta.json (for --plan)")
    ap.add_argument("--role", help="Role name from config.json (design, reuse, general, general_escalated, claim, da_overflow)")
    ap.add_argument("--brief", help="Absolute path to rendered brief markdown file")
    ap.add_argument("--cwd", help="Working directory for the agent (usually <DIR>/head)")
    ap.add_argument("--out", help="Output file path for stdout")
    ap.add_argument("--repo-dir", default="", help="Main repo checkout path (used by claude -p for project MCPs)")
    ap.add_argument("--gh-repo", default="", help="GitHub owner/repo for per-repo overrides")
    ap.add_argument("--effort", default="", help="Override configured effort (low|medium|high)")
    ap.add_argument("--timeout", type=int, default=0, help="Override configured timeout seconds")
    args = ap.parse_args()

    if args.plan:
        if not args.meta:
            ap.error("--plan requires --meta <DIR>/meta.json")
        return print_plan(args.meta)

    if not (args.role and args.brief and args.cwd and args.out):
        ap.error("Running an agent requires --role, --brief, --cwd, and --out")

    cfg = common.effective_config(args.gh_repo or None)
    role_cfg = resolve_role(cfg, args.role)
    if role_cfg.get("enabled") is False:
        print(f"{args.role}: disabled in config", file=sys.stderr)
        return 2

    provider = (role_cfg.get("provider") or "native").lower()
    if provider == "native":
        print(
            f"NATIVE_SUBAGENT role={args.role} model={role_cfg.get('model','default')} "
            f"effort={args.effort or role_cfg.get('effort','low')} brief={os.path.abspath(args.brief)}"
        )
        return 10

    effort = args.effort or role_cfg.get("effort") or "low"
    timeout = args.timeout or int(role_cfg.get("timeout_seconds") or (cfg.get("agents") or {}).get("timeout_seconds") or 900)
    brief_abs = os.path.abspath(args.brief)
    cwd_abs = os.path.abspath(args.cwd)
    work_dir = os.path.dirname(os.path.dirname(brief_abs)) if os.path.basename(os.path.dirname(brief_abs)) == "briefs" else os.path.dirname(brief_abs)
    custom_cmds = (cfg.get("agents") or {}).get("custom_commands") or {}

    try:
        cmd, run_cwd, stdin_txt = build_command(
            provider, role_cfg, brief_abs, cwd_abs, work_dir, effort, args.repo_dir, custom_cmds
        )
    except RuntimeError as e:
        print(f"ERROR ({args.role}): {e}", file=sys.stderr)
        return 1

    try:
        r = subprocess.run(
            cmd,
            cwd=run_cwd,
            input=stdin_txt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT ({args.role}): exceeded {timeout}s", file=sys.stderr)
        return 124

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(r.stdout or "")

    if r.returncode != 0:
        err_path = args.out + ".stderr"
        with open(err_path, "w", encoding="utf-8") as fh:
            fh.write(r.stderr or "")
        print(f"FAILED ({args.role}, exit {r.returncode}): see {err_path}", file=sys.stderr)
        return r.returncode

    if not (r.stdout or "").strip():
        print(f"EMPTY ({args.role}): runner returned empty output", file=sys.stderr)
        return 1

    print(f"OK ({args.role}): {provider}/{role_cfg.get('model','default')} -> {args.out} ({len(r.stdout)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
