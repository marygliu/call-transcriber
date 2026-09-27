---
name: enrich-transcripts
description: Standardize raw call-transcript files (`.md` from Local Transcriber, or `.vtt` Teams caption exports) — convert captions to markdown, add an AI summary and frontmatter, tidy filenames, purge spent audio, and (optionally) match each transcript to a calendar meeting. Use when the user runs /enrich-transcripts or asks to tidy/standardize their transcripts, add AI summaries, or add frontmatter. Requires ANTHROPIC_API_KEY for the summary step.
---

# Enrich call transcripts

Standardizes the transcript files your recorder writes. For each file this skill can:

1. **Convert `.vtt` captions** — turn a Teams/WebVTT caption export into a standardized `.md` body (Step 1.5).
2. **AI summary** — prepend an `## AI Summary` section (via the Anthropic API).
3. **Frontmatter** — add YAML frontmatter (tags, status, participants).
4. **Rename** — give the file a descriptive name.
5. **Purge paired audio** — delete the `.m4a` once its transcript is safely standardized (privacy-first; optional).
6. **Calendar mapping (optional)** — match the transcript to a calendar event to fill in the meeting subject + attendees. This step only runs if a calendar source is available (see below); everything else works without it.

Two capture formats can land in the folder:

- **`.md`** — from Local Transcriber (Granola-style). Carries its own `# Transcript — <date> at <time>` heading and (if audio is kept) pairs with a `YYYY-MM-DD-HHMM.m4a`.
- **`.vtt`** — a Teams meeting caption export. The filename is the meeting subject (Teams swaps `/`→`_`); inside it holds **only relative cue offsets** — no wall-clock, no date. Convert it to a standardized `.md` first (Step 1.5), supplying the meeting's start time, before it can be renamed/summarized like any other transcript.

**Core principle: confirm, don't assume.** Surface anything ambiguous — a no-match, multiple candidates, a personal call — and get the user's decision before renaming or writing. Never guess a mapping.

## Prerequisites

- `ANTHROPIC_API_KEY` set in the environment (for the summary step).
- `pip install anthropic`.
- Point the scripts at your transcript folder with `--dir "<path>"` (whatever you set as Local Transcriber's save location). The examples below use `./transcripts`.

## Inputs

- `/enrich-transcripts` — process every `.md` **and `.vtt`** in the folder that isn't already standardized (`.vtt` → convert first, per Step 1.5).
- `/enrich-transcripts <YYYY-MM-DD..YYYY-MM-DD>` — restrict to transcripts whose timestamp falls in that window.
- `/enrich-transcripts --audio-only` — do nothing but delete each `.m4a` whose paired `.md` is already standardized (no summaries, no renames). See Step 5.

## Step 0 — Preflight (once per invocation)

1. **API key.** Confirm `ANTHROPIC_API_KEY` is set and `anthropic` is installed. The summary step aborts early without the key.
2. **Calendar source (optional).** If you plan to do calendar mapping, confirm your calendar tool is available (a calendar MCP server, an export, etc.). Skip if you're not mapping.

## Step 1 — Inventory

List `.md` **and `.vtt`** files. For each `.md`, read the header block (the `# Transcript — <date> at <time>` line, `Duration`, `Speakers`, first speaker lines). Record per file:

- start timestamp (from the heading / filename; **a `.vtt` has none** — it's resolved in Step 1.5),
- whether it already has YAML frontmatter,
- whether it already has `## AI Summary` (for idempotency),
- a rough topic + participant names from the body (for a `.vtt`, read the first cues + the `<v Speaker>` names).

Leave `.m4a` audio alone until Step 5.

## Step 1.5 — Convert `.vtt` captures (Teams exports)

A `.vtt` can't be placed by timestamp (it has none), so resolve its start time first, then convert. Get the start time either from the matched calendar event (see **Calendar mapping** below) or from the user.

```bash
# preview the converted markdown (writes nothing)
python3 enrich-transcripts/scripts/vtt_to_md.py "<file>.vtt" --start "YYYY-MM-DD HH:MM" --dry
# then write <file>.md alongside the .vtt
python3 enrich-transcripts/scripts/vtt_to_md.py "<file>.vtt" --start "YYYY-MM-DD HH:MM"
```

The script sorts cues, merges consecutive same-speaker runs into utterances, maps anonymous `@N` speakers to `Unknown` (override with `--map "@1=Full Name"` only when identity is certain), stamps wall-clock times, and writes the `# Transcript — …` body the rest of the pipeline expects. It refuses to clobber an existing `.md` (use `--force`).

Then treat the produced `.md` as a normal transcript for the steps below. Idempotent: once the `.md` exists, a re-run won't reconvert (the script won't overwrite it). If you standardized the `.md`, the source `.vtt` is a raw capture you no longer need — delete or archive it as you prefer.

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
- **Participants** — full names when you can confirm them from the transcript/context (or from the calendar attendee list, if you mapped). Drop conference-room resources; people only.
- **Personal calls:** `tags: ["#transcript/personal"]`, no participants.

## Step 4 — Rename (`.md` only)

Format: `YYYY-MM-DD - <short descriptor from the transcript>.md`, e.g. `2026-05-15 - vendor renewal walkthrough.md`. If you mapped to a calendar event, lead the descriptor with the meeting subject. Replace filesystem-illegal `/` with a space. Renaming is not idempotent — present a proposed rename table and confirm before applying.

## Step 5 — Purge paired audio (`--audio-only`, optional)

If your recorder keeps audio (`keepAudio = true`), you can delete each `.m4a` once its transcript is safely captured. This step touches **only `.m4a` files** — it reads `.md` for pairing but never writes transcript content.

**Safety rule:** a recording is deleted **only** when a paired transcript exists **and** is standardized (contains an `## AI Summary`). Mis-fire and needs-review recordings keep their audio until they're resolved.

```bash
python3 enrich-transcripts/scripts/purge_audio.py --dir "<transcript folder>" --dry   # preview
python3 enrich-transcripts/scripts/purge_audio.py --dir "<transcript folder>"          # apply
```

Pairing key: the timestamp in a raw audio filename (`YYYY-MM-DD-HHMM.m4a`) is matched against the `# Transcript — <Month D, YYYY> at <h:mm AM/PM>` heading inside each `.md`. Run this **after** the summary + rename steps so the heading-time map is current and the AI-Summary gate can see the summary. Idempotent; warns + keeps audio on any no-match / ambiguous / not-yet-standardized case.

> Prefer to *keep* audio instead of deleting it? Leave `keepAudio = true` and skip this step — the `.md` transcripts stand alone.

## Optional — Calendar mapping (advanced)

If you can read your calendar from your agent (a calendar MCP server, an export, etc.), you can enrich further: for each transcript, find the event whose start ≈ the transcript timestamp (within a few minutes) **and** whose subject/attendees are consistent with the content, then use the meeting subject in the filename and the attendee list for `participants`. For a `.vtt`, the matched event's start time is also what you pass to `vtt_to_md.py --start` (convert the event's start to your local time first).

**Stop and ask the user** about anything that isn't a clean match:

- no event at that time (likely an impromptu meeting — ask what it was),
- multiple plausible events,
- a personal / non-work call,
- a mismatch between speaker count and the attendee list.

Present a proposed mapping table (file → meeting) and the flagged items; wait for confirmation before renaming. This step is not required — the skill works fully without it.

## Notes / gotchas

- Empty transcripts (tiny duration, no body) are usually mis-fire recordings — flag them, don't summarize.
- The AI-summary step is safe to re-run; the rename step is not (confirm first).
- The heading may sit far down the file once a long `## AI Summary` is present — the scripts read the whole file; don't truncate.
- `.vtt` conversion is idempotent (won't clobber an existing `.md`); audio purge is idempotent and gated on the transcript being standardized.
