#!/usr/bin/env python3
"""Manage local PR author profiles and review mannerisms.

Profiles live in <STATE_DIR>/authors/<github-login>.md (always local/gitignored).

Usage:
    python3 -I authors.py list
    python3 -I authors.py show <login>
    python3 -I authors.py touch <login> [--name "Display Name"] [--pr 123] [--repo owner/repo]
    python3 -I authors.py add-note <login> --pr 123 --note "Factual observation..." [--name "Display Name"]
"""
import argparse
import datetime
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common


def authors_dir(create=False):
    d = os.path.join(common.state_dir(create=create), "authors")
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def safe_login(login):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (login or "unknown").strip())


def author_path(login, create_dir=False):
    return os.path.join(authors_dir(create=create_dir), f"{safe_login(login)}.md")


def load_author(login):
    p = author_path(login)
    if not os.path.isfile(p):
        return None, {}, ""
    fm, body = common.parse_front_matter(p)
    return p, fm, body


def write_author(login, fm, body):
    p = author_path(login, create_dir=True)
    keys = ["login", "name", "first_seen", "last_reviewed", "prs_reviewed"]
    lines = ["---"]
    for k in keys:
        if k in fm and fm[k] is not None:
            v = fm[k]
            if isinstance(v, list):
                lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
            else:
                lines.append(f"{k}: {v}")
    for k, v in fm.items():
        if k not in keys and v is not None:
            lines.append(f"{k}: {v}")
    lines.append("---")
    content = "\n".join(lines) + "\n" + body.lstrip("\n")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(content)
    return p


def touch_author(login, name="", pr_num=None, gh_repo=""):
    if not login:
        return None
    today = datetime.date.today().isoformat()
    p, fm, body = load_author(login)
    if not p:
        display = name or login
        fm = {
            "login": login,
            "name": display,
            "first_seen": today,
            "last_reviewed": today,
            "prs_reviewed": [f"{gh_repo}#{pr_num}" if (gh_repo and pr_num) else f"#{pr_num}"] if pr_num else [],
        }
        body = f"\n# {display} (`@{login}`)\n\n## Review mannerisms\n\n<!-- Factual, PR-cited collaboration & code-review observations only. -->\n"
        return write_author(login, fm, body)

    if name and (not fm.get("name") or fm.get("name") == login):
        fm["name"] = name
    fm["last_reviewed"] = today
    prs = fm.get("prs_reviewed")
    if not isinstance(prs, list):
        prs = [prs] if prs else []
    if pr_num:
        tag = f"{gh_repo}#{pr_num}" if gh_repo else f"#{pr_num}"
        short_tag = f"#{pr_num}"
        if tag not in prs and short_tag not in prs:
            prs.append(tag)
    fm["prs_reviewed"] = prs[-50:]
    return write_author(login, fm, body)


def add_note(login, note, pr_num=None, name=""):
    if not login or not note.strip():
        raise ValueError("login and note are required")
    touch_author(login, name=name, pr_num=pr_num)
    _, fm, body = load_author(login)
    clean = note.strip().lstrip("- ").strip()
    if pr_num and f"#{pr_num}" not in clean:
        clean = f"{clean} (#{pr_num})"
    bullet = f"- {clean}"
    if bullet in body:
        return author_path(login), False
    if "## Review mannerisms" not in body:
        body = body.rstrip() + "\n\n## Review mannerisms\n\n" + bullet + "\n"
    else:
        body = body.rstrip() + "\n" + bullet + "\n"
    return write_author(login, fm, body), True


def extract_notes_for_context(login, display_name="", extra_files=()):
    """Return formatted author mannerisms for <DIR>/author-notes.md."""
    found = []
    _, fm, body = load_author(login)
    if body:
        for line in body.splitlines():
            s = line.strip()
            if s.startswith("- "):
                found.append(s)

    # Optional legacy/external team files configured in author_notes.extra_files
    lookup_name = display_name or fm.get("name") or ""
    if lookup_name and extra_files:
        pat = re.compile(rf"^-\s+\*?\*?{re.escape(lookup_name)}\*?\*?(\b|\s|$)", re.I)
        for tf in extra_files:
            tf_exp = common.expand_path(tf)
            if not tf_exp or not os.path.isfile(tf_exp):
                continue
            lines = open(tf_exp, encoding="utf-8", errors="replace").read().splitlines()
            for i, line in enumerate(lines):
                if pat.match(line.strip()) and not line.startswith((" ", "\t")):
                    j = i + 1
                    while j < len(lines) and (lines[j].startswith(("  ", "\t")) or lines[j].strip() == ""):
                        s = lines[j].strip()
                        if s and s not in found:
                            found.append(s)
                        j += 1

    if not found:
        return "none\n"
    header = f"# Author notes: {lookup_name or login} (`@{login}`)\n\n"
    return header + "\n".join(found) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Manage local PR author profiles.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")

    p_show = sub.add_parser("show")
    p_show.add_argument("login")

    p_touch = sub.add_parser("touch")
    p_touch.add_argument("login")
    p_touch.add_argument("--name", default="")
    p_touch.add_argument("--pr", type=int, default=None)
    p_touch.add_argument("--repo", default="")

    p_add = sub.add_parser("add-note")
    p_add.add_argument("login")
    p_add.add_argument("--note", required=True)
    p_add.add_argument("--pr", type=int, default=None)
    p_add.add_argument("--name", default="")

    args = ap.parse_args()
    if args.cmd == "list":
        d = authors_dir(create=False)
        files = sorted(glob.glob(os.path.join(d, "*.md"))) if os.path.isdir(d) else []
        if not files:
            print("No author profiles yet.")
            return 0
        for f in files:
            fm, body = common.parse_front_matter(f)
            notes = [l for l in body.splitlines() if l.strip().startswith("- ")]
            prs = fm.get("prs_reviewed") or []
            print(f"@{fm.get('login', os.path.basename(f)[:-3]):28} {fm.get('name', ''):18} prs={len(prs):2}  notes={len(notes):2}  last={fm.get('last_reviewed', '-')}")
        return 0

    if args.cmd == "show":
        p, _, _ = load_author(args.login)
        if not p:
            print(f"No profile for @{args.login}")
            return 1
        print(open(p, encoding="utf-8").read(), end="")
        return 0

    if args.cmd == "touch":
        p = touch_author(args.login, name=args.name, pr_num=args.pr, gh_repo=args.repo)
        print(f"updated {p}")
        return 0

    if args.cmd == "add-note":
        p, added = add_note(args.login, args.note, pr_num=args.pr, name=args.name)
        print(f"{'added note to' if added else 'already present in'} {p}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
