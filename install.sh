#!/usr/bin/env bash
# call-transcriber installer — idempotent. Safe to re-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HS_DIR="$HOME/.hammerspoon"
TRANSCRIBER_CLI="/Applications/Local Transcriber.app/Contents/Resources/transcriber-cli"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m warning:\033[0m %s\n' "$1"; }
die()  { printf '\033[1;31m error:\033[0m %s\n' "$1" >&2; exit 1; }

# 1. macOS version (need 14.4+ for the per-process CoreAudio API)
say "Checking macOS version…"
ver="$(sw_vers -productVersion)"
major="${ver%%.*}"; rest="${ver#*.}"; minor="${rest%%.*}"
if [ "$major" -lt 14 ] || { [ "$major" -eq 14 ] && [ "${minor:-0}" -lt 4 ]; }; then
  die "macOS 14.4+ required (found $ver). The per-process microphone API isn't available on older versions."
fi
echo "   macOS $ver — OK"

# 2. swiftc
say "Checking for swiftc…"
command -v swiftc >/dev/null 2>&1 || die "swiftc not found. Install the Xcode Command Line Tools:  xcode-select --install"
echo "   $(swiftc --version 2>&1 | head -1)"

# 3. Homebrew + Hammerspoon
say "Checking for Homebrew…"
command -v brew >/dev/null 2>&1 || die "Homebrew not found. Install it from https://brew.sh, then re-run."
if [ ! -d "/Applications/Hammerspoon.app" ]; then
  say "Installing Hammerspoon…"
  brew install --cask hammerspoon
else
  echo "   Hammerspoon already installed"
fi

# 4. Compile the mic-owner helper
say "Compiling the mic-owner helper…"
mkdir -p "$HS_DIR/bin"
swiftc -O "$SCRIPT_DIR/recorder/mic-owner.swift" -o "$HS_DIR/bin/mic-owner" \
  -framework CoreAudio -framework Foundation
echo "   built $HS_DIR/bin/mic-owner"

# 5. Install the recorder module
say "Installing call_recorder.lua…"
cp "$SCRIPT_DIR/recorder/call_recorder.lua" "$HS_DIR/call_recorder.lua"

# Wire up the loader without clobbering an existing init.lua
INIT="$HS_DIR/init.lua"
touch "$INIT"
if grep -q 'require("call_recorder")' "$INIT" || grep -q "require('call_recorder')" "$INIT"; then
  echo "   loader already present in init.lua"
else
  printf '\nrequire("call_recorder")  -- call-transcriber\n' >> "$INIT"
  echo "   appended require(\"call_recorder\") to init.lua"
fi

# 6. Symlink the transcriber CLI
say "Linking the transcriber CLI…"
if [ -x "$TRANSCRIBER_CLI" ]; then
  for d in /opt/homebrew/bin /usr/local/bin "$HOME/.local/bin"; do
    if [ -d "$d" ] && [ -w "$d" ]; then
      ln -sf "$TRANSCRIBER_CLI" "$d/transcriber"
      echo "   symlinked $d/transcriber"
      linked=1; break
    fi
  done
  [ "${linked:-0}" = 1 ] || warn "no writable bin dir on PATH; Hammerspoon uses the absolute path anyway."
else
  warn "Local Transcriber not found at the default location. Install it from https://www.localtranscriber.com/ (the recorder needs it)."
fi

cat <<'DONE'

✅ Installed. Next steps:
   1. Launch Hammerspoon and grant the permissions it requests.
      (Automation access for Chrome/Safari is needed only for Google Meet detection.)
   2. In Hammerspoon settings, enable "Launch Hammerspoon at login".
   3. Set Local Transcriber's save folder to wherever you want transcripts.
   4. Look for the 🎙️ icon in your menu bar — your next call will prompt you.

   Tune behavior (incl. keepAudio) in ~/.hammerspoon/call_recorder.lua,
   then pick "Reload config" from the 🎙️ menu.
DONE
