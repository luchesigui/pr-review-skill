# Voice & Comment Style Guide

Copy this file to `local/voice.md` (or let `/review-pr setup` generate one from your recent GitHub PR comments) and customize it to match how you write code reviews.

## Principles

- **Short & direct:** 1–2 sentences (what happens, then the ask). Cut long consequence chains and unnecessary line-range tours.
- **Breathing room:** Separate short paragraphs with blank lines (observation / why it matters / ask), never one dense wall of text.
- **Lead with what exists:** Name the existing helper, component, or constant first, plus a one-clause reason ("avoids duplicating formatting logic").
- **Missing or inert behavior:** State what is missing and end with `"..., or is that coming in a follow-up ticket?"`.
- **Concrete suggestions:** Use ```` ```suggestion ```` blocks for few-line edits so the author can apply in one click. For larger reshapes, provide a concise code sketch and frame open ideas as `"wdyt if, instead of ..., we ...?"`.
- **Uncertainty:** Ask as a confirmation question when something wasn't verified at runtime or looks intentionally removed. Ask what unused-looking code does rather than assuming it's dead.
- **Tone:** Argue from impact/correctness (never `"I prefer"`), label minor taste honestly (`"nit:"`), skip praise padding, keep one topic per comment, and anchor on a diff line.

## Before / After Examples

### Trimming a verbose draft
- **Too long:** "Because `formatDate` is reimplemented here instead of importing the shared formatter from `src/utils/date.ts` (see how `InvoiceList.tsx` L40–L52 uses it), timezone handling could diverge over time if we update the locale rules later. Could we switch to the shared helper?"
- **Better:** "`src/utils/date.ts` already has `formatDate` with the shared timezone rules. Could we reuse it here (or extend it with an option if we need a new format)?"

### Asking about unused-looking code
- **Better:** "What is `data-compact` doing here? I don't see it referenced in the styles or JS."

### Author's fix works but has trade-offs
- Acknowledge that it works, list the concrete drawbacks briefly, then provide the complete suggested alternative rather than a vague one-liner.

### Next-story or missed criterion
- **Better:** "The ticket asks for a test covering the retry path; I only see the happy path covered here. Is that coming in this PR?"
