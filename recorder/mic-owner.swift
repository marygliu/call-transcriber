// mic-owner — prints the bundle IDs of every process currently capturing mic input,
// one per line. Uses the macOS 14.4+ per-process CoreAudio API. Read-only: it inspects
// audio-object flags, so it needs no microphone permission of its own.
import CoreAudio
import Foundation

let sys = AudioObjectID(kAudioObjectSystemObject)
var listAddr = AudioObjectPropertyAddress(
  mSelector: kAudioHardwarePropertyProcessObjectList,
  mScope: kAudioObjectPropertyScopeGlobal,
  mElement: kAudioObjectPropertyElementMain)

var size = UInt32(0)
guard AudioObjectGetPropertyDataSize(sys, &listAddr, 0, nil, &size) == 0 else { exit(0) }
let count = Int(size) / MemoryLayout<AudioObjectID>.size
var procs = [AudioObjectID](repeating: 0, count: count)
guard AudioObjectGetPropertyData(sys, &listAddr, 0, nil, &size, &procs) == 0 else { exit(0) }

func bundleID(_ obj: AudioObjectID) -> String? {
  var a = AudioObjectPropertyAddress(mSelector: kAudioProcessPropertyBundleID,
    mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
  var sz = UInt32(MemoryLayout<CFString?>.size)
  var cf: Unmanaged<CFString>?
  let s = withUnsafeMutablePointer(to: &cf) { AudioObjectGetPropertyData(obj, &a, 0, nil, &sz, $0) }
  guard s == 0, let cf = cf else { return nil }
  return cf.takeRetainedValue() as String
}

func isCapturing(_ obj: AudioObjectID) -> Bool {
  var a = AudioObjectPropertyAddress(mSelector: kAudioProcessPropertyIsRunningInput,
    mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
  var v = UInt32(0)
  var sz = UInt32(MemoryLayout<UInt32>.size)
  guard AudioObjectGetPropertyData(obj, &a, 0, nil, &sz, &v) == 0 else { return false }
  return v == 1
}

var seen = Set<String>()
for p in procs where isCapturing(p) {
  if let b = bundleID(p), !b.isEmpty, seen.insert(b).inserted {
    print(b)
  }
}
