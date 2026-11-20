import AppKit
import Carbon
import ServiceManagement
import UniformTypeIdentifiers
import WebKit

final class LumenDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate,
  WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler
{
  private var statusItem: NSStatusItem!
  private var window: NSWindow!
  private var webView: WKWebView!
  private var backend: Process?
  private var backendURL: URL?
  private var outputPipe: Pipe?
  private var errorPipe: Pipe?
  private var outputBuffer = Data()
  private var errorBuffer = Data()
  private var hotKey: EventHotKeyRef?
  private var voiceKeyMonitor: Any?
  private var voiceShortcutEnabled = false
  private let voiceShortcutLabel = ". + Enter (Lumen focused)"
  private lazy var voiceShortcut = LocalVoiceShortcut(
    onActivate: { [weak self] in
      DispatchQueue.main.async { self?.toggleVoiceCapture() }
    },
    forward: { NSApp.sendEvent($0) }
  )
  private var eventHandler: EventHandlerRef?
  private var loginItem: NSMenuItem!
  private var quitting = false
  private var automaticRestarts = 0
  private let smokeTest = CommandLine.arguments.contains("--self-test")
  private let voice = VoiceCapture()
  private var voiceMenu: NSMenuItem!
  private var cancelVoiceMenu: NSMenuItem!
  private var voiceSheet: NSWindow?
  private var voiceStatus: NSTextField?
  private var voiceText: NSTextView?
  private var voiceStop: NSButton?
  private var voiceCopy: NSButton?
  private var voiceReview: NSButton?
  private var voiceLevel: NSLevelIndicator?
  private var voiceInput: NSTextField?
  private var voiceIdentifier: String?
  private var voiceContext: [String: Any]?

  func applicationDidFinishLaunching(_ notification: Notification) {
    NSApp.setActivationPolicy(.accessory)
    let configuration = WKWebViewConfiguration()
    configuration.websiteDataStore = .nonPersistent()
    configuration.userContentController.add(self, name: "lumen")
    webView = WKWebView(frame: .zero, configuration: configuration)
    webView.navigationDelegate = self
    webView.uiDelegate = self
    window = NSWindow(
      contentRect: NSRect(x: 0, y: 0, width: 640, height: 790),
      styleMask: [.titled, .closable, .miniaturizable, .resizable],
      backing: .buffered, defer: false
    )
    window.title = "Lumen"
    window.minSize = NSSize(width: 450, height: 560)
    window.contentView = webView
    window.delegate = self
    window.isReleasedWhenClosed = false
    window.center()
    buildMenu()
    voice.onStateChange = { [weak self] state in self?.updateVoiceState(state) }
    voice.onPartial = { [weak self] text in self?.voiceText?.string = text }
    voice.onInputLevel = { [weak self] level in
      guard let self = self else { return }
      self.voiceLevel?.doubleValue = sqrt(Double(min(1, max(0, level ?? 0))))
      self.voiceInput?.stringValue =
        "Input: \(self.voice.inputName). "
        + (level == nil ? "Level unavailable." : "Watch the meter move while you speak.")
    }
    voice.onComplete = { [weak self] text in self?.insertVoiceTranscript(text) }
    voice.onFailure = { [weak self] message in self?.voiceFailure(message) }
    voice.authorizeRecording = { [weak self] completion in
      guard let self = self, let identifier = self.voiceIdentifier,
        let context = self.voiceContext
      else {
        completion(
          .failure(
            NSError(
              domain: "Lumen.Voice", code: 1,
              userInfo: [
                NSLocalizedDescriptionKey: "The voice session is unavailable. Unlock and try again."
              ])))
        return
      }
      self.webView.callAsyncJavaScript(
        "return await window.lumenMac.validateVoiceCapture(context)",
        arguments: ["context": context], in: nil, in: .page
      ) { result in
        guard self.voiceIdentifier == identifier else {
          completion(
            .failure(
              NSError(
                domain: "Lumen.Voice", code: 2,
                userInfo: [
                  NSLocalizedDescriptionKey: "Voice capture was cancelled."
                ])))
          return
        }
        switch result {
        case .success(let value):
          if value as? Bool == true {
            completion(.success(()))
          } else {
            completion(
              .failure(
                NSError(
                  domain: "Lumen.Voice", code: 3,
                  userInfo: [
                    NSLocalizedDescriptionKey:
                      "The vault or voice session changed. Finish any chat action, unlock, and try again."
                  ])))
          }
        case .failure(let error):
          completion(.failure(error))
        }
      }
    }
    registerShortcut()
    voiceKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .keyUp]) {
      [weak self] event in
      guard let self = self else { return event }
      guard NSApp.isActive, self.voiceShortcutEnabled,
        let focusedWindow = NSApp.keyWindow,
        focusedWindow === self.window || focusedWindow === self.voiceSheet
      else {
        self.voiceShortcut.reset(forwardPending: false)
        return event
      }
      return self.voiceShortcut.handle(event)
    }
    if voiceKeyMonitor == nil {
      alert("Voice shortcut unavailable", "Use Speak to Lumen in the menu bar instead.")
    }
    NotificationCenter.default.addObserver(
      self, selector: #selector(resetVoiceShortcut),
      name: NSApplication.didResignActiveNotification, object: nil
    )
    NSWorkspace.shared.notificationCenter.addObserver(
      self, selector: #selector(lockWorkspace),
      name: NSWorkspace.willSleepNotification, object: nil
    )
    NotificationCenter.default.addObserver(
      self, selector: #selector(cancelVoiceCapture),
      name: NSApplication.didHideNotification, object: nil
    )
    NSWorkspace.shared.notificationCenter.addObserver(
      self, selector: #selector(lockWorkspace),
      name: NSWorkspace.sessionDidResignActiveNotification, object: nil
    )
    startBackend()
    if !CommandLine.arguments.contains("--background") { showWindow() }
    if smokeTest {
      DispatchQueue.main.asyncAfter(deadline: .now() + 25) {
        self.finishSmokeTest(["error": "Native startup timed out."])
      }
    }
  }

  private func buildMenu() {
    statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    statusItem.button?.image = NSImage(
      systemSymbolName: "sparkle", accessibilityDescription: "Lumen")
    statusItem.button?.toolTip = "Lumen - Control Option Space"
    let menu = NSMenu()
    func add(_ title: String, _ action: Selector, _ key: String = "") -> NSMenuItem {
      let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
      item.target = self
      menu.addItem(item)
      return item
    }
    _ = add("Open Lumen    Control Option Space", #selector(showWindow))
    voiceMenu = add("Speak to Lumen    \(voiceShortcutLabel)", #selector(toggleVoiceCapture))
    cancelVoiceMenu = add("Cancel speaking", #selector(cancelVoiceCapture))
    cancelVoiceMenu.isHidden = true
    _ = add("Share clipboard text...", #selector(shareClipboard))
    _ = add("Share a file...", #selector(shareFile))
    menu.addItem(.separator())
    _ = add("Settings...", #selector(openSettings))
    _ = add("Open Ollama", #selector(openOllama))
    loginItem = add("Start at login", #selector(toggleLogin))
    updateLoginStatus()
    _ = add("Lock private workspace", #selector(lockWorkspace))
    _ = add("Restart local service", #selector(restartBackend))
    menu.addItem(.separator())
    _ = add("Quit Lumen", #selector(quit), "q")
    statusItem.menu = menu
  }

  private func registerShortcut() {
    var event = EventTypeSpec(
      eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)
    )
    let installed = InstallEventHandler(
      GetApplicationEventTarget(),
      { _, event, pointer in
        guard let pointer = pointer, let event = event else { return OSStatus(eventNotHandledErr) }
        var identifier = EventHotKeyID()
        guard
          GetEventParameter(
            event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
            nil, MemoryLayout<EventHotKeyID>.size, nil, &identifier
          ) == noErr, identifier.signature == 0x4C55_4D4E
        else { return OSStatus(eventNotHandledErr) }
        let delegate = Unmanaged<LumenDelegate>.fromOpaque(pointer).takeUnretainedValue()
        let action = identifier.id
        DispatchQueue.main.async {
          if action == 1 {
            delegate.showWindow()
          }
        }
        return noErr
      },
      1, &event, Unmanaged.passUnretained(self).toOpaque(), &eventHandler
    )
    guard installed == noErr else {
      alert("Keyboard shortcut unavailable", "Use the Lumen menu-bar icon instead.")
      return
    }
    let result = RegisterEventHotKey(
      UInt32(kVK_Space), UInt32(controlKey | optionKey),
      EventHotKeyID(signature: 0x4C55_4D4E, id: 1),
      GetApplicationEventTarget(), 0, &hotKey
    )
    if result != noErr {
      alert(
        "Keyboard shortcut is in use",
        "Control Option Space is unavailable. The menu-bar icon still works.")
    }
  }

  @objc private func resetVoiceShortcut() { voiceShortcut.reset() }

  @objc func showWindow() {
    NSApp.activate(ignoringOtherApps: true)
    window.makeKeyAndOrderFront(nil)
  }

  func windowShouldClose(_ sender: NSWindow) -> Bool {
    voiceShortcut.reset()
    cancelVoiceCapture()
    sender.orderOut(nil)
    return false
  }

  func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

  @objc private func openSettings() {
    cancelVoiceCapture()
    showWindow()
    webView.evaluateJavaScript("window.lumenMac?.openSettings()") { _, error in
      if let error = error { self.alert("Settings aren't ready", error.localizedDescription) }
    }
  }

  @objc private func lockWorkspace() {
    cancelVoiceCapture()
    guard backendURL != nil else { return }
    webView.evaluateJavaScript("window.lumenMac?.lock(); undefined") { _, error in
      if let error = error {
        self.alert("Could not lock the workspace", error.localizedDescription)
      }
    }
  }

  private func requireUnlocked(_ operation: @escaping ([String: Any]) -> Void) {
    showWindow()
    webView.callAsyncJavaScript(
      "return await window.lumenMac.prepareSharing()",
      arguments: [:], in: nil, in: .page
    ) { result in
      switch result {
      case .failure(let error):
        self.alert("Lumen is not ready", error.localizedDescription)
      case .success(let value):
        guard let context = value as? [String: Any], context["identifier"] is String,
          context["epoch"] is Int, context["vault_generation"] is Int
        else {
          self.alert(
            "Unlock before sharing",
            "Enter your vault passphrase, then share again. No clipboard text or file has been read.")
          return
        }
        operation(context)
      }
    }
  }

  private func validateSharing(_ context: [String: Any], completion: @escaping (Bool) -> Void) {
    webView.callAsyncJavaScript(
      "return await window.lumenMac.validateSharing(context)",
      arguments: ["context": context], in: nil, in: .page
    ) { result in
      guard case .success(let value) = result, value as? Bool == true else {
        self.alert(
          "Sharing cancelled",
          "The workspace or sharing session changed. Unlock and share again. No content was read.")
        completion(false)
        return
      }
      completion(true)
    }
  }

  @objc private func shareClipboard() {
    cancelVoiceCapture()
    copyClipboard(mode: "ask")
  }

  private func copyClipboard(mode: String) {
    requireUnlocked { context in
      AuthorizedCapture.perform(
        authorize: { self.validateSharing(context, completion: $0) }
      ) {
        self.readClipboard(mode: mode, context: context)
      }
    }
  }

  private func readClipboard(mode: String, context: [String: Any]) {
    guard let text = NSPasteboard.general.string(forType: .string), !text.isEmpty else {
      alert(
        "No text to share",
        "Copy a selection in the app you want help with, then choose Share clipboard text.")
      return
    }
    guard text.utf16.count <= 8000 else {
      alert(
        "Select a smaller passage",
        "Share up to 8,000 characters at a time. Clipboard text was not sent to AI.")
      return
    }
    deliver("shareText", value: ["text": text, "mode": mode], context: context)
  }

  @objc private func shareFile() {
    cancelVoiceCapture()
    requireUnlocked { context in
      let panel = NSOpenPanel()
      panel.title = "Choose a file to share with Lumen"
      panel.canChooseDirectories = false
      panel.allowsMultipleSelection = false
      panel.allowedContentTypes = ["pdf", "docx", "txt", "md"].compactMap {
        UTType(filenameExtension: $0)
      }
      panel.beginSheetModal(for: self.window) { result in
        guard result == .OK, let url = panel.url else { return }
        AuthorizedCapture.perform(
          authorize: { self.validateSharing(context, completion: $0) }
        ) {
          self.readSharedFile(url, context: context)
        }
      }
    }
  }

  private func readSharedFile(_ url: URL, context: [String: Any]) {
    do {
      let handle = try FileHandle(forReadingFrom: url)
      defer {
        do { try handle.close() } catch {
          alert("Could not close the selected file", error.localizedDescription)
        }
      }
      let bytes = try handle.read(upToCount: 12 * 1024 * 1024 + 1) ?? Data()
      guard !bytes.isEmpty && bytes.count <= 12 * 1024 * 1024 else {
        alert("This file is too large or empty", "Choose a nonempty file up to 12 MiB.")
        return
      }
      deliver(
        "shareFile",
        value: ["name": url.lastPathComponent, "base64": bytes.base64EncodedString()],
        context: context)
    } catch {
      alert("Could not read the selected file", error.localizedDescription)
    }
  }

  private func deliver(_ method: String, value: Any, context: [String: Any]) {
    guard ["shareText", "shareFile"].contains(method) else { return }
    webView.callAsyncJavaScript(
      "return await window.lumenMac.\(method)(payload, context)",
      arguments: ["payload": value, "context": context], in: nil, in: .page
    ) { result in
      switch result {
      case .failure(let error):
        self.alert("Sharing failed", error.localizedDescription)
      case .success(let value):
        if value as? Bool != true {
          self.alert(
            "Content was not shared", "Unlock Lumen and try again. Nothing was sent to AI.")
        }
      }
    }
  }

  @objc private func toggleVoiceCapture() {
    if voice.state == .recording {
      voice.stop()
      return
    }
    if voiceIdentifier != nil {
      cancelVoiceCapture()
      return
    }
    showWindow()
    let identifier = UUID().uuidString
    voiceIdentifier = identifier
    webView.callAsyncJavaScript(
      "return await window.lumenMac.prepareVoiceCapture(identifier)",
      arguments: ["identifier": identifier], in: nil, in: .page
    ) { result in
      guard self.voiceIdentifier == identifier else { return }
      switch result {
      case .success(let value):
        if let reason = (value as? [String: Any])?["reason"] as? String {
          self.cancelVoiceCapture()
          self.alert("Cannot speak yet", reason)
          return
        }
        guard let context = value as? [String: Any],
          context["identifier"] as? String == identifier,
          context["epoch"] is Int, context["vault_generation"] is Int,
          let mode = context["mode"] as? String,
          ["ask", "note", "reminder", "draft"].contains(mode)
        else {
          self.cancelVoiceCapture()
          self.alert(
            "Unlock before speaking",
            "Unlock your vault, then choose Speak to Lumen again. The microphone has not been started."
          )
          return
        }
        self.voiceContext = context
        self.presentVoiceSheet()
        self.voice.start()
      case .failure(let error):
        self.cancelVoiceCapture()
        self.alert("Voice capture could not start", error.localizedDescription)
      }
    }
  }

  private func presentVoiceSheet() {
    let sheet = NSWindow(
      contentRect: NSRect(x: 0, y: 0, width: 520, height: 540),
      styleMask: [.titled], backing: .buffered, defer: false
    )
    sheet.title = "Speak to Lumen"
    let title = NSTextField(labelWithString: "Speak, then review.")
    title.font = .systemFont(ofSize: 19, weight: .semibold)
    let status = NSTextField(
      wrappingLabelWithString: "Waiting for macOS permission. Recording has not started.")
    status.font = .systemFont(ofSize: 12)
    voiceStatus = status
    let input = NSTextField(wrappingLabelWithString: "Input: waiting for microphone permission.")
    input.font = .systemFont(ofSize: 11)
    voiceInput = input
    let level = NSLevelIndicator()
    level.levelIndicatorStyle = .continuousCapacity
    level.minValue = 0
    level.maxValue = 1
    level.isEditable = false
    voiceLevel = level
    let privacy = NSTextField(
      wrappingLabelWithString:
        "On-device only. Up to 60 seconds. No audio file is saved. Your transcript is never sent automatically."
    )
    privacy.font = .systemFont(ofSize: 11)
    privacy.textColor = .secondaryLabelColor
    let scroll = NSScrollView()
    scroll.hasVerticalScroller = true
    scroll.borderType = .bezelBorder
    let text = NSTextView(frame: NSRect(x: 0, y: 0, width: 440, height: 100))
    text.isEditable = false
    text.isSelectable = true
    text.font = .systemFont(ofSize: 13)
    text.textContainerInset = NSSize(width: 8, height: 8)
    text.isVerticallyResizable = true
    text.isHorizontallyResizable = false
    text.autoresizingMask = [.width]
    text.textContainer?.containerSize = NSSize(width: 440, height: CGFloat.greatestFiniteMagnitude)
    text.textContainer?.widthTracksTextView = true
    scroll.documentView = text
    voiceText = text
    let stop = NSButton(title: "Stop & review", target: self, action: #selector(stopVoiceCapture))
    stop.bezelStyle = .rounded
    stop.keyEquivalent = "\r"
    stop.isEnabled = false
    voiceStop = stop
    let cancel = NSButton(title: "Cancel", target: self, action: #selector(cancelVoiceCapture))
    cancel.bezelStyle = .rounded
    cancel.keyEquivalent = "\u{1b}"
    let copy = NSButton(
      title: "Copy partial text", target: self, action: #selector(copyVoiceTranscript))
    copy.bezelStyle = .rounded
    copy.isHidden = true
    voiceCopy = copy
    let review = NSButton(
      title: "Review partial text", target: self, action: #selector(reviewPartialVoiceTranscript))
    review.bezelStyle = .rounded
    review.isHidden = true
    voiceReview = review
    let recovery = NSStackView(views: [copy, review])
    recovery.orientation = .horizontal
    recovery.spacing = 8
    let buttons = NSStackView(views: [cancel, stop])
    buttons.orientation = .horizontal
    buttons.spacing = 8
    let stack = NSStackView(views: [
      title, status, input, level, privacy, scroll, recovery, buttons,
    ])
    stack.orientation = .vertical
    stack.alignment = .leading
    stack.spacing = 12
    stack.translatesAutoresizingMaskIntoConstraints = false
    let content = sheet.contentView!
    content.addSubview(stack)
    NSLayoutConstraint.activate([
      stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 20),
      stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -20),
      stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 20),
      stack.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -20),
      scroll.widthAnchor.constraint(equalTo: stack.widthAnchor),
      scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 80),
      status.widthAnchor.constraint(equalTo: stack.widthAnchor),
      privacy.widthAnchor.constraint(equalTo: stack.widthAnchor),
      input.widthAnchor.constraint(equalTo: stack.widthAnchor),
      level.widthAnchor.constraint(equalTo: stack.widthAnchor),
      level.heightAnchor.constraint(equalToConstant: 12),
    ])
    voiceSheet = sheet
    window.beginSheet(sheet)
  }

  private func updateVoiceState(_ state: VoiceCapture.State) {
    let recording = state == .recording
    statusItem.button?.image = NSImage(
      systemSymbolName: recording ? "mic.fill" : "sparkle",
      accessibilityDescription: recording ? "Lumen microphone recording" : "Lumen"
    )
    statusItem.button?.contentTintColor = recording ? .systemRed : nil
    voiceStop?.isEnabled = recording
    cancelVoiceMenu.isHidden = voiceIdentifier == nil
    switch state {
    case .authorizing:
      voiceMenu.title = "Cancel voice setup"
      voiceStatus?.stringValue = "Waiting for microphone and speech permission. No recording yet."
    case .recording:
      voiceInput?.stringValue = "Input: \(voice.inputName). Waiting for audio..."
      voiceMenu.title = "Stop speaking & review    \(voiceShortcutLabel)"
      voiceStatus?.stringValue =
        "Microphone on. Speak now; press Stop & review or hold . and press Enter in Lumen when finished."
    case .finishing:
      voiceLevel?.doubleValue = 0
      voiceMenu.title = "Cancel transcription    \(voiceShortcutLabel)"
      voiceStatus?.stringValue = "Microphone off. Finishing your on-device transcript..."
    case .idle:
      voiceLevel?.doubleValue = 0
      voiceMenu.title = "Speak to Lumen    \(voiceShortcutLabel)"
    }
  }

  @objc private func stopVoiceCapture() { voice.stop() }

  private func insertVoiceTranscript(_ text: String, partial: Bool = false) {
    guard let identifier = voiceIdentifier, let context = voiceContext else { return }
    var payload = context
    payload["text"] = text
    payload["partial"] = partial
    voiceReview?.isEnabled = false
    voiceStatus?.stringValue = "Microphone off. Placing the transcript in chat for your review..."
    webView.callAsyncJavaScript(
      "return await window.lumenMac.acceptVoiceTranscript(payload)",
      arguments: ["payload": payload], in: nil, in: .page
    ) { result in
      guard self.voiceIdentifier == identifier else { return }
      switch result {
      case .success(let value):
        if let receipt = value as? [String: Any], receipt["accepted"] as? Bool == true {
          self.cancelVoiceCapture()
          self.showWindow()
        } else {
          let reason =
            (value as? [String: Any])?["reason"] as? String
            ?? "The vault or voice session changed. Existing typed text was not replaced."
          self.voiceFailure(reason)
        }
      case .failure(let error):
        self.voiceFailure("The transcript was not inserted: \(error.localizedDescription)")
      }
    }
  }

  private func voiceFailure(_ message: String) {
    let hasText = voiceText?.string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false
    voiceStatus?.stringValue =
      message
      + (hasText
        ? " Choose Review partial text to keep the possibly incomplete words in chat for editing."
        : "")
    voiceStop?.isEnabled = false
    voiceCopy?.isHidden = !hasText
    voiceReview?.isHidden = !hasText
    voiceReview?.isEnabled = true
    updateVoiceState(.idle)
    voiceMenu.title = "Dismiss voice window    \(voiceShortcutLabel)"
  }

  @objc private func reviewPartialVoiceTranscript() {
    guard voice.state == .idle, voiceReview?.isEnabled == true,
      let text = voiceText?.string, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    else { return }
    insertVoiceTranscript(text, partial: true)
  }

  @objc private func copyVoiceTranscript() {
    guard let text = voiceText?.string, !text.isEmpty else { return }
    NSPasteboard.general.clearContents()
    guard NSPasteboard.general.setString(text, forType: .string) else {
      voiceFailure("The partial transcript could not be copied to the system clipboard.")
      return
    }
    voiceStatus?.stringValue =
      "Copied to your system clipboard. Other apps or clipboard synchronization may access it."
  }

  @objc private func cancelVoiceCapture() {
    voiceIdentifier = nil
    voiceContext = nil
    voice.cancel()
    webView?.evaluateJavaScript("window.lumenMac?.cancelVoiceCapture(); undefined")
    if let sheet = voiceSheet {
      window.endSheet(sheet)
      sheet.orderOut(nil)
    }
    voiceText?.string = ""
    voiceSheet = nil
    voiceStatus = nil
    voiceText = nil
    voiceStop = nil
    voiceCopy = nil
    voiceReview = nil
    voiceLevel = nil
    voiceInput = nil
    cancelVoiceMenu?.isHidden = true
  }

  @objc private func openOllama() {
    guard
      let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.electron.ollama")
    else {
      alert(
        "Ollama is not installed",
        "Install the Ollama Mac app, download a local model, then choose Set up local AI in Lumen. Lumen does not download anything automatically."
      )
      return
    }
    NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration()) {
      _, error in
      if let error = error {
        DispatchQueue.main.async { self.alert("Could not open Ollama", error.localizedDescription) }
      }
    }
  }

  private func updateLoginStatus() {
    loginItem.state = SMAppService.mainApp.status == .enabled ? .on : .off
    if SMAppService.mainApp.status == .requiresApproval {
      loginItem.title = "Approve start at login..."
    } else {
      loginItem.title = "Start at login"
    }
  }

  @objc private func toggleLogin() {
    if SMAppService.mainApp.status == .requiresApproval {
      SMAppService.openSystemSettingsLoginItems()
      return
    }
    do {
      if SMAppService.mainApp.status == .enabled {
        try SMAppService.mainApp.unregister()
      } else {
        try SMAppService.mainApp.register()
      }
      updateLoginStatus()
      if SMAppService.mainApp.status == .requiresApproval {
        alert(
          "Approve Lumen in Login Items",
          "macOS needs your approval. Enable Lumen under System Settings > General > Login Items.")
        SMAppService.openSystemSettingsLoginItems()
      }
    } catch { alert("Could not change login startup", error.localizedDescription) }
  }

  @objc private func restartBackend() {
    guard backend?.isRunning != true else {
      alert(
        "The local service is running",
        "Quit and reopen Lumen to restart it. This locks the vault and discards any unfinished work."
      )
      return
    }
    automaticRestarts = 0
    startBackend()
  }

  private func startBackend() {
    voiceShortcutEnabled = false
    voiceShortcut.reset(forwardPending: false)
    guard let runtime = Bundle.main.infoDictionary,
      let python = runtime["LumenPythonPath"] as? String,
      let project = runtime["LumenProjectPath"] as? String
    else {
      alert(
        "Lumen installation is incomplete", "Rebuild the Mac app with scripts/install_macos.py.")
      return
    }
    outputBuffer = Data()
    errorBuffer = Data()
    backendURL = nil
    webView.loadHTMLString(
      "<html><body style='font:16px -apple-system;padding:50px;color:#2d5c48'><h2>Starting Lumen...</h2><p>Your private workspace will be ready in a moment.</p></body></html>",
      baseURL: nil)
    let process = Process()
    process.executableURL = URL(fileURLWithPath: python)
    process.currentDirectoryURL = URL(fileURLWithPath: project)
    process.arguments = ["-m", "lumen.desktop_server"]
    if smokeTest,
      let testDirectory = ProcessInfo.processInfo.environment["LUMEN_SELF_TEST_DATA_DIR"]
    {
      process.arguments! += ["--data-dir", testDirectory]
    }
    var environment = ProcessInfo.processInfo.environment
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.removeValue(forKey: "PYTHONPATH")
    environment.removeValue(forKey: "PYTHONHOME")
    process.environment = environment
    let output = Pipe()
    let errors = Pipe()
    outputPipe = output
    errorPipe = errors
    process.standardOutput = output
    process.standardError = errors
    output.fileHandleForReading.readabilityHandler = { handle in
      let bytes = handle.availableData
      if bytes.isEmpty {
        handle.readabilityHandler = nil
        return
      }
      DispatchQueue.main.async { self.consumeOutput(bytes) }
    }
    errors.fileHandleForReading.readabilityHandler = { handle in
      let bytes = handle.availableData
      if bytes.isEmpty {
        handle.readabilityHandler = nil
        return
      }
      DispatchQueue.main.async { self.errorBuffer = Data((self.errorBuffer + bytes).suffix(8000)) }
    }
    process.terminationHandler = { ended in
      DispatchQueue.main.async {
        guard !self.quitting else { return }
        self.cancelVoiceCapture()
        self.backendURL = nil
        if self.smokeTest {
          self.finishSmokeTest(["error": "Backend exited with status \(ended.terminationStatus)."])
        } else if self.automaticRestarts < 1 {
          self.automaticRestarts += 1
          self.startBackend()
        } else {
          let details = String(data: self.errorBuffer, encoding: .utf8) ?? "No error details."
          self.alert(
            "The local service stopped",
            "Use Restart local service after fixing the problem.\n\n\(details)")
        }
      }
    }
    backend = process
    do { try process.run() } catch {
      alert(
        "Could not start the local service",
        "Keep the project folder and its .venv in place.\n\n\(error.localizedDescription)")
    }
  }

  private func consumeOutput(_ bytes: Data) {
    outputBuffer.append(bytes)
    guard outputBuffer.count <= 4096 else {
      alert("Unexpected startup response", "The backend did not return a valid startup address.")
      outputPipe?.fileHandleForReading.readabilityHandler = nil
      return
    }
    guard let newline = outputBuffer.firstIndex(of: 10) else { return }
    let line = String(data: outputBuffer[..<newline], encoding: .utf8) ?? ""
    outputBuffer.removeSubrange(...newline)
    guard line.hasPrefix("LUMEN_READY:"),
      let port = Int(line.dropFirst("LUMEN_READY:".count)),
      (1024...65535).contains(port),
      let url = URL(string: "http://127.0.0.1:\(port)/?desktop=1")
    else {
      alert("Invalid backend startup address", "Lumen only accepts an owned loopback service.")
      return
    }
    backendURL = url
    webView.load(URLRequest(url: url))
  }

  private func isLocal(_ url: URL) -> Bool {
    guard let base = backendURL else { return false }
    return url.scheme == "http" && url.host == "127.0.0.1" && url.port == base.port
  }

  func webView(
    _ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
    decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
  ) {
    guard let url = action.request.url else {
      decisionHandler(.cancel)
      return
    }
    if isLocal(url) || (url.absoluteString == "about:blank" && backendURL == nil) {
      decisionHandler(.allow)
    } else {
      decisionHandler(.cancel)
      if action.navigationType == .linkActivated && ["https", "http"].contains(url.scheme ?? "") {
        NSWorkspace.shared.open(url)
      }
    }
  }

  func webView(
    _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
    for action: WKNavigationAction, windowFeatures: WKWindowFeatures
  ) -> WKWebView? {
    if action.navigationType == .linkActivated, let url = action.request.url,
      ["https", "http"].contains(url.scheme ?? ""), !isLocal(url)
    {
      NSWorkspace.shared.open(url)
    }
    return nil
  }

  func webView(
    _ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
    initiatedByFrame frame: WKFrameInfo,
    completionHandler: @escaping ([URL]?) -> Void
  ) {
    guard let url = frame.request.url, isLocal(url) else {
      completionHandler(nil)
      return
    }
    let panel = NSOpenPanel()
    panel.canChooseDirectories = false
    panel.allowsMultipleSelection = false
    panel.allowedContentTypes = ["pdf", "docx", "txt", "md"].compactMap {
      UTType(filenameExtension: $0)
    }
    panel.beginSheetModal(for: window) { result in
      completionHandler(result == .OK ? panel.urls : nil)
    }
  }

  func userContentController(
    _ controller: WKUserContentController, didReceive message: WKScriptMessage
  ) {
    guard message.frameInfo.isMainFrame, let url = message.frameInfo.request.url, isLocal(url),
      let payload = message.body as? [String: String]
    else { return }
    switch payload["action"] {
    case "voiceShortcutAvailability":
      guard let enabled = payload["enabled"], ["true", "false"].contains(enabled) else {
        alert("Invalid shortcut state", "The voice shortcut state could not be updated.")
        return
      }
      voiceShortcutEnabled = enabled == "true"
      if !voiceShortcutEnabled { voiceShortcut.reset(forwardPending: false) }
    case "shareClipboard":
      let mode = payload["mode"] ?? "ask"
      guard ["ask", "note", "reminder", "draft"].contains(mode) else {
        alert("Unsupported sharing mode", "Choose one of Lumen's chat actions.")
        return
      }
      copyClipboard(mode: mode)
    case "openOllama": openOllama()
    case "speak": toggleVoiceCapture()
    case "cancelVoice": cancelVoiceCapture()
    default: alert("Unsupported Mac action", "This action is not available.")
    }
  }

  func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
    guard smokeTest, let url = webView.url, isLocal(url) else { return }
    DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
      self.webView.evaluateJavaScript(
        "({compact:document.body.classList.contains('compact'),bridge:!!window.lumenMac,chat:!document.getElementById('page-assistant').hidden,locked:!window.lumenMac.canShare()})"
      ) { result, error in
        guard error == nil, let values = result as? [String: Bool] else {
          self.finishSmokeTest([
            "error": error?.localizedDescription ?? "Web UI did not initialize."
          ])
          return
        }
        self.window.performClose(nil)
        let survived = self.backend?.isRunning == true && !self.window.isVisible
        self.showWindow()
        self.finishSmokeTest([
          "compact_chat": values["compact"] == true && values["chat"] == true,
          "mac_bridge": values["bridge"] == true,
          "session_locked": values["locked"] == true,
          "close_keeps_running": survived,
          "hotkey_registered": self.hotKey != nil,
          "voice_local_chord_registered": self.voiceKeyMonitor != nil,
          "voice_shortcut_enabled_while_locked": self.voiceShortcutEnabled,
          "voice_menu_available": self.voiceMenu != nil,
          "on_device_only": VoiceCapture.localRequest().requiresOnDeviceRecognition,
          "microphone_off_on_startup": !self.voice.microphoneRunning && self.voice.state == .idle,
          "loopback_port": self.backendURL?.port ?? 0,
        ])
      }
    }
  }

  private func finishSmokeTest(_ report: [String: Any]) {
    guard !quitting else { return }
    if let destination = ProcessInfo.processInfo.environment["LUMEN_SELF_TEST_REPORT"] {
      do {
        let bytes = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
        try bytes.write(to: URL(fileURLWithPath: destination), options: .atomic)
      } catch { fputs("Could not write native smoke report: \(error)\n", stderr) }
    }
    quit()
  }

  private func alert(_ title: String, _ detail: String) {
    if smokeTest {
      finishSmokeTest(["error": "\(title): \(detail)"])
      return
    }
    let alert = NSAlert()
    alert.messageText = title
    alert.informativeText = detail
    alert.addButton(withTitle: "OK")
    alert.runModal()
  }

  @objc private func quit() { NSApp.terminate(nil) }

  func applicationWillTerminate(_ notification: Notification) {
    quitting = true
    cancelVoiceCapture()
    if let hotKey = hotKey { UnregisterEventHotKey(hotKey) }
    voiceShortcut.reset(forwardPending: false)
    if let monitor = voiceKeyMonitor { NSEvent.removeMonitor(monitor) }
    if let eventHandler = eventHandler { RemoveEventHandler(eventHandler) }
    outputPipe?.fileHandleForReading.readabilityHandler = nil
    errorPipe?.fileHandleForReading.readabilityHandler = nil
    if let backend = backend, backend.isRunning { backend.terminate() }
  }
}

@main
struct LumenApplication {
  static func main() {
    let delegate = LumenDelegate()
    let app = NSApplication.shared
    app.delegate = delegate
    app.run()
  }
}
