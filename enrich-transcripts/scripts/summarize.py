#!/usr/bin/env python3
"""Generate & insert an `## AI Summary` into call-transcript .md files.

Uses the Anthropic API (bring your own key). Set ANTHROPIC_API_KEY in your
environment. Requires the official SDK:  pip install anthropic

- Idempotent: skips any file that already contains `## AI Summary`.
- Inserts the summary between the YAML frontmatter and the `# Transcript` heading.
- Continues past individual failures; prints a per-file status line.

Usage:
  summarize.py --dir DIR [--model MODEL] [--dry] [--limit N]

Defaults: DIR = ./transcripts, MODEL = $ANTHROPIC_MODEL or claude-opus-4-8
(set --model claude-sonnet-5 for a cheaper/faster option).
"""
import glob
import os
import re
import sys

try:
    import anthropic
except ImportError:
    sys.exit("The 'anthropic' package is required. Install it with:  pip install anthropic")

DEFAULT_DIR = "./transcripts"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

SYSTEM = """You are summarizing a meeting/call transcript. \
Output ONLY a markdown "AI Summary" section — no preamble, no sign-off, no code fences, nothing after it.

Format EXACTLY like this:
- First line: `## AI Summary`
- Then 3 to 6 `### ` subsections whose titles describe the actual substance of THIS call (not generic labels)
- Under each subsection, concise `- ` bullet points; use 2-space-indented nested bullets for supporting detail
- If (and only if) the call has clear action items or follow-ups, end with a `### Next Steps` subsection
- Be specific and information-dense: real names, numbers, product names, decisions, dollar/percentage figures, dates
- Neutral, analytical note-taking voice. Do not reproduce the transcript. Do not wrap output in ``` fences."""


def extract_body(text):
    m = re.search(r"^# Transcript\b", text, re.MULTILINE)
    if not m:
        return None, None
    return text[:m.start()], text[m.start():]


def clean(summary):
    s = summary.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n", "", s)
        s = re.sub(r"\n```$", "", s).strip()
    i = s.find("## AI Summary")
    if i > 0:
        s = s[i:]
    elif i == -1:
        s = "## AI Summary\n\n" + s
    return s.strip()


def summarize(client, transcript, model):
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": transcript}],
    )
    return next((b.text for b in resp.content if b.type == "text"), "")


def main(argv):
    d = argv[argv.index("--dir") + 1] if "--dir" in argv else DEFAULT_DIR
    model = argv[argv.index("--model") + 1] if "--model" in argv else DEFAULT_MODEL
    dry = "--dry" in argv
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY in your environment first.")

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    files = sorted(glob.glob(os.path.join(d, "*.md")))
    if limit:
        files = files[:limit]
    ok = skipped = failed = 0
    for f in files:
        name = os.path.basename(f)
        text = open(f, encoding="utf-8").read()
        if "## AI Summary" in text:
            print(f"SKIP (already summarized): {name}"); skipped += 1; continue
        front, body = extract_body(text)
        if body is None:
            print(f"SKIP (no # Transcript heading): {name}"); skipped += 1; continue
        try:
            summary = clean(summarize(client, body, model))
            secs = summary.count("\n### ")
            if dry:
                print(f"\n===== DRY: {name} ({secs} sections) =====\n{summary}\n"); ok += 1; continue
            open(f, "w", encoding="utf-8").write(front + summary + "\n\n" + body)
            print(f"OK ({secs} sections): {name}"); ok += 1
        except Exception as e:
            print(f"FAIL: {name} -> {e}"); failed += 1
    print(f"\n=== done: {ok} processed, {skipped} skipped, {failed} failed ===")


if __name__ == "__main__":
    main(sys.argv)
