# Recheck mode (`review-pr recheck <n>`)

The author pushed fixes or replied after the user posted comments. No specialist agents run: the orchestrator verifies every posted comment, checks peer threads, inspects new commits for side effects, and observes any notable author review patterns.

## 1. Gather context

Run the deterministic gatherer from the repo checkout (resolves `old_head` from the PR note, latest `round-*.json`, or — in `docs.mode: "none"` — directly from the commit SHA of the reviewer's last GitHub review/comment; fetches `origin pull/<n>/head`; handles force-pushes/rebases; builds `recheck.diff` restricted to PR paths; detects reverted files; paginates all threads; loads `author-notes.md`, `related.md`, and `repo-profile.md`; and re-runs any configured extra linters):

```
python3 -I <SKILL_DIR>/scripts/gather.py <n> --dir <DIR> --mode recheck
```

Then:
- Read `<DIR>/meta.json`, `<DIR>/recheck-info.md`, `<DIR>/existing-comments.md`, `<DIR>/author-notes.md`, `<DIR>/related.md`, `<DIR>/repo-profile.md`, and `<DIR>/linters.txt`.
- Re-fetch the ticket (Step 1.3 in `SKILL.md`) when `main_ticket` is present and `issue_tracker != "none"`. If the ticket revision changed since the last round, inspect what changed, re-check every criterion previously `not met` or `partly`, and carry the ticket table forward in the round file.

## 2. Verify every one of the reviewer's posted threads

Always check **every** thread the reviewer posted (open **and** resolved) against the actual code at `<DIR>/head`, not only threads with new comments or authors flagged in `author-notes.md`. Being resolved proves nothing: a thread resolved silently with no matching code change is **not fixed**.

For each posted comment, assign one verdict: **fixed**, **half-fixed**, **not fixed**, or **pushback** (the author argued instead).
- Verify that the fix actually takes effect, not just that the line changed (e.g., CSS specificity/nested rules overriding the edited rule, or a guard added in desktop view but omitted in mobile view).
- For **half-fixed** or silently resolved threads: draft a reply in that thread asking if there's a reason, with the remaining fix as code, and note it should be unresolved.
- For **pushback**: weigh the author's argument against the code, design specs, `ticket.md`, and `related.md` (especially agreed decisions from earlier PRs) before accepting or answering.

## 3. Check peer threads, reverts, and fix-commit side effects

- **Other reviewers' open threads:** Inspect `Other reviewers' open threads` in `<DIR>/existing-comments.md` (and `meta.json["peer_open_threads"]`). Summarize any unresolved peer threads (especially blocking ones). Do not draft unrequested comments on them unless the user is already in the thread or asked, **and never return `verdict: "ready to approve"` silently while blocking peer threads remain open** — use `"our threads clear (peer threads open)"` instead.
- **Changed stateful flow:** Repeat the affected end-to-end trace in SKILL.md §2 using the current head and repo profile. Check the reported scenario and another affected path, such as a retry after partial success or a failure that leaves existing state in place. Check agreed ordering or ownership decisions against the actual call sequence. Record runtime or external behavior that still needs verification.
- **Reverts:** Check `reverted_files_dropped_from_pr_diff` in `<DIR>/recheck-info.md`. A file edited in one commit and reverted in a later commit drops out of `pr.diff` while still deciding runtime behavior.
- **New-code side effects & extra linters:** Skim added lines in `<DIR>/recheck.diff` for:
  - dead wiring (a new prop/flag added with no caller);
  - newly unreachable UI states or regressions introduced by the fix;
  - new lint/type suppressions;
  - any linter errors in `<DIR>/linters.txt` on newly edited files.
  If a new defect is clear, add it as a finding (`agents: "recheck"`); if it depends on runtime/visual checks you couldn't verify, place it in `unverified[]` (never inside `findings[]`).

## 4. Observe author mannerisms (interactive)

If `author_notes.mode != "off"` and this recheck surfaced a clear, factual pattern not already in `author-notes.md` (for example: resolved threads without a matching fix, pushed back with accurate measurements/evidence, or introduced a recurring pattern):
- In `propose` mode (interactive): include a short **Suggested author note** at the end of the review and ask whether to save it via:
  ```
  python3 -I <SKILL_DIR>/scripts/authors.py add-note <author_login> --pr <n> --name "<author_name>" --note "<observation>"
  ```
- In `auto` mode: save it directly and mention it in one line.
- In unattended mode with `propose`: never prompt or edit `authors/`; note it in `## Notes` if documenting.

## 5. Verdict, gate, round file, and documentation

Recheck `verdict` values:
- `"nothing new"` — only merges from base branch / no PR code change and no author replies since the last round.
- `"ready to approve"` — all of the reviewer's threads are fixed or settled, no new issues found, and no blocking peer threads remain open.
- `"our threads clear (peer threads open)"` — all of the reviewer's threads are fixed/settled, but other reviewers still have unresolved blocking threads.
- `"follow-ups drafted"` — one or more follow-up replies or new findings are drafted in `findings[]`.

Before finishing:
1. Build the round JSON (`meta.json["round_path"]`) with `python3 -I` and `json.dump`:
   - `kind: "recheck"`, real `session` id from the harness file (never a placeholder), `recheck: [...]` table, `verdict`, and `findings: [...]` (only `STANDS`/`DEFENSIBLE` drafted follow-ups; set `agents: "recheck"` or `"peer-reply"`, and keep all required schema fields including `code_context`: 1–2 neutral sentences on what the anchored snippet does and why it was implemented this way in the context of the ticket/PR). Put unverified items in `unverified[]`, never in `findings[]`.
2. Run the gate with schema validation and hunk fill:
   ```
   python3 -I <SKILL_DIR>/scripts/gate.py <round_path> --diff <DIR>/pr.diff --head <DIR>/head --validate-round --fill-hunks
   ```
   Fix any FAIL or schema error before finishing, and record the gate tally in `"gate"`.
3. Remove the worktree: `git -C <repo_dir> worktree remove <DIR>/head`.
4. Document per `meta.json["docs_mode"]` (`none`: skip note; `skill` / `folder`: append the round under `## What we suggested` and update `## Outcome`; never edit front matter if `docs.external_front_matter` is true).
5. Interactive only: if `hooks.post_review` is set in `config.json`, run it. Unattended: reply in one line.
