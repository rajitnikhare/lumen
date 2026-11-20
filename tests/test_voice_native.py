import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("xcrun") is None,
    reason="Requires Apple's Swift compiler; synthetic buffers only, never records.",
)
def test_native_audio_levels_and_empty_final_errors(tmp_path):
    source = tmp_path / "VoiceChecks.swift"
    source.write_text(
        """
import AVFoundation
import Foundation

@main struct VoiceChecks {
  static func main() {
    let format = AVAudioFormat(
      commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 2, interleaved: false)!
    let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4)!
    assert(VoiceCapture.inputLevel(buffer) == nil)
    buffer.frameLength = 4
    for channel in 0..<2 {
      for frame in 0..<4 { buffer.floatChannelData![channel][frame] = 0 }
    }
    assert(VoiceCapture.inputLevel(buffer) == 0)
    buffer.floatChannelData![1][3] = -0.25
    assert(VoiceCapture.inputLevel(buffer) == 0.25)
    buffer.floatChannelData![0][0] = .nan
    assert(VoiceCapture.inputLevel(buffer) == nil)
    let packedFormat = AVAudioFormat(
      commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 2, interleaved: true)!
    let packed = AVAudioPCMBuffer(pcmFormat: packedFormat, frameCapacity: 4)!
    packed.frameLength = 4
    for sample in 0..<8 { packed.floatChannelData![0][sample] = 0 }
    packed.floatChannelData![0][7] = -0.5
    assert(VoiceCapture.inputLevel(packed) == 0.5)
    assert(VoiceCapture.emptyTranscriptMessage(frames: 0, peak: nil, input: "Test input")
      .contains("no audio buffers"))
    assert(VoiceCapture.emptyTranscriptMessage(frames: 4, peak: 0.001, input: "Test input")
      .contains("silent or very quiet"))
    assert(VoiceCapture.emptyTranscriptMessage(frames: 4, peak: 0.002, input: "Test input")
      .contains("Audio reached Lumen"))
    let error = NSError(domain: "SyntheticRecognition", code: 1101)
    switch VoiceCapture.recognitionCompletion(text: "", isFinal: true, error: error) {
    case .failure(let reported): assert((reported as NSError).code == 1101)
    default: fatalError("An empty final result hid the recognition error")
    }
    switch VoiceCapture.recognitionCompletion(text: "Valid final text", isFinal: true, error: error) {
    case .transcript(let text): assert(text == "Valid final text")
    default: fatalError("A valid final transcript was discarded")
    }
    switch VoiceCapture.recognitionCompletion(text: "  ", isFinal: true, error: nil) {
    case .empty: break
    default: fatalError("Whitespace must not become a transcript")
    }
    switch VoiceCapture.recognitionCompletion(text: "Partial text", isFinal: false, error: nil) {
    case .pending: break
    default: fatalError("Partial text was silently finalized")
    }
    let voice = VoiceCapture()
    assert(!voice.microphoneRunning && voice.state == .idle)
    print("Synthetic voice checks passed; microphone never started")
  }
}
""",
        encoding="utf-8",
    )
    executable = tmp_path / "voice-checks"
    subprocess.run(
        [
            "xcrun",
            "swiftc",
            "-parse-as-library",
            str(Path(__file__).resolve().parents[1] / "native" / "VoiceCapture.swift"),
            str(source),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [str(executable)], check=True, capture_output=True, text=True, timeout=10
    )
    assert "microphone never started" in result.stdout


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("xcrun") is None,
    reason="Requires Apple's Swift compiler; synthetic app-local events only.",
)
def test_period_enter_chord_and_ordinary_typing(tmp_path):
    source = tmp_path / "ShortcutChecks.swift"
    source.write_text(
        """
import AppKit
import Carbon

@main struct ShortcutChecks {
  static func event(
    _ type: NSEvent.EventType, _ code: Int, _ text: String,
    repeatKey: Bool = false, modifiers: NSEvent.ModifierFlags = []
  ) -> NSEvent {
    return NSEvent.keyEvent(
      with: type, location: .zero, modifierFlags: modifiers, timestamp: 1,
      windowNumber: 0, context: nil, characters: text, charactersIgnoringModifiers: text,
      isARepeat: repeatKey, keyCode: UInt16(code))!
  }
  static func main() {
    var activations = 0
    var forwarded: [NSEvent] = []
    let chord = LocalVoiceShortcut(
      onActivate: { activations += 1 }, forward: { forwarded.append($0) })
    let dotDown = event(.keyDown, kVK_ANSI_Period, ".")
    let dotUp = event(.keyUp, kVK_ANSI_Period, ".")
    let enterDown = event(.keyDown, kVK_Return, "\\r")
    let enterUp = event(.keyUp, kVK_Return, "\\r")
    assert(chord.handle(dotDown) == nil)
    assert(chord.handle(enterDown) == nil)
    assert(activations == 1 && forwarded.isEmpty)
    assert(chord.handle(event(.keyDown, kVK_Return, "\\r", repeatKey: true)) == nil)
    assert(chord.handle(dotUp) == nil)
    assert(chord.handle(enterUp) == nil)
    assert(activations == 1)
    assert(chord.handle(dotDown) == nil)
    assert(chord.handle(dotUp) === dotUp)
    assert(forwarded.count == 1 && forwarded[0] === dotDown)
    assert(chord.handle(enterDown) === enterDown)
    assert(activations == 1)
    forwarded.removeAll()
    assert(chord.handle(dotDown) == nil)
    let letter = event(.keyDown, kVK_ANSI_A, "a")
    assert(chord.handle(letter) === letter)
    assert(forwarded.count == 1 && forwarded[0] === dotDown)
    assert(chord.handle(enterDown) === enterDown)
    _ = chord.handle(dotUp)
    forwarded.removeAll()
    _ = chord.handle(dotDown)
    let repeatDot = event(.keyDown, kVK_ANSI_Period, ".", repeatKey: true)
    assert(chord.handle(repeatDot) === repeatDot)
    assert(forwarded.count == 1)
    assert(chord.handle(enterDown) === enterDown)
    _ = chord.handle(dotUp)
    forwarded.removeAll()
    _ = chord.handle(dotDown)
    let modifiedEnter = event(.keyDown, kVK_Return, "\\r", modifiers: [.command])
    assert(chord.handle(modifiedEnter) === modifiedEnter)
    assert(activations == 1 && forwarded.count == 1)
    _ = chord.handle(dotUp)
    forwarded.removeAll()
    _ = chord.handle(dotDown)
    chord.reset()
    assert(forwarded.count == 2 && forwarded[1].type == .keyUp)
    assert(chord.handle(enterDown) === enterDown)
    forwarded.removeAll()
    _ = chord.handle(dotDown)
    chord.reset(forwardPending: false)
    assert(forwarded.isEmpty && chord.handle(enterDown) === enterDown)
    _ = chord.handle(dotDown)
    assert(chord.handle(event(.keyDown, kVK_ANSI_KeypadEnter, "\\r")) == nil)
    assert(activations == 2)
    chord.reset(forwardPending: false)
    let shifted = event(.keyDown, kVK_ANSI_Period, ">", modifiers: [.shift])
    assert(chord.handle(shifted) === shifted)
    assert(chord.handle(enterDown) === enterDown)
    assert(activations == 2)
    print("Local chord and normal typing checks passed; no events posted globally")
  }
}
""",
        encoding="utf-8",
    )
    executable = tmp_path / "shortcut-checks"
    subprocess.run(
        [
            "xcrun",
            "swiftc",
            "-parse-as-library",
            str(Path(__file__).resolve().parents[1] / "native" / "LocalVoiceShortcut.swift"),
            str(source),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [str(executable)], check=True, capture_output=True, text=True, timeout=10
    )
    assert "no events posted globally" in result.stdout
