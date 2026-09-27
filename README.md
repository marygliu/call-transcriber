# call-transcriber

Granola-style **automatic** call recording on macOS, built on top of [Local Transcriber](https://www.localtranscriber.com/).

When a call starts in Teams, Zoom, or Google Meet, a floating **"Record this call?"** panel pops up. Click **Record** and it transcribes the call on-device to a Markdown file; when you leave the call it stops automatically. An optional [Claude Code](https://claude.com/claude-code) skill then cleans up each transcript — adding an AI summary and frontmatter.

No manual clicking in the recorder. No bot joining your meeting. Everything runs locally except the optional AI-summary step.

---

## ⚠️ Get consent before you record

This tool is a transcriber, not a covert recorder — but transcribing a conversation still captures what other people say, so treat consent as the default, not an afterthought. Following the norms that tools like [Granola publish](https://docs.granola.ai/help-center/consent-security-privacy/getting-consent):

- **Tell people before recording starts, not after.** Mention in the invite that you'll take AI-assisted notes, and say so out loud at the top of the call — a quick "I'm using an AI note-taker for this, any objections?" is enough.
- **Make it a distinct, opt-out-able moment.** Getting consent to transcribe is separate from consent to have the meeting. Give people a clear chance to say no.
- **You are responsible for consent where the law requires it.** Recording/consent laws vary by state and country (some require *all* parties to consent). This tool does not obtain consent for you — that's on you.
- **Be mindful of what the mic hears.** Local Transcriber records the microphone directly, so it can pick up side conversations and people near your desk even while you're muted in the call app. Pause or stop recording (menu-bar icon) during anything that shouldn't be captured.

When in doubt, ask. It's a two-second courtesy that avoids a real problem.

---

## How it works

```
call app grabs the mic ──► panel: "Record this call?" [Record] [Ignore]
        │ Record
        ▼
   transcriber start ──► on-device transcription to a .md file
        │
        ▼
   you leave the call ──► transcriber stop  (audio auto-deleted by default)
        │
        ▼   (optional, via Claude Code)
   /enrich-transcripts ──► adds AI summary + frontmatter
```

**Trigger** — A tiny Swift helper reads which process is holding the microphone (using the per-process CoreAudio API, macOS 14.4+). [Hammerspoon](https://www.hammerspoon.org/) polls it and, when a call app grabs the mic, shows the panel. Detection is by an **allowlist of bundle IDs**, so non-call mic use (Voice Memos, dictation, etc.) never triggers a prompt.

**Google Meet** runs in the browser, so it's detected by checking for a `meet.google.com` tab when Chrome/Safari holds the mic.

---

## Prerequisites

- **macOS 14.4 or newer** (Sonoma+) — required for the per-process microphone API.
- **[Local Transcriber](https://www.localtranscriber.com/)** installed.
- **Xcode Command Line Tools** (`xcode-select --install`) — provides `swiftc` to compile the helper.
- **[Homebrew](https://brew.sh/)** — used to install Hammerspoon.
- For the optional enrich step: **Python 3**, `pip install anthropic`, and an **`ANTHROPIC_API_KEY`**.

---

## Install

```bash
git clone <this repo>
cd call-transcriber
./install.sh
```

The installer will:
1. Check macOS version, `swiftc`, and Homebrew.
2. Install Hammerspoon if it's missing.
3. Compile the `mic-owner` helper into `~/.hammerspoon/bin/`.
4. Copy `call_recorder.lua` into `~/.hammerspoon/` and add one `require("call_recorder")` line to your `~/.hammerspoon/init.lua` (it won't clobber an existing config).
5. Symlink the `transcriber` CLI onto your PATH (if Local Transcriber is installed).

Then:
- **Launch Hammerspoon** and grant it the permissions it asks for. (Reading Chrome/Safari tabs for Google Meet needs **Automation** access — you'll be prompted the first time. The core recorder does **not** need Accessibility.)
- In Hammerspoon settings, enable **Launch Hammerspoon at login** so it's always running.
- Set **Local Transcriber's save folder** to wherever you want transcripts.

You should see a 🎙️ icon in the menu bar. That's it — your next Teams/Zoom/Meet call will prompt you.

---

## Recording behavior

- **Transcription-only by default.** After post-processing, the `.m4a` audio is deleted and only the `.md` transcript is kept. Set `keepAudio = true` in `call_recorder.lua` to retain audio (needed if you want to re-run diarization later).
- **Muting in the call app does not pause recording.** Local Transcriber records the mic directly, independent of the app's mute button. To actually pause, use the 🎙️ menu-bar icon.
- **Menu bar** — start/stop manually, or "Pause auto-detect" to silence prompts for a while.

### Configuration

Edit the `CONFIG` block at the top of `~/.hammerspoon/call_recorder.lua`, then pick **Reload config** from the 🎙️ menu:

| Setting | Default | What it does |
|---|---|---|
| `keepAudio` | `false` | Keep the `.m4a` (`true`) or transcription-only (`false`) |
| `pollSec` | `2` | How often to check the mic |
| `promptTimeout` | `8` | Seconds before the prompt auto-dismisses (= don't record) |
| `stopGrace` | `3` | Cold-mic polls before stopping (~6s; rides over mutes) |
| `callApps` | Teams, Zoom | Allowlist of call apps — add your own |
| `debug` | `false` | Write a diagnostic log to `~/.hammerspoon/callrec.log` |

---

## Enriching transcripts (optional, via Claude Code)

The `enrich-transcripts/` folder is a [Claude Code](https://claude.com/claude-code) skill. Copy it into your Claude skills directory (or run the scripts directly). It adds an `## AI Summary` and frontmatter to each transcript, and bundles two helpers:

- **`vtt_to_md.py`** — convert a Teams/WebVTT caption export (`.vtt`) into a standardized transcript `.md`, so Teams meetings flow through the same pipeline.
- **`purge_audio.py`** — delete a `.m4a` once its transcript is safely summarized (privacy-first; only relevant if you set `keepAudio = true`).

Run the summary step standalone (no Claude Code required):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
pip install anthropic
python3 enrich-transcripts/scripts/summarize.py --dir "<your transcript folder>" --dry --limit 1  # preview
python3 enrich-transcripts/scripts/summarize.py --dir "<your transcript folder>"                   # apply
```

Set `--model claude-sonnet-5` for a cheaper/faster model than the default. See [`enrich-transcripts/SKILL.md`](enrich-transcripts/SKILL.md) for the full workflow, including `.vtt` conversion, audio purge, and the optional calendar-matching step.

---

## Troubleshooting

- **No panel on a call?** Check the 🎙️ icon is present (Hammerspoon running) and not paused. Turn on `debug = true`, reload, make a call, and read `~/.hammerspoon/callrec.log` to see what the mic detector saw.
- **Panel for the wrong app / not your call app?** Add the app's bundle ID prefix to `callApps` in the config. Find it with: `osascript -e 'id of app "Your App"'`.
- **`transcriber: command not found`?** Re-run `./install.sh`, or symlink it yourself: `ln -sf "/Applications/Local Transcriber.app/Contents/Resources/transcriber-cli" /opt/homebrew/bin/transcriber`.
- **Meet not detected?** The browser tab check needs Automation permission for Hammerspoon → Chrome/Safari (granted on first use).

---

## What's in here

```
call-transcriber/
├── install.sh                     one-command setup
├── recorder/
│   ├── call_recorder.lua          the Hammerspoon watcher + prompt + state machine
│   └── mic-owner.swift            per-process mic-owner helper (compiled by install.sh)
└── enrich-transcripts/            optional Claude Code skill
    ├── SKILL.md
    └── scripts/{summarize.py, vtt_to_md.py, purge_audio.py}
```

## License

MIT — see [LICENSE](LICENSE).
