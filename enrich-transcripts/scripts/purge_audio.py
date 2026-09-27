#!/usr/bin/env python3
"""Delete `.m4a` audio once its paired `.md` transcript has been fully standardized.

Privacy policy (mirrors Granola): don't retain call audio. Once a transcript is
captured and standardized, its recording is deleted. The `.md` files are only
READ (for pairing) — never modified. Only `.m4a` files are deleted.

A recording is deleted ONLY when a paired transcript exists AND is standardized
(contains an `## AI Summary`). This guarantees we never delete audio whose transcript
hasn't been safely captured — mis-fires and needs-review recordings keep their audio.

Pairing:
- Raw-named audio (`YYYY-MM-DD-HHMM.m4a`) -> matched to a `.md` by the
  `# Transcript — <Month D, YYYY> at <h:mm AM/PM>` heading time. (Primary path.)
- Legacy archived audio carrying a full transcript name -> matched to the `.md` with
  the same stem. (Cleans up recordings moved into `audio files/` by an older workflow.)
- Anything that matches neither, or whose transcript isn't standardized -> WARN + KEEP.

Scans the top level of DIR and the legacy `audio files/` subfolder. Idempotent.

Usage: purge_audio.py [--dir DIR] [--dry]
Default DIR = ./transcripts
"""
import glob, os, re, sys
from datetime import datetime

DEFAULT_DIR = "./transcripts"
LEGACY_SUBDIR = "audio files"
TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})$")   # YYYY-MM-DD-HHMM
HEADING_RE = re.compile(r"^# Transcript\s*[—\-]\s*(.+?)\s*$", re.MULTILINE)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def md_key(text):
    """Return 'YYYY-MM-DD-HHMM' parsed from the transcript heading, or None."""
    m = HEADING_RE.search(text)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%B %d, %Y at %I:%M %p")
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%d-%H%M")


def is_standardized(text):
    """A transcript is safe-to-purge-audio-for once it carries an AI Summary."""
    return "## AI Summary" in text


def main(argv):
    d = argv[argv.index("--dir") + 1] if "--dir" in argv else DEFAULT_DIR
    dry = "--dry" in argv
    legacy_dir = os.path.join(d, LEGACY_SUBDIR)

    # Build maps from the .md files (top level only).
    keymap = {}      # YYYY-MM-DD-HHMM -> True if a standardized transcript exists at that time
    ambiguous = set()
    std_stems = set()
    for md in glob.glob(os.path.join(d, "*.md")):
        stem = os.path.splitext(os.path.basename(md))[0]
        text = read(md)
        std = is_standardized(text)
        if std:
            std_stems.add(stem)
        k = md_key(text)
        if k:
            if k in keymap:
                ambiguous.add(k)          # two transcripts at the same heading time
            keymap[k] = std

    audio = glob.glob(os.path.join(d, "*.m4a")) + glob.glob(os.path.join(legacy_dir, "*.m4a"))

    deleted = kept = warned = 0
    for path in sorted(audio):
        base = os.path.basename(path)
        stem = os.path.splitext(base)[0]
        rel = os.path.relpath(path, d)

        if TS_RE.match(stem):                       # raw timestamp name -> pair by heading time
            if stem in ambiguous:
                print(f"WARN (ambiguous: multiple transcripts at that time): {rel}"); warned += 1; continue
            std = keymap.get(stem)
            if std is None:
                print(f"WARN (no matching transcript — keeping audio): {rel}"); warned += 1; continue
            if not std:
                print(f"KEEP (transcript not standardized yet): {rel}"); kept += 1; continue
        elif stem in std_stems:                     # legacy audio carrying a standardized transcript name
            pass
        else:
            print(f"WARN (no matching standardized transcript — keeping audio): {rel}"); warned += 1; continue

        if dry:
            print(f"DRY delete: {rel}"); deleted += 1; continue
        os.remove(path)
        print(f"DELETED: {rel}"); deleted += 1

    verb = "would delete" if dry else "deleted"
    print(f"\n=== {verb} {deleted}, kept {kept}, warnings {warned} ===")


if __name__ == "__main__":
    main(sys.argv)
