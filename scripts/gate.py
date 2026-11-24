#!/usr/bin/env python3
"""Deterministic gate on review findings and round files. No model: every check can fail on its own.

    python3 -I gate.py <findings.json> --diff <DIR>/pr.diff --head <DIR>/head [--out <DIR>/gate.json]
    python3 -I gate.py <round-k.json> --diff <DIR>/pr.diff --head <DIR>/head --validate-round [--fill-hunks]

<findings.json> is a list of findings or a round file ({"findings": [...]}). Each finding uses:
file, line, start_line (optional), category, evidence, existing (optional), comment (optional).

Checks:
  anchor      file is in the diff and line (and start_line <= line) sit on the new side of one hunk
  quotes      code quoted in backticks in evidence exists at the PR head or in the diff
  refs        every path:line cited in evidence/existing/comment exists at the head; a symbol named
              after an `existing:` ref appears within 15 lines of it
  suggestion  a ```suggestion block is not a no-op and doesn't repeat substantial lines around its range
  schema      (--validate-round) round file and finding keys match the round JSON contract
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

MIN_QUOTE = 12
REF = re.compile(r"((?:[\w.@\[\]-]+/)*\.?[\w@\[\]-][\w.@\[\]-]*\.[A-Za-z]\w*):L?(\d+)(?:-L?(\d+))?")
SPAN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
SUGG = re.compile(r"```suggestion[^\n]*\n(.*?)```", re.S)
IDENT = re.compile(r"^[A-Za-z_$][\w$]*$")

VALID_CATEGORIES = {"design", "reuse", "shape", "schema", "correctness", "claim", "roadmap", "tests", "conventions", "tripwire"}
VALID_SEVERITIES = {"major", "minor", "nit"}
VALID_VERDICTS = {"STANDS", "DEFENSIBLE"}
BASE_VALID_AGENTS = {"design", "reuse", "general", "claim", "orchestrator", "recheck", "peer-reply", "reviewer", "user"}
ROGUE_FINDING_KEYS = {"devil", "devils_advocate", "reply_to", "summary"}
REQUIRED_FINDING_KEYS = ("id", "file", "line", "severity", "category", "claim", "evidence", "verdict", "da_reason", "overlap", "post", "agents", "comment")


def valid_agents():
    agents = set(BASE_VALID_AGENTS)
    try:
        cfg = common.load_config()
        user = cfg.get("user") or {}
        for k in ("name", "github_login"):
            v = (user.get(k) or "").strip().lower().split()[0] if user.get(k) else ""
            if v:
                agents.add(v)
    except Exception:
        pass
    return agents


def parse_diff(text):
    """Return ({path: [set(new-side line numbers)]}, set(deleted_paths), {path: [(header, [(new_line, raw_line)])]})."""
    files, deleted, hunks_text = {}, set(), {}
    cur, prev_from, hunk, h_lines, n = None, None, None, None, 0
    for line in text.splitlines():
        if line.startswith("--- "):
            prev_from = re.sub(r"^a/", "", line[4:].strip())
            hunk = None
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path == "/dev/null":
                cur = None
                if prev_from and prev_from != "/dev/null":
                    deleted.add(prev_from)
            else:
                cur = re.sub(r"^b/", "", path)
                files.setdefault(cur, [])
                hunks_text.setdefault(cur, [])
            hunk = None
            continue
        if line.startswith("diff --git"):
            prev_from, cur, hunk = None, None, None
            continue
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
        if m and cur:
            n = int(m.group(1))
            hunk = set()
            h_lines = []
            files[cur].append(hunk)
            hunks_text[cur].append((line, h_lines))
            continue
        if hunk is None:
            continue
        if line.startswith("+") or line.startswith(" "):
            hunk.add(n)
            h_lines.append((n, line))
            n += 1
        elif line.startswith("-"):
            h_lines.append((None, line))
        elif line.startswith("\\"):
            continue
    return {p: [h for h in hs if h] for p, hs in files.items()}, deleted, hunks_text


def extract_hunk(hunks_text, path, line, start_line=None):
    """Extract a 3-8 line diff snippet around start_line..line from parsed diff hunks."""
    if not path or not line or path not in hunks_text:
        return None
    end = int(line)
    start = int(start_line or end)
    for header, rows in hunks_text[path]:
        idxs = [i for i, (ln, _) in enumerate(rows) if ln is not None and start <= ln <= end]
        if not idxs:
            continue
        lo = max(0, idxs[0] - 2)
        hi = min(len(rows), idxs[-1] + 3)
        snippet = [header] + [raw for _, raw in rows[lo:hi]]
        return "\n".join(snippet)
    return None


def squash(s):
    return re.sub(r"\s+", "", s)


def diff_sides(text):
    """The diff's code without +/-/space prefixes, old and new side joined, whitespace removed."""
    keep = [l[1:] for l in text.splitlines()
            if l[:1] in "+- " and not l.startswith(("+++ ", "--- "))]
    return squash("\n".join(keep))


class Head:
    def __init__(self, root, diff_text):
        self.root = root
        self.diff_code = diff_sides(diff_text)
        r = subprocess.run(["git", "-C", root, "ls-files"], capture_output=True, text=True)
        self.files = r.stdout.split("\n") if r.returncode == 0 else []
        self._lines = {}

    def resolve(self, path):
        while path.startswith("./"):
            path = path[2:]
        if os.path.isfile(os.path.join(self.root, path)):
            return path
        hits = [f for f in self.files if f.endswith("/" + path)]
        return hits[0] if len(hits) == 1 else None

    def lines(self, path):
        if path not in self._lines:
            try:
                self._lines[path] = open(os.path.join(self.root, path), encoding="utf-8", errors="replace").read().split("\n")
            except OSError:
                self._lines[path] = None
        return self._lines[path]

    def in_file(self, q, path):
        ls = self.lines(path) if path else None
        return ls is not None and q in squash("\n".join(ls))

    def contains(self, quote, prefer=(), scope_file=None):
        """Whitespace-insensitive, so code an agent joined from several lines still matches."""
        q = squash(quote)
        if q in self.diff_code or any(self.in_file(q, p) for p in prefer):
            return True
        chunk = max(re.split(r"\s+", quote.strip()), key=len)
        r = subprocess.run(["git", "-C", self.root, "grep", "-F", "-l", "-e", chunk], capture_output=True, text=True)
        hits = [p for p in r.stdout.split("\n") if p]
        if scope_file and len(hits) > 200:
            prefix = "/".join(scope_file.split("/")[:2]) + "/"
            hits.sort(key=lambda p: (0 if p.startswith(prefix) else 1))
        return any(self.in_file(q, p) for p in hits[:200])


def nearest(hunks, line):
    best = None
    for h in hunks:
        for x in h:
            if best is None or abs(x - line) < abs(best - line):
                best = x
    return best


def check_anchor(f, diff, deleted):
    path, line, start = f.get("file"), f.get("line"), f.get("start_line")
    if not path:
        return True, "no file: general comment"
    if path in deleted and path not in diff:
        return False, f"{path} is deleted in the diff (no new-side lines; anchor on a caller or general comment)"
    if path not in diff:
        return False, f"{path} is not in the diff"
    if not line:
        return True, "file-level comment"
    end = int(line)
    if start and int(start) > end:
        return False, f"start_line L{start} is greater than line L{end}"
    hunks = diff[path]
    hit = next((h for h in hunks if end in h), None)
    if not hit:
        return False, f"L{end} is not on a diff line; nearest commentable line is L{nearest(hunks, end)}"
    if start and int(start) not in hit:
        return False, f"start_line L{start} is not in the same hunk as L{end}"
    return True, f"L{start}-L{end}" if start else f"L{end}"


def cited_files(f, head):
    out = [f.get("file")]
    for field in ("evidence", "existing", "comment"):
        out += [head.resolve(m.group(1)) for m in REF.finditer(f.get(field) or "")]
    return [p for p in out if p]


def check_quotes(f, head):
    if f.get("category") == "design":
        return True, "skipped: design evidence quotes design spec"
    ev = f.get("evidence") or ""
    prefer = cited_files(f, head)
    missing, checked = [], 0
    for q in SPAN.findall(ev):
        q = q.strip()
        if len(q) < MIN_QUOTE or REF.search(q):
            continue
        checked += 1
        if not head.contains(q, prefer, scope_file=f.get("file")):
            missing.append(q)
    if missing:
        return False, "not at head or in the diff: " + "; ".join(f"`{m[:80]}`" for m in missing)
    return True, f"{checked} quote{'s' * (checked != 1)} found"


def check_refs(f, head):
    bad, checked = [], 0
    for field in ("evidence", "existing", "comment"):
        text = f.get(field) or ""
        for m in REF.finditer(text):
            checked += 1
            path, a = m.group(1), int(m.group(2))
            real = head.resolve(path)
            if not real:
                bad.append(f"{path} not found ({field})")
                continue
            ls = head.lines(real) or []
            if a > len(ls):
                bad.append(f"{path}:{a} past the end ({len(ls)} lines, {field})")
                continue
            if field == "existing":
                rest = text[m.end():].strip().strip("`").split()
                sym = rest[0].strip("`(),.:") if rest else ""
                if IDENT.match(sym) and len(sym) > 2:
                    window = "\n".join(ls[max(0, a - 16):a + 15])
                    if sym not in window:
                        bad.append(f"`{sym}` not within 15 lines of {path}:{a}")
    if bad:
        return False, "; ".join(bad)
    return True, f"{checked} ref{'s' * (checked != 1)} found"


def check_suggestion(f, head):
    blocks = SUGG.findall(f.get("comment") or "")
    if not blocks:
        return True, "no suggestion block"
    path, line = f.get("file"), f.get("line")
    real = head.resolve(path) if path else None
    ls = head.lines(real) if real else None
    if not ls or not line:
        return False, "suggestion block without a readable anchor file and line"
    end = int(line)
    start = int(f.get("start_line") or end)
    if start > end:
        return False, f"start_line L{start} > line L{end}"
    current = ls[start - 1:end]
    warns = []
    for b in blocks:
        new = b.rstrip("\n").split("\n") if b.strip() else []
        if [x.rstrip() for x in new] == [x.rstrip() for x in current]:
            return False, "no-op: the suggestion equals the anchored lines"
        if new:
            after = [x.strip() for x in ls[end:end + 5] if len(x.strip()) > 8]
            before = [x.strip() for x in ls[max(0, start - 6):start - 1] if len(x.strip()) > 8]
            tail = new[-1].strip()
            head_ = new[0].strip()
            if tail in after:
                msg = f"repeats a line below L{end} (`{tail[:60]}`): widen line or trim the block"
                if len(tail) > 24 or (len(new) > 1 and new[-2].strip() in after):
                    return False, msg
                warns.append(msg)
            if head_ in before:
                msg = f"repeats a line above L{start} (`{head_[:60]}`): widen start_line or trim the block"
                if len(head_) > 24 or (len(new) > 1 and new[1].strip() in before):
                    return False, msg
                warns.append(msg)
    detail = f"replaces L{start}-L{end}" if start != end else f"replaces L{end}"
    if warns:
        detail += " [WARN: " + "; ".join(warns) + "]"
    return True, detail


def check_round_schema(data):
    """Validate top-level round file schema and every finding's required fields."""
    errors = []
    allowed_agents = valid_agents()
    if not isinstance(data, dict):
        return ["round file must be a JSON object"]
    for k in ("pr", "round", "kind", "date", "head", "session", "short", "summary", "agents", "not_verified", "findings"):
        if k not in data:
            errors.append(f"top-level missing `{k}`")
    if data.get("kind") not in ("review", "recheck"):
        errors.append(f"invalid kind: {data.get('kind')!r} (expected 'review' or 'recheck')")
    sess = str(data.get("session") or "")
    if not sess or sess.startswith(("unattended-", "<", "TODO", "none")):
        errors.append(f"invalid/placeholder session id: {sess!r}")
    if data.get("kind") == "recheck" and not data.get("verdict"):
        errors.append("recheck round missing `verdict`")
    for i, f in enumerate(data.get("findings") or []):
        fid = f.get("id") or f"#{i}"
        missing = [k for k in REQUIRED_FINDING_KEYS if not f.get(k) and f.get(k) != 0]
        if missing:
            errors.append(f"{fid}: missing required keys {missing}")
        rogue = sorted(ROGUE_FINDING_KEYS & set(f.keys()))
        if rogue:
            errors.append(f"{fid}: non-schema keys {rogue} (use claim/da_reason/overlap/post)")
        if f.get("severity") and f.get("severity") not in VALID_SEVERITIES:
            errors.append(f"{fid}: invalid severity {f.get('severity')!r}")
        if f.get("category") and f.get("category") not in VALID_CATEGORIES:
            errors.append(f"{fid}: invalid category {f.get('category')!r}")
        if f.get("verdict") and f.get("verdict") not in VALID_VERDICTS:
            errors.append(f"{fid}: verdict {f.get('verdict')!r} not allowed in findings[] (move UNVERIFIED/DROPPED out)")
        raw_agents = str(f.get("agents") or "").strip()
        if not raw_agents:
            errors.append(f"{fid}: empty `agents` (will show as 'unknown' in outcomes)")
        else:
            toks = [a.strip().split()[0].lower() for a in raw_agents.split(",") if a.strip()]
            bad_ag = [t for t in toks if t not in allowed_agents]
            if bad_ag:
                errors.append(f"{fid}: unrecognized agent names {bad_ag} (allowed: {sorted(allowed_agents)})")
        if f.get("file") and f.get("line") and not f.get("hunk"):
            errors.append(f"{fid}: missing `hunk` (run with --fill-hunks)")
        if f.get("file"):
            cc = f.get("code_context")
            if not isinstance(cc, str) or not cc.strip():
                errors.append(f"{fid}: missing `code_context` (1-2 sentences on what the snippet does and why it was written this way for the ticket)")
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("findings")
    ap.add_argument("--diff", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--out")
    ap.add_argument("--validate-round", action="store_true", help="also validate round-file JSON schema")
    ap.add_argument("--fill-hunks", action="store_true", help="auto-populate missing hunk fields in-place from --diff")
    a = ap.parse_args()
    data = json.load(open(a.findings, encoding="utf-8"))
    findings = data["findings"] if isinstance(data, dict) else data
    diff_text = open(a.diff, encoding="utf-8", errors="replace").read()
    diff, deleted, hunks_text = parse_diff(diff_text)
    head = Head(a.head, diff_text)

    filled = 0
    if a.fill_hunks:
        for f in findings:
            if not f.get("hunk") and f.get("file") and f.get("line"):
                h = extract_hunk(hunks_text, f["file"], f["line"], f.get("start_line"))
                if h:
                    f["hunk"] = h
                    filled += 1
        if filled:
            with open(a.findings, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            print(f"filled {filled} hunk{'s' * (filled != 1)} in {a.findings}")

    out, n_fail = [], 0
    for i, f in enumerate(findings):
        checks = {}
        for name, fn in (
            ("anchor", lambda: check_anchor(f, diff, deleted)),
            ("quotes", lambda: check_quotes(f, head)),
            ("refs", lambda: check_refs(f, head)),
            ("suggestion", lambda: check_suggestion(f, head)),
        ):
            ok, detail = fn()
            checks[name] = {"ok": ok, "detail": detail}
        failed = [k for k, v in checks.items() if not v["ok"]]
        n_fail += bool(failed)
        fid = f.get("id") or f"#{i}"
        out.append({"id": fid, "file": f.get("file"), "line": f.get("line"), "pass": not failed, "failed": failed, "checks": checks})
        where = f"{f.get('file') or 'general'}:{f.get('line') or ''}"
        print(f"{'PASS' if not failed else 'FAIL'} {fid} {where}" +
              "".join(f"\n    {k}: {checks[k]['detail']}" for k in failed))

    schema_errors = check_round_schema(data) if a.validate_round else []
    if schema_errors:
        print("SCHEMA FAIL:")
        for e in schema_errors:
            print(f"    schema: {e}")

    print(f"gate: {len(findings)} checked, {len(findings) - n_fail} pass, {n_fail} fail"
          + (f", {len(schema_errors)} schema errors" if a.validate_round else ""))
    if a.out:
        json.dump(
            {"checked": len(findings), "failed": n_fail, "schema_errors": schema_errors, "results": out},
            open(a.out, "w", encoding="utf-8"),
            indent=1,
        )
    return 1 if (n_fail or schema_errors) else 0


if __name__ == "__main__":
    sys.exit(main())
