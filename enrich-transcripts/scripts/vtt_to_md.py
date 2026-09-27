#!/usr/bin/env python3
"""Convert a Teams/WebVTT capture (.vtt) into a standardized transcript .md body.

Teams exports a meeting caption file named after the meeting subject, with only
*relative* cue offsets inside (no wall-clock, no date). This script parses the
cues, sorts them by start offset, merges consecutive same-speaker runs into one
utterance, maps anonymous `@N` speakers to `Unknown`, and stamps each utterance
with a wall-clock time derived from a meeting start you supply (`--start`).

The output matches the `# Transcript — <date> at <time>` body shape the rest of
the enrich pipeline (summarize.py, purge_audio.py) expects, so a converted file
flows straight into rename -> frontmatter -> AI Summary.

Usage:
  vtt_to_md.py FILE.vtt --start "YYYY-MM-DD HH:MM" [--out FILE.md | --dry]
                        [--map "@1=Jane Doe,@2=John Roe"]

- `--start` is the meeting's *local* wall-clock start (in your local timezone).
  Get it from the matched calendar event (convert to your local time before passing).
- Default output path: alongside the .vtt, same stem, `.md` extension.
- `--dry` prints the converted markdown to stdout and writes nothing.
- Refuses to overwrite an existing --out file unless `--force`.
"""
import argparse, html, os, re, sys
from datetime import datetime, timedelta

CUE_TIME = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[.,](\d{3})")
VOICE = re.compile(r"<v\s+([^>]*)>(.*?)</v>", re.DOTALL)
TAG = re.compile(r"<[^>]+>")


def _secs(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_cues(text):
    """Yield (start_seconds, speaker_or_None, text) for each cue block."""
    cues = []
    # Blocks are separated by blank lines; a block may carry an id line, then a
    # timestamp line, then one or more text lines.
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines or lines[0].strip() == "WEBVTT":
            continue
        tline = next((ln for ln in lines if CUE_TIME.search(ln)), None)
        if not tline:
            continue
        m = CUE_TIME.search(tline)
        start = _secs(*m.group(1, 2, 3, 4))
        idx = lines.index(tline)
        payload = " ".join(lines[idx + 1:]).strip()
        if not payload:
            continue
        vm = VOICE.search(payload)
        if vm:
            speaker = vm.group(1).strip()
            body = " ".join(v.group(2) for v in VOICE.finditer(payload))
        else:
            speaker = None
            body = payload
        body = html.unescape(TAG.sub("", body))
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            cues.append((start, speaker, body))
    cues.sort(key=lambda c: c[0])
    return cues


def normalize_speaker(name, mapping):
    if name is None:
        return None
    if name in mapping:
        return mapping[name]
    if re.fullmatch(r"@\d+", name.strip()):
        return "Unknown"
    return name.strip()


def merge_runs(cues, mapping):
    """Collapse consecutive same-speaker cues into utterances (start, speaker, text)."""
    out = []
    last_speaker = "Unknown"
    for start, raw, body in cues:
        sp = normalize_speaker(raw, mapping)
        if sp is None:              # untagged cue -> attribute to whoever spoke last
            sp = last_speaker
        if out and out[-1][1] == sp:
            out[-1][2].append(body)
        else:
            out.append([start, sp, [body]])
        last_speaker = sp
    return [(s, sp, " ".join(parts)) for s, sp, parts in out]


def fmt_dur(secs):
    secs = int(secs)  # floor: elapsed time, not rounded
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def convert(vtt_text, start_dt, mapping):
    cues = parse_cues(vtt_text)
    if not cues:
        raise ValueError("no cues parsed from .vtt")
    utterances = merge_runs(cues, mapping)
    speakers = {u[1] for u in utterances}
    duration = fmt_dur(cues[-1][0])  # last cue start ~= recording length
    # header date: "July 29, 2026 at 10:00 AM"
    head_dt = start_dt.strftime("%B %d, %Y at %I:%M %p")
    head_dt = re.sub(r" 0", " ", head_dt).lstrip("0")  # strip leading zeros
    lines = [f"# Transcript — {head_dt}", "",
             f"**Duration:** {duration} · **Speakers:** {len(speakers)}", "",
             "---", ""]
    for off, sp, body in utterances:
        stamp = (start_dt + timedelta(seconds=off)).strftime("%H:%M:%S")
        lines.append(f"**[{stamp}] {sp}:** {body}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("vtt")
    ap.add_argument("--start", required=True, help='meeting local start "YYYY-MM-DD HH:MM"')
    ap.add_argument("--out", help="output .md path (default: alongside .vtt)")
    ap.add_argument("--map", default="", help='e.g. "@1=Jane Doe,@2=John Roe"')
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)

    try:
        start_dt = datetime.strptime(a.start, "%Y-%m-%d %H:%M")
    except ValueError:
        sys.exit(f"--start must be 'YYYY-MM-DD HH:MM', got {a.start!r}")
    mapping = {}
    for pair in filter(None, (p.strip() for p in a.map.split(","))):
        k, _, v = pair.partition("=")
        mapping[k.strip()] = v.strip()

    text = open(a.vtt, encoding="utf-8-sig").read()
    md = convert(text, start_dt, mapping)

    if a.dry:
        sys.stdout.write(md)
        return
    out = a.out or os.path.splitext(a.vtt)[0] + ".md"
    if os.path.exists(out) and not a.force:
        sys.exit(f"refusing to overwrite existing {out} (use --force)")
    open(out, "w", encoding="utf-8").write(md)
    print(f"OK: wrote {out} ({len(md.splitlines())} lines)")


if __name__ == "__main__":
    main(sys.argv[1:])
