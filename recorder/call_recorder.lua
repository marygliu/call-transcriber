-- ============================================================================
-- call_recorder — Granola-style automatic trigger for Local Transcriber
--
-- Watches which process is capturing the microphone (via the mic-owner helper).
-- When a *call app* (Teams / Zoom / Google Meet) starts using the mic, it shows
-- a floating "Record this call?" panel. Click Record -> `transcriber start`.
-- When the call's mic goes cold for a grace period -> `transcriber stop`.
-- Non-call mic use (Voice Memos, dictation, etc.) is ignored by construction:
-- only allowlisted bundle IDs ever prompt.
--
-- Load it from ~/.hammerspoon/init.lua with:   require("call_recorder")
-- (install.sh does this for you.)
-- ============================================================================

local M = {}

-- ── CONFIG (edit these) ─────────────────────────────────────────────────────
M.config = {
  -- Path to the Local Transcriber CLI. This is the default install location.
  transcriber = "/Applications/Local Transcriber.app/Contents/Resources/transcriber-cli",

  -- Delete the .m4a after post-processing, keeping only the .md transcript.
  -- true  = keep audio (lets you re-run diarization later with `transcriber reprocess`)
  -- false = transcription-only; the audio recording is not retained
  keepAudio = false,

  pollSec       = 2,   -- how often to check the mic (seconds)
  promptTimeout = 8,   -- seconds before the prompt auto-dismisses (= don't record)
  stopGrace     = 3,   -- cold polls before auto-STOPPING a recording (~6s). Teams/Zoom
                       -- keep the mic stream open while muted, so this only debounces
                       -- the ~2s device-release transition, not a mute.
  resetGrace    = 2,   -- cold polls before resetting state when NOT recording, so a
                       -- back-to-back second call re-prompts instead of being ignored.

  debug = false,       -- write a diagnostic log to ~/.hammerspoon/callrec.log

  -- Call-app allowlist: bundle-id PREFIX -> friendly label. Prefix match, so
  -- helper processes (…​.helper) count too. Add your own apps here.
  callApps = {
    { prefix = "com.microsoft.teams2", label = "Microsoft Teams" },
    { prefix = "us.zoom",              label = "Zoom" },
  },
  -- Browsers that might host a Google Meet call. When one of these owns the mic,
  -- we additionally require a meet.google.com tab before prompting.
  browserPrefixes = { "com.google.Chrome", "com.apple.Safari", "com.apple.WebKit" },
}

local C = M.config
local MIC_OWNER = os.getenv("HOME") .. "/.hammerspoon/bin/mic-owner"
local LOG_PATH  = os.getenv("HOME") .. "/.hammerspoon/callrec.log"

pcall(require, "hs.ipc")  -- enables the `hs` command-line bridge (for debugging)

-- ── State ───────────────────────────────────────────────────────────────────
local currentCall  = nil
local promptShown  = false
local dismissed    = false
local recording    = false
local coldPolls    = 0
local paused       = false
local promptCanvas = nil
local promptTimer  = nil
M._audioTimers     = {}   -- held so Lua's GC doesn't reclaim in-flight deletion timers

-- ── Helpers ─────────────────────────────────────────────────────────────────
local function run(cmd) return hs.execute(cmd) or "" end

local function logLine(msg)
  if not C.debug then return end
  local f = io.open(LOG_PATH, "a")
  if f then f:write(os.date("%H:%M:%S") .. "  " .. msg .. "\n"); f:close() end
end

-- Is any Chrome/Safari window showing a Google Meet tab?
local function meetTabOpen()
  local function browserHasMeet(appName)
    if not hs.application.get(appName) then return false end
    local ok, res = hs.osascript.applescript(([[
      tell application "%s"
        repeat with w in windows
          repeat with t in tabs of w
            if (URL of t) contains "meet.google.com" then return true
          end repeat
        end repeat
      end tell
      return false
    ]]):format(appName))
    return ok and res == true
  end
  return browserHasMeet("Google Chrome") or browserHasMeet("Safari")
end

-- Given the bundle IDs currently capturing mic, return a call label or nil.
local function detectCall(owners)
  for _, bid in ipairs(owners) do
    for _, app in ipairs(C.callApps) do
      if bid:sub(1, #app.prefix) == app.prefix then return app.label end
    end
  end
  for _, bid in ipairs(owners) do
    for _, bp in ipairs(C.browserPrefixes) do
      if bid:sub(1, #bp) == bp then
        if meetTabOpen() then return "Google Meet" end
      end
    end
  end
  return nil
end

local function micOwners()
  local out = run("'" .. MIC_OWNER .. "'")
  local list = {}
  for line in out:gmatch("[^\r\n]+") do list[#list + 1] = line end
  return list
end

-- ── Actuator ────────────────────────────────────────────────────────────────
local updateMenu  -- forward declaration

-- The current transcript path, parsed from `transcriber status --json`.
local function currentTranscriptFile()
  local out = run("'" .. C.transcriber .. "' status --json")
  return out:match('"file"%s*:%s*"([^"]+)"')
end

-- After post-processing finishes, delete the sibling .m4a (transcription-only mode).
local function scheduleAudioDeletion(mdPath)
  if not mdPath then return end
  local m4a = mdPath:gsub("%.md$", ".m4a")
  local attempts = 0
  local t
  t = hs.timer.new(3, function()
    attempts = attempts + 1
    local processing = run("'" .. C.transcriber .. "' status --short"):match("Processing") ~= nil
    if (not processing) or attempts >= 20 then
      t:stop()
      if hs.fs.attributes(m4a) then
        os.remove(m4a)
        logLine("deleted audio: " .. m4a)
      end
    end
  end)
  t:start()
  M._audioTimers[#M._audioTimers + 1] = t
end

local function startRecording(label)
  recording = true
  run("'" .. C.transcriber .. "' start")
  hs.alert.show("🎙️ Recording " .. (label or "call"), 2)
  updateMenu()
end

local function stopRecording()
  if recording then
    local file = currentTranscriptFile()   -- capture while status still points at it
    run("'" .. C.transcriber .. "' stop")
    hs.alert.show("⏹️ Recording stopped", 2)
    if not C.keepAudio then scheduleAudioDeletion(file) end
  end
  recording = false
  updateMenu()
end

-- ── Floating prompt (non-blocking hs.canvas) ────────────────────────────────
local function closePrompt()
  if promptTimer then promptTimer:stop(); promptTimer = nil end
  if promptCanvas then promptCanvas:delete(); promptCanvas = nil end
  promptShown = false
end

local function showPrompt(label)
  closePrompt()
  promptShown = true
  local W, H = 320, 132
  local screen = hs.screen.mainScreen():frame()
  local x = screen.x + screen.w - W - 24
  local y = screen.y + 24

  local c = hs.canvas.new({ x = x, y = y, w = W, h = H })
  promptCanvas = c   -- IMPORTANT: keep the reference so closePrompt() can delete it
  c:appendElements(
    { type = "rectangle", action = "fill", roundedRectRadii = { xRadius = 14, yRadius = 14 },
      fillColor = { red = 0.11, green = 0.11, blue = 0.13, alpha = 0.97 } },
    { type = "text", text = "🎙️  Record this call?",
      textSize = 17, textColor = { white = 1 },
      frame = { x = 18, y = 16, w = W - 36, h = 26 } },
    { type = "text", text = label .. " detected",
      textSize = 13, textColor = { white = 0.65 },
      frame = { x = 18, y = 44, w = W - 36, h = 20 } },
    { type = "rectangle", action = "fill", roundedRectRadii = { xRadius = 9, yRadius = 9 },
      fillColor = { red = 0.20, green = 0.55, blue = 1.0, alpha = 1 },
      frame = { x = 18, y = 80, w = 138, h = 38 }, trackMouseUp = true, id = "record" },
    { type = "text", text = "Record", textSize = 15, textColor = { white = 1 },
      textAlignment = "center", frame = { x = 18, y = 88, w = 138, h = 22 },
      trackMouseUp = true, id = "record" },
    { type = "rectangle", action = "fill", roundedRectRadii = { xRadius = 9, yRadius = 9 },
      fillColor = { white = 0.28, alpha = 1 },
      frame = { x = 164, y = 80, w = 138, h = 38 }, trackMouseUp = true, id = "ignore" },
    { type = "text", text = "Ignore", textSize = 15, textColor = { white = 0.9 },
      textAlignment = "center", frame = { x = 164, y = 88, w = 138, h = 22 },
      trackMouseUp = true, id = "ignore" }
  )
  c:mouseCallback(function(_, evt, id)
    if evt ~= "mouseUp" then return end
    if id == "record" then
      closePrompt(); startRecording(label)
    elseif id == "ignore" then
      dismissed = true; closePrompt()
    end
  end)
  c:level(hs.canvas.windowLevels.overlay)
  c:show()

  promptTimer = hs.timer.doAfter(C.promptTimeout, function()
    dismissed = true; closePrompt()   -- timeout = don't record
  end)
end

-- ── Main poll loop ──────────────────────────────────────────────────────────
local function tick()
  if paused then return end
  local owners = micOwners()
  local activeCall = detectCall(owners)

  if activeCall or currentCall or recording or #owners > 0 then
    logLine(string.format("owners=[%s]  active=%s  current=%s  rec=%s  cold=%d",
      table.concat(owners, ","), tostring(activeCall), tostring(currentCall),
      tostring(recording), coldPolls))
  end

  if activeCall then
    coldPolls = 0
    if not currentCall then
      currentCall = activeCall
      if not recording and not dismissed then showPrompt(activeCall) end
    end
  elseif currentCall then
    -- Mic cold. If recording, wait out stopGrace so a mid-call mute doesn't cut
    -- the recording. If NOT recording, reset quickly so a new call re-prompts.
    coldPolls = coldPolls + 1
    local grace = recording and C.stopGrace or C.resetGrace
    if coldPolls >= grace then
      stopRecording()
      currentCall = nil; dismissed = false; coldPolls = 0
      if promptShown then closePrompt() end
    end
  end
end

-- ── Menu-bar control ────────────────────────────────────────────────────────
local menu = hs.menubar.new()

updateMenu = function()
  if not menu then return end
  menu:setTitle(recording and "🔴" or (paused and "🎙️⏸" or "🎙️"))
  menu:setMenu({
    { title = recording and "Recording…  (Stop now)" or "Start recording now",
      fn = function() if recording then stopRecording() else startRecording("manual") end end },
    { title = "-" },
    { title = paused and "Resume auto-detect" or "Pause auto-detect",
      fn = function() paused = not paused; updateMenu() end },
    { title = "Reload config", fn = function() hs.reload() end },
  })
end

-- ── Debug hooks (safe to leave; usable via `hs -c "call_recorder.state()"`) ──
M.detect      = function(list) return detectCall(list) end
M.micOwners   = micOwners
M.showPrompt  = function(label) showPrompt(label or "Test call") end
M.closePrompt = closePrompt
M.state = function()
  return string.format("currentCall=%s recording=%s dismissed=%s paused=%s promptShown=%s keepAudio=%s",
    tostring(currentCall), tostring(recording), tostring(dismissed),
    tostring(paused), tostring(promptShown), tostring(C.keepAudio))
end

-- ── Start ───────────────────────────────────────────────────────────────────
updateMenu()
-- Clean up any open prompt before a reload/quit, so it can't orphan on screen.
hs.shutdownCallback = function() pcall(closePrompt) end
-- Held on M (which package.loaded keeps alive) so the timer isn't GC'd.
M._watcher = hs.timer.new(C.pollSec, tick)
M._watcher:start()

-- Expose as a global too, so `hs -c "call_recorder.state()"` works.
call_recorder = M
return M
