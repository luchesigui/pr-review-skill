#!/usr/bin/env python3
"""Stage a validated round's findings on GitHub as a PENDING (unsubmitted) review, or post them. Opt-in only.

    python3 -I stage.py <pr> [--gh-repo owner/repo] [--round <round-k.json>] [--only f1,f2] [--skip f3]
                             [--no-body] [--dry-run] [--allow-moved-head] [--post]

Default (stage): a pending review only the user sees until they submit it in GitHub.
--post: the same review is submitted right away as a COMMENT review, visible to everyone.

Refuses unless every check passes:
  schema    the round passes gate.py's round schema check and is not blocked
  findings  only findings[] are staged; each needs a file and line, and replies in existing threads are refused
  head      the PR is open and its head still matches the round's `head` (or --allow-moved-head)
  diff      every line / start_line sits on the RIGHT side of one hunk of the current PR diff
  pending   the authenticated user has no PENDING review on the PR already (GitHub allows one)

Staging omits `event`, so GitHub keeps the review pending and visible only to you until you submit it.
--post sends `event: COMMENT`, so GitHub publishes it immediately (never APPROVE or REQUEST_CHANGES).
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import gate


def latest_round(data_dir, pr):
    best, best_k = None, -1
    for p in glob.glob(os.path.join(data_dir, str(pr), "round-*.json")):
        m = re.search(r"round-(\d+)\.json$", p)
        if m and int(m.group(1)) > best_k:
            best, best_k = p, int(m.group(1))
    return best


def split_ids(s):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def select_findings(findings, only, skip):
    ids = {f.get("id") for f in findings}
    unknown = [x for x in only + skip if x not in ids]
    if unknown:
        return None, [f"unknown finding ids: {unknown} (round has {sorted(i for i in ids if i)})"]
    picked = [f for f in findings if (not only or f.get("id") in only) and f.get("id") not in skip]
    return picked, []


def stageable_errors(findings):
    errors = []
    for i, f in enumerate(findings):
        fid = f.get("id") or f"#{i}"
        if not f.get("file") or not f.get("line"):
            errors.append(f"{fid}: no file and line, so it can't be an inline comment (post it by hand or --skip {fid})")
        if str(f.get("post") or "").lower().startswith("reply"):
            errors.append(f"{fid}: drafted as a reply in an existing thread ({f.get('post')}); reply there by hand or --skip {fid}")
    return errors


def right_side_errors(findings, diff_text):
    """Every anchor must be a new-side (RIGHT) line of a single hunk in the current PR diff."""
    diff, deleted, _ = gate.parse_diff(diff_text)
    errors = []
    for i, f in enumerate(findings):
        ok, detail = gate.check_anchor(f, diff, deleted)
        if not ok:
            errors.append(f"{f.get('id') or f'#{i}'} {f.get('file')}:{f.get('line')}: {detail}")
    return errors


def moved_hunk_warnings(findings, diff_text):
    _, _, hunks_text = gate.parse_diff(diff_text)
    warns = []
    for f in findings:
        now = gate.extract_hunk(hunks_text, f.get("file"), f.get("line"), f.get("start_line"))
        if f.get("hunk") and now != f["hunk"]:
            warns.append(f"{f.get('id')} {f.get('file')}:{f.get('line')}: hunk differs from the round; check the anchor in GitHub")
    return warns


def build_payload(findings, commit_id, body=None, post=False):
    comments = []
    for f in findings:
        c = {"path": f["file"], "line": int(f["line"]), "side": "RIGHT", "body": f["comment"]}
        if f.get("start_line") and int(f["start_line"]) != int(f["line"]):
            c["start_line"] = int(f["start_line"])
            c["start_side"] = "RIGHT"
        comments.append(c)
    payload = {"commit_id": commit_id, "comments": comments}
    if body and body.strip():
        payload["body"] = body
    if post:
        payload["event"] = "COMMENT"
    return payload


def gh(args, input_text=None):
    return common.run(["gh"] + args, input_text=input_text, timeout=120)


def pending_reviews(gh_repo, pr, login):
    r = gh(["api", "--paginate", f"repos/{gh_repo}/pulls/{pr}/reviews",
            "--jq", '.[] | select(.state == "PENDING") | [.user.login, .html_url] | @tsv'])
    out = []
    for line in r.stdout.splitlines():
        who, _, url = line.partition("\t")
        if who.lower() == login.lower():
            out.append(url)
    return out


def record_staging(round_path, data, review, key="staged"):
    data[key] = {
        "review_id": review.get("id"),
        "url": review.get("html_url"),
        "commit_id": review.get("commit_id"),
        "date": datetime.datetime.now().astimezone().isoformat(timespec="minutes"),
    }
    tmp = round_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, round_path)


def fail(errors, header):
    print(f"REFUSED: {header}")
    for e in errors:
        print(f"    {e}")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Stage round findings as a pending GitHub review, or post them with --post.")
    ap.add_argument("pr", type=int)
    ap.add_argument("--gh-repo", help="owner/repo (default: config default_repo, then the current checkout)")
    ap.add_argument("--round", help="round JSON path (default: latest round-<k>.json for the PR)")
    ap.add_argument("--only", help="comma-separated finding ids to stage")
    ap.add_argument("--skip", help="comma-separated finding ids to leave out")
    ap.add_argument("--no-body", action="store_true", help="don't use review_summary as the review body")
    ap.add_argument("--dry-run", action="store_true", help="run every check and print the payload; no POST")
    ap.add_argument("--allow-moved-head", action="store_true", help="stage on the current head even if it moved since the round")
    ap.add_argument("--post", action="store_true", help="submit the review as a COMMENT right away instead of leaving it pending")
    a = ap.parse_args()

    cfg = common.load_config()
    gh_repo = a.gh_repo or cfg.get("default_repo") or common.detect_gh_repo(cfg=cfg)
    if not gh_repo:
        fail(["pass --gh-repo owner/repo"], "no GitHub repo")
    cfg = common.effective_config(gh_repo)

    round_path = a.round
    if not round_path:
        _, _, data_dir = common.docs_paths(cfg, gh_repo)
        round_path = latest_round(data_dir, a.pr) if data_dir else None
        if not round_path:
            fail([f"looked in {data_dir or '(docs.mode none)'}; pass --round <path>"], f"no round file for PR {a.pr}")
    data = json.load(open(round_path, encoding="utf-8"))
    print(f"round: {round_path}")

    if data.get("blocked"):
        fail([str(data["blocked"])], "round is blocked")
    if str(data.get("pr")) != str(a.pr):
        fail([f"round pr is {data.get('pr')!r}"], f"round doesn't belong to PR {a.pr}")
    errors = gate.check_round_schema(data)
    if errors:
        fail(errors, "round schema check failed (fix it and re-run gate.py --validate-round)")
    if data.get("posted"):
        fail([f"posted before: {data['posted'].get('url')}"], "this round was already posted")
    if data.get("staged"):
        print(f"note: this round was already staged before: {data['staged'].get('url')}")

    findings, errors = select_findings(data.get("findings") or [], split_ids(a.only), split_ids(a.skip))
    if errors:
        fail(errors, "bad --only/--skip")
    if not findings:
        fail(["nothing left to stage"], "no findings selected")
    errors = stageable_errors(findings)
    if errors:
        fail(errors, "findings that can't be staged as new inline comments")

    pr = json.loads(gh(["pr", "view", str(a.pr), "-R", gh_repo, "--json", "headRefOid,state,url"]).stdout)
    if pr.get("state") != "OPEN":
        fail([f"{pr.get('url')} is {pr.get('state')}"], "PR is not open")
    commit_id = data.get("head")
    if pr["headRefOid"] != commit_id:
        why = f"round head {str(commit_id)[:10]} != PR head {pr['headRefOid'][:10]}: the author pushed since the review"
        if not a.allow_moved_head:
            fail([why, "run /review-pr recheck first, or pass --allow-moved-head"], "PR head moved")
        print(f"WARN: {why}; staging on the current head")
        commit_id = pr["headRefOid"]

    diff_text = gh(["pr", "diff", str(a.pr), "-R", gh_repo]).stdout
    errors = right_side_errors(findings, diff_text)
    if errors:
        fail(errors, "anchors outside the current PR diff (GitHub would reject them)")
    if commit_id != data.get("head"):
        for w in moved_hunk_warnings(findings, diff_text):
            print(f"WARN: {w}")

    login = common.run(["gh", "api", "user", "-q", ".login"]).stdout.strip()
    existing = pending_reviews(gh_repo, a.pr, login)
    if existing:
        fail([f"{login} already has a pending review: {u}" for u in existing]
             + ["submit or delete it in GitHub first (GitHub allows one pending review per user)"], "pending review exists")

    body = None if a.no_body or data.get("is_self_pr") else data.get("review_summary")
    payload = build_payload(findings, commit_id, body, post=a.post)

    print(f"{'POST' if a.post else 'stage'} {gh_repo}#{a.pr} as {login}, commit {commit_id[:10]}, {len(payload['comments'])} comment(s), "
          f"body: {'yes' if 'body' in payload else 'no'}")
    for f, c in zip(findings, payload["comments"]):
        span = f"{c['start_line']}-{c['line']}" if "start_line" in c else str(c["line"])
        first = (c["body"].strip().splitlines() or [""])[0]
        print(f"  {f.get('id')}  {c['path']}:{span}  {first[:100]}")

    if a.dry_run:
        print("dry run: nothing posted")
        return

    r = gh(["api", "--method", "POST", f"repos/{gh_repo}/pulls/{a.pr}/reviews", "--input", "-"],
           input_text=json.dumps(payload))
    review = json.loads(r.stdout)
    expected = "COMMENTED" if a.post else "PENDING"
    if review.get("state") != expected:
        print(f"WARN: GitHub returned state {review.get('state')!r}, expected {expected}")
    try:
        record_staging(round_path, data, review, key="posted" if a.post else "staged")
    except OSError as e:
        print(f"WARN: couldn't record the review in the round file: {e}")
    if a.post:
        print(f"posted: {review.get('html_url')}")
        print("This review is PUBLISHED: the author and everyone on the PR can see it.")
        return
    print(f"staged: {review.get('html_url')}")
    print("This review is PENDING: only you can see it. Edit, add images, and submit it from GitHub's Files changed tab.")


if __name__ == "__main__":
    main()
