---
name: enrich-transcripts
description: Standardize raw call-transcript .md files produced by Local Transcriber — add an AI summary and frontmatter, tidy filenames, and (optionally) match each transcript to a calendar meeting. Use when the user runs /enrich-transcripts or asks to tidy/standardize their transcripts, add AI summaries, or add frontmatter. Requires ANTHROPIC_API_KEY for the summary step.
---

# Enrich call transcripts

Standardizes the transcript `.md` files that Local Transcriber writes. For each file this skill can:

1. **AI summary** — prepend an `## AI Summary` section (via the Anthropic API).
2. **Frontmatter** — add YAML frontmatter (tags, status, participants).
3. **Rename** — give the file a descriptive name.
4. **Calendar mapping (optional)** — match the transcript to a calendar event to fill in the meeting subject + invitees. This step only runs if a calendar source is available (see below); the core summary + frontmatter work without it.

**Core principle: confirm, don't assume.** Surface anything ambiguous and get the user's decision before renaming or writing. Never guess a mapping.

## Prerequisites

- `ANTHROPIC_API_KEY` set in the environment (for the summary step).
- `pip install anthropic`.
- Point the scripts at your transcript folder with `--dir "<path>"` (whatever you set as Local Transcriber's save location).

## Inputs

- `/enrich-transcripts` — process every `.md` in the folder that isn't already standardized.
- `/enrich-transcripts <YYYY-MM-DD..YYYY-MM-DD>` — restrict to transcripts whose timestamp falls in that window.
- `/enrich-transcripts --audio-only` — only rename/move `.m4a` files (see Step 5). Relevant only if the recorder keeps audio (`keepAudio = true`).

## Step 1 — Inventory

List `.md` files and read each header block (the `# Transcript — <date> at <time>` line, `Duration`, `Speakers`, first speaker lines). Record per file: start timestamp, whether it already has frontmatter, whether it already has `## AI Summary` (for idempotency), and a rough topic + participant names from the body.

## Step 2 — AI Summary

Insert an `## AI Summary` between the frontmatter and the `# Transcript` heading. Use the bundled batch driver (idempotent — skips files that already have a summary):

```bash
# validate the format on one file first (no writes)
python3 enrich-transcripts/scripts/summarize.py --dir "<transcript folder>" --dry --limit 1
# then run the batch
python3 enrich-transcripts/scripts/summarize.py --dir "<transcript folder>"
```

Set `--model claude-sonnet-5` (or `export ANTHROPIC_MODEL=...`) for a cheaper/faster model than the default.

**⚠️ Privacy gate:** summarizing sends the transcript body to the Anthropic API. For anything sensitive or personal, confirm with the user before summarizing.

## Step 3 — Frontmatter

Add frontmatter at the very top, above the `# Transcript` heading. A simple, editable starting schema:

```yaml
---
created: YYYY-MM-DD
tags:
  - "#transcript/<category>"
status: new
participants:
  - Full Name
---
```

- **Tag vocabulary is yours to define** — e.g. `#transcript/{work, personal, customer, internal}`. Keep it small and consistent.
- **Participants** — full names when you can confirm them from the transcript/context; otherwise leave them out. Drop conference-room resources; people only.
- **Personal calls:** `tags: ["#transcript/personal"]`, no participants.

## Step 4 — Rename (`.md` only)

Format: `YYYY-MM-DD - <short descriptor from the transcript>.md`, e.g. `2026-05-15 - vendor renewal walkthrough.md`. Replace filesystem-illegal `/` with a space. Renaming is not idempotent — present a proposed rename table and confirm before applying.

## Step 5 — Rename & relocate paired audio (`--audio-only`, optional)

Only relevant when the recorder keeps audio. Renames each `.m4a` to match its paired `.md` and moves it into the `audio files/` subfolder. Reads `.md` for pairing but never writes transcript content.

```bash
python3 enrich-transcripts/scripts/rename_audio.py --dir "<transcript folder>" --dry   # preview
python3 enrich-transcripts/scripts/rename_audio.py --dir "<transcript folder>"          # apply
```

Run this **after** Step 4, so the heading-time → filename map is current.

## Optional — Calendar mapping (advanced)

If you have a way to read your calendar from your agent (a calendar MCP server, an export, etc.), you can enrich further: match each transcript to the event whose start ≈ the transcript timestamp **and** whose subject/attendees are consistent with the content, then use the meeting subject in the filename and the attendee list for `participants`. **Stop and ask the user** about anything that isn't a clean match (no event at that time, multiple plausible events, a personal call, or a mismatch between speaker count and attendees). This step is not required — the skill works fully without it.

## Notes / gotchas

- Empty transcripts (tiny duration, no body) are usually mis-fire recordings — flag them, don't summarize.
- The AI-summary step is safe to re-run; the rename steps are not (confirm first).
- The heading may sit far down the file once a long `## AI Summary` is present — the scripts read the whole file; don't truncate.
