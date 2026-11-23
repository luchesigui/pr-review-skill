# Repo Review Profile Example

Save per-repo rules at `local/repos/<owner>__<repo>.md` (and optional structured overrides at `local/repos/<owner>__<repo>.json`). `gather.py` automatically loads the matching profile for every PR in that repository.

## Extra Reuse / General Rules

- Shared utility types live in `packages/shared-types/` (prefer existing helpers over hand-rolled types).
- Prefer localized message files over raw backend error strings in user-facing toasts.
- When changing a REST/GraphQL DTO field, check both backend producers and frontend consumers.

## Learned Checks

Use one entry per recurring mechanism. Include when to apply the check, what to verify, and a local source reference. As you learn more, update the matching entry.

- **Retry after partial success.** When a change touches a retried write, follow a caller retry after the write succeeds and the response is lost. Verify that the retry can recover the original result or avoid repeating the write. Source PR #123 (example).

## Not Worth Raising

- Legacy files intentionally forked/replaced as part of an active redesign.
- Generated files (`*.gen.ts`, lockfiles, snapshots unless semantically wrong).
- Formatting or lint rules already enforced in CI.
