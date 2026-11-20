import AVFoundation
import Foundation
import Speech

final class VoiceCapture {
  enum State { case idle, authorizing, recording, finishing }
  enum RecognitionCompletion {
    case pending
    case transcript(String)
    case failure(Error)
    case empty
  }
  private(set) var state: State = .idle
  private(set) var inputName = "system default microphone"
  var onStateChange: ((State) -> Void)?
  var onInputLevel: ((Float?) -> Void)?
  var onPartial: ((String) -> Void)?
  var onComplete: ((String) -> Void)?
  var onFailure: ((String) -> Void)?
  var authorizeRecording: ((@escaping (Result<Void, Error>) -> Void) -> Void)?
  private var identifier: UUID?
  private var engine: AVAudioEngine?
  private var recognizer: SFSpeechRecognizer?
  private var request: SFSpeechAudioBufferRecognitionRequest?
  private var task: SFSpeechRecognitionTask?
  private var tapInstalled = false
  private var durationTimer: Timer?
  private var finishTimer: Timer?
  private var receivedFrames = 0
  private var peakLevel: Float?

  var microphoneRunning: Bool { engine?.isRunning == true }

  static func inputLevel(_ buffer: AVAudioPCMBuffer) -> Float? {
    guard buffer.frameLength > 0, let channels = buffer.floatChannelData else { return nil }
    var peak: Float = 0
    for channel in 0..<Int(buffer.format.channelCount) {
      for frame in 0..<Int(buffer.frameLength) {
        let sample =
          buffer.format.isInterleaved
          ? channels[0][frame * Int(buffer.format.channelCount) + channel]
          : channels[channel][frame]
        guard sample.isFinite else { return nil }
        peak = max(peak, abs(sample))
      }
    }
    return peak
  }

  static func recognitionCompletion(
    text: String?, isFinal: Bool, error: Error?
  ) -> RecognitionCompletion {
    if isFinal, let text = text,
      !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    {
      return .transcript(text)
    }
    if let error = error { return .failure(error) }
    return isFinal ? .empty : .pending
  }

  static func emptyTranscriptMessage(frames: Int, peak: Float?, input: String) -> String {
    let detail: String
    if frames == 0 {
      detail = "\(input) delivered no audio buffers."
    } else if let peak = peak, peak < 0.002 {
      detail = "The signal from \(input) was silent or very quiet."
    } else {
      detail = "Audio reached Lumen from \(input), but no words were recognized."
    }
    return detail
      + " Check System Settings > Sound > Input, the input volume, and your headset's mute/connection. "
      + "Try speaking several words in the Dictation language after the input meter starts moving. "
      + "The microphone is off. No transcript was inserted and no cloud fallback was used."
  }

  static func localRequest() -> SFSpeechAudioBufferRecognitionRequest {
    let request = SFSpeechAudioBufferRecognitionRequest()
    request.requiresOnDeviceRecognition = true
    request.shouldReportPartialResults = true
    request.taskHint = .dictation
    request.addsPunctuation = true
    return request
  }

  func start() {
    guard state == .idle else { return }
    let token = UUID()
    identifier = token
    receivedFrames = 0
    peakLevel = nil
    guard let recognizer = SFSpeechRecognizer(locale: Locale.current),
      recognizer.supportsOnDeviceRecognition
    else {
      fail(
        "On-device speech recognition is not available for \(Locale.current.identifier). "
          + "Check your Mac's Dictation language settings. No cloud fallback or recording was used."
      )
      return
    }
    self.recognizer = recognizer
    setState(.authorizing)
    switch AVCaptureDevice.authorizationStatus(for: .audio) {
    case .authorized:
      authorizeSpeech(token)
    case .notDetermined:
      AVCaptureDevice.requestAccess(for: .audio) { granted in
        DispatchQueue.main.async {
          guard self.identifier == token else { return }
          if granted {
            self.authorizeSpeech(token)
          } else {
            self.fail(
              "Microphone access was denied. Allow Lumen in System Settings > Privacy & Security > Microphone."
            )
          }
        }
      }
    case .denied, .restricted:
      fail(
        "Microphone access is unavailable. Allow Lumen in System Settings > Privacy & Security > Microphone."
      )
    @unknown default:
      fail("macOS returned an unsupported microphone permission state. Recording did not start.")
    }
  }

  private func authorizeSpeech(_ token: UUID) {
    guard identifier == token else { return }
    switch SFSpeechRecognizer.authorizationStatus() {
    case .authorized:
      validateRecording(token)
    case .notDetermined:
      SFSpeechRecognizer.requestAuthorization { status in
        DispatchQueue.main.async {
          guard self.identifier == token else { return }
          if status == .authorized {
            self.validateRecording(token)
          } else {
            self.fail(
              "Speech recognition permission was not granted. Allow Lumen in System Settings > Privacy & Security > Speech Recognition."
            )
          }
        }
      }
    case .denied, .restricted:
      fail(
        "Speech recognition permission is unavailable. Allow Lumen in System Settings > Privacy & Security > Speech Recognition."
      )
    @unknown default:
      fail("macOS returned an unsupported speech permission state. Recording did not start.")
    }
  }

  private func validateRecording(_ token: UUID) {
    guard identifier == token else { return }
    guard let authorizeRecording = authorizeRecording else {
      fail("The recording authorization check is unavailable. The microphone was not started.")
      return
    }
    authorizeRecording { result in
      DispatchQueue.main.async {
        guard self.identifier == token else { return }
        switch result {
        case .success:
          self.beginRecording(token)
        case .failure(let error):
          self.fail(
            "Recording authorization failed: \(error.localizedDescription) The microphone was not started."
          )
        }
      }
    }
  }

  private func beginRecording(_ token: UUID) {
    guard identifier == token else { return }
    guard let recognizer = recognizer, recognizer.supportsOnDeviceRecognition,
      recognizer.isAvailable
    else {
      fail(
        "The on-device speech recognizer is unavailable. Try again after checking Dictation language support; no cloud fallback was used."
      )
      return
    }
    let engine = AVAudioEngine()
    self.engine = engine
    inputName = AVCaptureDevice.default(for: .audio)?.localizedName ?? "system default microphone"
    let input = engine.inputNode
    let format = input.outputFormat(forBus: 0)
    guard format.sampleRate > 0, format.channelCount > 0 else {
      fail(
        "No usable microphone was found. Select or connect an input device in System Settings > Sound."
      )
      return
    }
    let request = Self.localRequest()
    self.request = request
    task = recognizer.recognitionTask(with: request) { result, error in
      DispatchQueue.main.async {
        guard self.identifier == token else { return }
        let text = result?.bestTranscription.formattedString
        if let text = text, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
          self.onPartial?(text)
        }
        switch Self.recognitionCompletion(
          text: text, isFinal: result?.isFinal == true, error: error)
        {
        case .transcript(let text):
          self.complete(text)
        case .failure(let error):
          let details = error as NSError
          self.fail(
            "On-device recognition failed (\(details.domain) \(details.code)): \(error.localizedDescription) "
              + "Nothing was sent to the assistant. Any partial text remains in the recording window."
          )
        case .empty:
          self.complete("")
        case .pending:
          break
        }
      }
    }
    input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
      let frames = Int(buffer.frameLength)
      let level = Self.inputLevel(buffer)
      DispatchQueue.main.async {
        guard let self = self, self.identifier == token else { return }
        self.receivedFrames += frames
        if let level = level { self.peakLevel = max(self.peakLevel ?? 0, level) }
        if self.state == .recording { self.onInputLevel?(level) }
      }
      request.append(buffer)
    }
    tapInstalled = true
    engine.prepare()
    do {
      try engine.start()
      setState(.recording)
      durationTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: false) { _ in
        guard self.identifier == token else { return }
        self.stop()
      }
    } catch {
      fail("The microphone could not start: \(error.localizedDescription)")
    }
  }

  func stop() {
    guard state == .recording, let token = identifier else { return }
    stopAudio()
    request?.endAudio()
    // Ending the buffer request does not finish the recognition task.
    task?.finish()
    setState(.finishing)
    finishTimer = Timer.scheduledTimer(withTimeInterval: 8, repeats: false) { _ in
      guard self.identifier == token else { return }
      self.fail(
        "Speech recognition did not finalize in time. The microphone is off. "
          + "You can explicitly review or copy partial text; nothing was inserted automatically.")
    }
  }

  func cancel() {
    identifier = nil
    cleanup()
    setState(.idle)
  }

  private func stopAudio() {
    durationTimer?.invalidate()
    durationTimer = nil
    engine?.stop()
    if tapInstalled {
      engine?.inputNode.removeTap(onBus: 0)
      tapInstalled = false
    }
  }

  private func cleanup() {
    stopAudio()
    finishTimer?.invalidate()
    finishTimer = nil
    task?.cancel()
    task = nil
    request = nil
    recognizer = nil
    engine = nil
  }

  private func complete(_ text: String) {
    let emptyMessage = Self.emptyTranscriptMessage(
      frames: receivedFrames, peak: peakLevel, input: inputName)
    identifier = nil
    cleanup()
    setState(.idle)
    guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
      onFailure?(emptyMessage)
      return
    }
    onComplete?(text)
  }

  private func fail(_ message: String) {
    identifier = nil
    cleanup()
    setState(.idle)
    onFailure?(message)
  }

  private func setState(_ state: State) {
    self.state = state
    onStateChange?(state)
  }
}
