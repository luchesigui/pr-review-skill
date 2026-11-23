#!/usr/bin/env python3
"""Shared stdlib-only helpers for /review-pr scripts.

Resolves SKILL_DIR and STATE_DIR (REVIEW_PR_HOME -> <SKILL_DIR>/local -> ~/.config/review-pr),
loads user config and per-repo profiles, detects GitHub repo/login, and resolves docs paths
for all three documentation modes ("none", "skill", "folder").
"""
import copy
import glob
import json
import os
import re
import subprocess

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)

DEFAULT_CONFIG = {
    "version": 2,
    "user": {
        "name": "",
        "github_login": "",
        "screenshot_dir": "",
    },
    "default_repo": "",
    "docs": {
        "mode": "skill",  # "none" | "skill" | "folder"
        "folder": "",
        "per_repo_subfolder": True,
        "external_front_matter": False,
    },
    "author_notes": {
        "mode": "propose",  # "propose" | "auto" | "off"
        "extra_files": [],
    },
    "issue_tracker": {
        "type": "github",  # "github" | "azure-devops" | "jira" | "linear" | "none"
        "pattern": r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?)\s+#(\d+)|#(\d+)",
        "org": "",
        "project": "",
        "url_template": "",
    },
    "design": {
        "mode": "off",  # "off" | "screenshots-only" | "figma-mcp"
        "figma_map": "",
        "browser_preview": False,
        "local_preview_url": "",
        "credentials_env": "",
    },
    "agents": {
        "preset": "claude-only",
        "timeout_seconds": 900,
        "roles": {
            "design": {"enabled": "auto", "provider": "native", "model": "sonnet", "effort": "low"},
            "reuse": {"enabled": True, "provider": "native", "model": "sonnet", "effort": "low"},
            "general": {"enabled": True, "provider": "native", "model": "sonnet", "effort": "low"},
            "general_escalated": {"enabled": True, "provider": "native", "model": "opus", "effort": "low"},
            "claim": {"enabled": "auto", "provider": "native", "model": "sonnet", "effort": "low"},
            "da_overflow": {"enabled": "auto", "provider": "native", "model": "sonnet", "effort": "low"},
        },
        "custom_commands": {},
    },
    "routing": {
        "small_diff_max_files": 5,
        "small_diff_max_lines": 50,
        "escalate_min_lines": 800,
        "sensitive_path_regex": r"(payment|stripe|billing|checkout.*(card|pay|intent|challenge)|auth|login|session|token|secret|oauth|credential|password|crypto|security|rbac|acl|permission)",
        "sensitive_diff_regex": r"(client_?secret|payment_?intent|setup_?intent|dangerouslySetInnerHTML|innerHTML|jwt|bearer\s+token|api_?key|private_?key|eval\()",
        "ui_extensions": [".tsx", ".jsx", ".vue", ".svelte", ".scss", ".css", ".less"],
        "shared_prefixes": ["libs/", "packages/", "shared/"],
        "stack_prefixes": {},
        "cross_stack_groups": [],
    },
    "hooks": {
        "pre_review": "",
        "post_review": "",
        "outcomes": "",
    },
    "extra_linters": [],
}


def run(cmd, cwd=None, check=True, input_text=None, timeout=None):
    r = subprocess.run(
        cmd,
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:6])} failed (exit {r.returncode}): {r.stderr.strip()}")
    return r


def deep_merge(base, override):
    out = copy.deepcopy(base)
    if not isinstance(override, dict):
        return out
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def state_dir(create=False):
    """Return local user state directory: REVIEW_PR_HOME -> <SKILL_DIR>/local -> ~/.config/review-pr."""
    env_home = os.environ.get("REVIEW_PR_HOME", "").strip()
    if env_home:
        p = os.path.abspath(os.path.expanduser(env_home))
        if create:
            os.makedirs(p, exist_ok=True)
        return p

    local_dir = os.path.join(SKILL_DIR, "local")
    if os.path.isdir(local_dir) and os.access(local_dir, os.W_OK):
        return local_dir
    if os.access(SKILL_DIR, os.W_OK):
        if create:
            os.makedirs(local_dir, exist_ok=True)
        return local_dir

    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip() or os.path.expanduser("~/.config")
    fallback = os.path.join(xdg, "review-pr")
    if create:
        os.makedirs(fallback, exist_ok=True)
    return fallback


def config_path():
    return os.path.join(state_dir(), "config.json")


def is_configured():
    return os.path.isfile(config_path())


def load_config():
    p = config_path()
    if not os.path.isfile(p):
        return copy.deepcopy(DEFAULT_CONFIG)
    with open(p, encoding="utf-8") as fh:
        user_cfg = json.load(fh)
    return deep_merge(DEFAULT_CONFIG, user_cfg)


def repo_slug(gh_repo):
    return re.sub(r"[^A-Za-z0-9._-]+", "__", (gh_repo or "unknown").strip("/"))


def parse_github_remote(url):
    url = (url or "").strip()
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?$", url, re.I)
    return m.group(1) if m else ""


def detect_gh_repo(repo_dir=None, cfg=None):
    cwd = repo_dir or os.getcwd()
    r = run(["git", "-C", cwd, "remote", "get-url", "origin"], check=False)
    if r.returncode == 0:
        parsed = parse_github_remote(r.stdout)
        if parsed:
            return parsed
    r = run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], cwd=cwd, check=False)
    if r.returncode == 0 and "/" in r.stdout.strip():
        return r.stdout.strip()
    return (cfg or {}).get("default_repo", "")


def detect_git_root(start_dir=None):
    cwd = start_dir or os.getcwd()
    r = run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], check=False)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return os.path.abspath(cwd)


def detect_github_login(cfg=None):
    login = ((cfg or {}).get("user") or {}).get("github_login") or ""
    if login:
        return login.strip()
    r = run(["gh", "api", "user", "-q", ".login"], check=False)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return ""


def load_repo_profile(gh_repo):
    """Return (override_dict, markdown_text_or_empty, md_path_or_none) for a repo."""
    slug = repo_slug(gh_repo)
    rdir = os.path.join(state_dir(), "repos")
    jpath = os.path.join(rdir, f"{slug}.json")
    mpath = os.path.join(rdir, f"{slug}.md")
    override = {}
    if os.path.isfile(jpath):
        try:
            with open(jpath, encoding="utf-8") as fh:
                override = json.load(fh)
        except Exception:
            override = {}
    md = ""
    if os.path.isfile(mpath):
        with open(mpath, encoding="utf-8", errors="replace") as fh:
            md = fh.read()
    return override, md, (mpath if os.path.isfile(mpath) else None)


def effective_config(gh_repo=None):
    cfg = load_config()
    if gh_repo:
        override, _, _ = load_repo_profile(gh_repo)
        if override:
            cfg = deep_merge(cfg, override)
    return cfg


def docs_paths(cfg, gh_repo):
    """Return (mode, reviews_dir_or_none, data_dir_or_none)."""
    docs = cfg.get("docs") or {}
    mode = (docs.get("mode") or "skill").lower()
    if mode == "none":
        return "none", None, None
    if mode == "folder" and docs.get("folder"):
        base = os.path.abspath(os.path.expanduser(docs["folder"]))
        if docs.get("per_repo_subfolder"):
            base = os.path.join(base, repo_slug(gh_repo))
        return "folder", base, os.path.join(base, ".data")
    # Default: "skill"
    base = os.path.join(state_dir(), "reviews", repo_slug(gh_repo))
    return "skill", base, os.path.join(base, ".data")


def parse_front_matter(path):
    """Minimal YAML front-matter reader (stdlib-only)."""
    text = open(path, encoding="utf-8", errors="replace").read()
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.startswith((" ", "\t", "-")):
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            items = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
            fm[k] = items
        else:
            fm[k] = v.strip("'\"")
    return fm, m.group(2)


def find_pr_note(reviews_dir, pr_num):
    if not reviews_dir or not os.path.isdir(reviews_dir):
        return None
    patterns = [
        os.path.join(reviews_dir, f"PR-{pr_num} *.md"),
        os.path.join(reviews_dir, f"PR-{pr_num}.md"),
    ]
    for pat in patterns:
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


def next_round_number(data_dir, pr_num, note_fm=None):
    if note_fm and str(note_fm.get("round") or "").isdigit():
        return int(note_fm["round"]) + 1
    if not data_dir:
        return 1
    rounds = glob.glob(os.path.join(data_dir, str(pr_num), "round-*.json"))
    nums = []
    for r in rounds:
        m = re.search(r"round-(\d+)\.json$", r)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def expand_path(p):
    return os.path.abspath(os.path.expanduser(p)) if p else ""
