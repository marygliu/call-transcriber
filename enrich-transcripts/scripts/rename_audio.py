#!/usr/bin/env python3
"""Rename `.m4a` audio to match its paired `.md` transcript, and move it into the
`audio files/` subfolder of the transcript directory.

Only relevant when the recorder is configured with keepAudio = true. In the
default transcription-only mode there is no audio to manage.

Pairing key: the timestamp in a raw audio filename (`YYYY-MM-DD-HHMM.m4a`) is matched
against the `# Transcript — <Month D, YYYY> at <h:mm AM/PM>` heading inside each `.md`.
The `.md` files are only READ (for pairing) — never modified. Only `.m4a` files move/rename.

Handles audio found either at the top level of the transcript dir or already inside
`audio files/`. Idempotent: audio already correctly named AND already in the subfolder
is left alone.

Usage: rename_audio.py --dir DIR [--dry]
Default DIR = ./transcripts ; audio subfolder = DIR/"audio files"
"""
import glob
import os
import re
import sys
from datetime import datetime

DEFAULT_DIR = "./transcripts"
AUDIO_SUBDIR = "audio files"
TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})$")   # YYYY-MM-DD-HHMM
HEADING_RE = re.compile(r"^# Transcript\s*[—\-]\s*(.+?)\s*$", re.MULTILINE)


def md_key(path):
    """Return 'YYYY-MM-DD-HHMM' parsed from the transcript heading, or None."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()          # read whole file: heading sits below the AI Summary
    m = HEADING_RE.search(text)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%B %d, %Y at %I:%M %p")
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%d-%H%M")


def main(argv):
    d = argv[argv.index("--dir") + 1] if "--dir" in argv else DEFAULT_DIR
    dry = "--dry" in argv
    audio_dir = os.path.join(d, AUDIO_SUBDIR)

    # Build maps from the .md files (top level only)
    keymap = {}           # YYYY-MM-DD-HHMM -> md stem
    stems = set()         # all valid md stems
    for md in glob.glob(os.path.join(d, "*.md")):
        stem = os.path.splitext(os.path.basename(md))[0]
        stems.add(stem)
        k = md_key(md)
        if not k:
            continue
        keymap[k] = None if k in keymap else stem

    # Candidate audio: top level + already in the subfolder
    audio = glob.glob(os.path.join(d, "*.m4a")) + glob.glob(os.path.join(audio_dir, "*.m4a"))

    if not dry:
        os.makedirs(audio_dir, exist_ok=True)

    moved = skipped = warned = 0
    for path in sorted(audio):
        base = os.path.basename(path)
        stem = os.path.splitext(base)[0]
        # Resolve the target stem
        if TS_RE.match(stem):                 # raw timestamp name -> look up by heading time
            target_stem = keymap.get(stem)
        elif stem in stems:                   # already carries a valid transcript name
            target_stem = stem
        else:
            print(f"WARN (unrecognized / no matching .md): {base}"); warned += 1; continue
        if not target_stem:
            print(f"WARN (no matching .md): {base}"); warned += 1; continue

        target = os.path.join(audio_dir, target_stem + ".m4a")
        if os.path.abspath(path) == os.path.abspath(target):
            print(f"SKIP (already placed): {base}"); skipped += 1; continue
        if os.path.exists(target):
            print(f"WARN (target exists): {base} -> audio files/{target_stem}.m4a"); warned += 1; continue
        if dry:
            print(f"DRY: {base}  ->  audio files/{target_stem}.m4a"); moved += 1; continue
        os.rename(path, target)
        print(f"OK: {base}  ->  audio files/{target_stem}.m4a"); moved += 1

    verb = "would move/rename" if dry else "moved/renamed"
    print(f"\n=== {verb} {moved}, skipped {skipped}, warnings {warned} ===")


if __name__ == "__main__":
    main(sys.argv)
