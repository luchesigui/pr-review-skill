#!/usr/bin/env python3
"""Environment diagnostics and setup auto-detection for /review-pr.

Usage:
    python3 -I doctor.py                # Human-readable health check
    python3 -I doctor.py --detect-json  # Machine-readable detection for /review-pr setup
"""
import argparse
import json
import os
import platform
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common


def detect_environment():
    clis = {}
    for tool in ("gh", "git", "rg", "claude", "codex", "grok", "gemini", "agy", "node", "npx"):
        clis[tool] = shutil.which(tool) or ""

    gh_login = ""
    if clis["gh"]:
        r = common.run(["gh", "api", "user", "-q", ".login"], check=False)
        if r.returncode == 0:
            gh_login = r.stdout.strip()

    git_root = common.detect_git_root()
    gh_repo = common.detect_gh_repo(git_root)
    sdir = common.state_dir()
    cfg_exists = common.is_configured()
    cfg = common.load_config() if cfg_exists else {}

    return {
        "os": platform.system(),
        "python": platform.python_version(),
        "skill_dir": common.SKILL_DIR,
        "state_dir": sdir,
        "configured": cfg_exists,
        "config_path": common.config_path(),
        "gh_login": gh_login,
        "git_root": git_root,
        "gh_repo": gh_repo,
        "clis": clis,
        "available_ai_clis": [k for k in ("claude", "codex", "grok", "gemini", "agy") if clis.get(k)],
        "config_summary": {
            "docs_mode": (cfg.get("docs") or {}).get("mode"),
            "docs_folder": (cfg.get("docs") or {}).get("folder"),
            "author_notes_mode": (cfg.get("author_notes") or {}).get("mode"),
            "issue_tracker": (cfg.get("issue_tracker") or {}).get("type"),
            "design_mode": (cfg.get("design") or {}).get("mode"),
            "preset": (cfg.get("agents") or {}).get("preset"),
        } if cfg_exists else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detect-json", action="store_true")
    args = ap.parse_args()

    info = detect_environment()
    if args.detect_json:
        print(json.dumps(info, indent=2))
        return 0

    issues = []
    print(f"/review-pr doctor ({info['os']}, Python {info['python']})")
    print(f"  skill_dir : {info['skill_dir']}")
    print(f"  state_dir : {info['state_dir']}")
    print(f"  configured: {'yes' if info['configured'] else 'NO (run /review-pr setup)'}")
    print(f"  gh_login  : {info['gh_login'] or 'NOT AUTHENTICATED (run `gh auth login`)'}")
    print(f"  gh_repo   : {info['gh_repo'] or '(not inside a GitHub git repo)'}")
    print(f"  AI CLIs   : {', '.join(info['available_ai_clis']) or 'none detected (will use native subagents)'}")

    if not info["clis"]["gh"]:
        issues.append("`gh` CLI is required for PR review gathering.")
    elif not info["gh_login"]:
        issues.append("`gh` is installed but not authenticated (`gh auth login`).")
    if not info["clis"]["git"]:
        issues.append("`git` is required for worktrees and diffs.")

    if info["configured"]:
        cfg = common.effective_config(info["gh_repo"] or None)
        roles = (cfg.get("agents") or {}).get("roles") or {}
        print("\nConfigured agents:")
        for role, rcfg in roles.items():
            prov = rcfg.get("provider", "native")
            enabled = rcfg.get("enabled", True)
            status = "ok"
            if enabled is False:
                status = "disabled"
            elif prov not in ("native",) and prov not in (cfg.get("agents") or {}).get("custom_commands", {}):
                if not shutil.which(prov):
                    status = f"MISSING `{prov}` CLI on PATH"
                    issues.append(f"Role `{role}` uses `{prov}` which is not in PATH.")
            print(f"  - {role:18} {prov}/{rcfg.get('model','default')} ({rcfg.get('effort','low')}) [{status}]")

        mode, rev_dir, _ = common.docs_paths(cfg, info["gh_repo"] or "example/repo")
        print(f"\nDocs mode     : {mode}" + (f" ({rev_dir})" if rev_dir else ""))
        print(f"Author notes  : {(cfg.get('author_notes') or {}).get('mode', 'propose')} ({os.path.join(info['state_dir'], 'authors')})")
        print(f"Issue tracker : {(cfg.get('issue_tracker') or {}).get('type', 'github')}")
        print(f"Design mode   : {(cfg.get('design') or {}).get('mode', 'off')}")
        voice = os.path.join(info["state_dir"], "voice.md")
        print(f"Voice guide   : {'present' if os.path.isfile(voice) else 'not created yet (uses built-in defaults)'}")
        if info["gh_repo"]:
            _, md, mpath = common.load_repo_profile(info["gh_repo"])
            print(f"Repo profile  : {mpath if mpath else 'none for ' + info['gh_repo']}")

        for hname, hcmd in (cfg.get("hooks") or {}).items():
            if hcmd:
                print(f"Hook ({hname:11}): {hcmd}")

    if issues:
        print("\nIssues found:")
        for i in issues:
            print(f"  - {i}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
