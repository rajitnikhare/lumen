enum AuthorizedCapture {
  static func perform(
    authorize: (@escaping (Bool) -> Void) -> Void,
    capture: @escaping () -> Void
  ) {
    authorize { isAuthorized in
      guard isAuthorized else { return }
      capture()
    }
  }
}
