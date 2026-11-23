#!/usr/bin/env python3
"""Standalone outcome matcher for /review-pr ("Grow this skill" without an external dashboard).

Compares drafted findings in round-*.json files against your actual posted GitHub PR comments
to compute per-agent and per-category acceptance rates (posted, rewritten, not posted, pending,
self-pr, plus comments you added that no agent drafted).

Usage:
    python3 -I outcomes.py [<pr>] [--gh-repo owner/repo]
"""
import argparse
import datetime as dt
import difflib
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common


def parse_ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def norm_text(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def similarity(a, b):
    na, nb = norm_text(a), norm_text(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def code_tokens(s):
    return {t for t in re.findall(r"`([^`\n]{3,60})`", s or "") if not t.isspace()}


def agent_names(finding):
    names = [a.strip().split()[0].lower() for a in str(finding.get("agents") or "").split(",") if a.strip()]
    return names or ["unknown"]


def my_pr_comments(gh_repo, pr_num, me):
    raw = common.run(["gh", "api", f"repos/{gh_repo}/pulls/{pr_num}/comments", "--paginate"], check=False).stdout or "[]"
    try:
        items = json.loads(raw)
    except Exception:
        return []
    return [c for c in items if ((c.get("user") or {}).get("login") or "").lower() == me.lower()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pr", nargs="?", type=int)
    ap.add_argument("--gh-repo", default="")
    args = ap.parse_args()

    repo_dir = common.detect_git_root()
    base_cfg = common.load_config()
    gh_repo = args.gh_repo or common.detect_gh_repo(repo_dir, base_cfg)
    cfg = common.effective_config(gh_repo)
    me = common.detect_github_login(cfg)
    mode, _, data_dir = common.docs_paths(cfg, gh_repo)

    if mode == "none" or not data_dir or not os.path.isdir(data_dir):
        print(f"No stored round files (docs.mode={mode}). Switch to 'skill' or 'folder' mode to track outcomes.")
        return 0
    if not me:
        print("Could not detect GitHub login. Configure user.github_login or run `gh auth login`.")
        return 1

    pr_dirs = [os.path.join(data_dir, str(args.pr))] if args.pr else sorted(glob.glob(os.path.join(data_dir, "[0-9]*")))
    agg = {"by_agent": {}, "by_category": {}}
    added_all = []

    for pdir in pr_dirs:
        if not os.path.isdir(pdir):
            continue
        base = os.path.basename(pdir)
        if not base.isdigit():
            continue
        n = int(base)
        rounds = []
        for f in glob.glob(os.path.join(pdir, "round-*.json")):
            try:
                rounds.append(json.load(open(f, encoding="utf-8")))
            except Exception:
                pass
        rounds = sorted((r for r in rounds if r.get("findings")), key=lambda r: r.get("round", 0))
        if not rounds:
            continue

        mine = my_pr_comments(gh_repo, n, me)
        used, rows = set(), []
        first = parse_ts(rounds[0].get("date"))
        is_self = bool(rounds[0].get("is_self_pr"))

        for r in rounds:
            since = parse_ts(r.get("date"))
            for f in r["findings"]:
                best, score = None, 0.0
                for c in mine:
                    ct = parse_ts(c.get("created_at"))
                    if c["id"] in used or (since and ct and ct < since - dt.timedelta(hours=1)):
                        continue
                    s = similarity(f.get("comment"), c.get("body"))
                    near = (
                        c.get("path") == f.get("file")
                        and f.get("line")
                        and abs((c.get("line") or c.get("original_line") or 0) - int(f["line"])) <= 3
                    )
                    if s >= 0.6 or (near and s >= 0.3):
                        sc = s + (0.2 if near else 0.0)
                        if sc > score:
                            best, score = c, sc
                split = []
                if not best:
                    want = code_tokens(f.get("comment"))
                    got = set()
                    for c in mine:
                        ct = parse_ts(c.get("created_at"))
                        if c["id"] in used or (since and ct and ct < since - dt.timedelta(hours=1)):
                            continue
                        shared = want & code_tokens(c.get("body"))
                        if shared:
                            split.append(c)
                            got |= shared
                    if not (len(got) >= 2 and want and len(got) >= 0.4 * len(want)):
                        split = []

                posted_later = any(parse_ts(c.get("created_at")) >= since for c in mine if parse_ts(c.get("created_at"))) if since else bool(mine)
                if best:
                    used.add(best["id"])
                    raw = similarity(f.get("comment"), best.get("body"))
                    outcome = "posted" if raw >= 0.9 else "rewritten"
                elif split:
                    used.update(c["id"] for c in split)
                    outcome = "rewritten"
                    raw = max(similarity(f.get("comment"), c.get("body")) for c in split)
                elif is_self:
                    outcome = "self-pr"
                elif not posted_later:
                    outcome = "pending"
                else:
                    outcome = "not posted"

                row = {
                    "round": r.get("round"),
                    "id": f.get("id"),
                    "file": f.get("file"),
                    "line": f.get("line"),
                    "category": f.get("category") or "other",
                    "agents": agent_names(f),
                    "outcome": outcome,
                }
                if best or split:
                    hits = [best] if best else split
                    row["similarity"] = round(raw, 2)
                    row["url"] = hits[0].get("html_url")
                    if outcome == "rewritten":
                        row["posted"] = "\n\n---\n\n".join(c["body"] for c in hits)
                rows.append(row)
                if outcome != "self-pr":
                    for key, names in (("by_agent", row["agents"]), ("by_category", [row["category"]])):
                        for name in names:
                            b = agg[key].setdefault(name, {"drafted": 0, "posted": 0, "rewritten": 0, "not posted": 0, "pending": 0})
                            b["drafted"] += 1
                            b[outcome] += 1

        added = [
            {
                "pr": n,
                "file": c.get("path"),
                "line": c.get("line") or c.get("original_line"),
                "body": c["body"],
                "url": c.get("html_url"),
            }
            for c in mine
            if c["id"] not in used and not c.get("in_reply_to_id")
            and first and parse_ts(c.get("created_at")) and parse_ts(c.get("created_at")) >= first
        ]
        added_all += added
        with open(os.path.join(pdir, "outcomes.json"), "w", encoding="utf-8") as fh:
            json.dump({"findings": rows, "added": added}, fh, indent=2)

    for b in list(agg["by_agent"].values()) + list(agg["by_category"].values()):
        decided = b["posted"] + b["rewritten"] + b["not posted"]
        b["used_rate"] = round((b["posted"] + b["rewritten"]) / decided, 2) if decided else None

    if not args.pr:
        with open(os.path.join(data_dir, "outcomes.json"), "w", encoding="utf-8") as fh:
            json.dump(
                {"generated": dt.datetime.now(dt.timezone.utc).isoformat(), **agg, "added": added_all},
                fh,
                indent=2,
            )

    for key in ("by_agent", "by_category"):
        print(key.replace("_", " ") + ":")
        for name, b in sorted(agg[key].items(), key=lambda kv: -kv[1]["drafted"]):
            rate = "-" if b["used_rate"] is None else f"{int(b['used_rate'] * 100)}%"
            print(
                f"  {name:14} drafted {b['drafted']:3}  posted {b['posted']:3}  "
                f"rewritten {b['rewritten']:3}  not posted {b['not posted']:3}  "
                f"pending {b['pending']:3}  used {rate}"
            )
    print(f"added by reviewer (no draft): {len(added_all)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
