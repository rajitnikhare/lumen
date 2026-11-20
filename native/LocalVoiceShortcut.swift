import AppKit
import Carbon

final class LocalVoiceShortcut {
  var onActivate: () -> Void
  private let forward: (NSEvent) -> Void
  private var pendingPeriod: NSEvent?
  private var periodKey: UInt16?
  private var usedChord = false
  private var consumedEnters = Set<UInt16>()
  private var forwarding = false

  init(onActivate: @escaping () -> Void, forward: @escaping (NSEvent) -> Void) {
    self.onActivate = onActivate
    self.forward = forward
  }

  func handle(_ event: NSEvent) -> NSEvent? {
    if forwarding { return event }
    if event.type == .keyUp {
      if consumedEnters.remove(event.keyCode) != nil { return nil }
      if event.keyCode == periodKey {
        let consumed = usedChord
        flushPeriod()
        periodKey = nil
        usedChord = false
        return consumed ? nil : event
      }
      return event
    }
    guard event.type == .keyDown else { return event }
    if consumedEnters.contains(event.keyCode) { return nil }
    let modifiers: NSEvent.ModifierFlags = [.command, .control, .option, .shift, .function]
    let unmodified = event.modifierFlags.intersection(modifiers).isEmpty
    if unmodified && event.characters == "." {
      if event.isARepeat {
        if usedChord { return nil }
        flushPeriod()
        periodKey = nil
        return event
      }
      flushPeriod()
      periodKey = event.keyCode
      pendingPeriod = event
      usedChord = false
      return nil
    }
    if unmodified, pendingPeriod != nil,
      event.keyCode == UInt16(kVK_Return) || event.keyCode == UInt16(kVK_ANSI_KeypadEnter)
    {
      pendingPeriod = nil
      usedChord = true
      consumedEnters.insert(event.keyCode)
      onActivate()
      return nil
    }
    flushPeriod()
    periodKey = nil
    usedChord = false
    return event
  }

  private func flushPeriod() {
    guard let event = pendingPeriod else { return }
    pendingPeriod = nil
    forwarding = true
    forward(event)
    forwarding = false
  }

  func reset(forwardPending: Bool = true) {
    let event = pendingPeriod
    if forwardPending { flushPeriod() } else { pendingPeriod = nil }
    if forwardPending, let event = event,
      let release = NSEvent.keyEvent(
        with: .keyUp, location: event.locationInWindow, modifierFlags: event.modifierFlags,
        timestamp: event.timestamp, windowNumber: event.windowNumber, context: nil,
        characters: ".", charactersIgnoringModifiers: ".", isARepeat: false, keyCode: event.keyCode)
    {
      forwarding = true
      forward(release)
      forwarding = false
    }
    periodKey = nil
    usedChord = false
    consumedEnters.removeAll()
  }
}
