import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("xcrun") is None,
    reason="Requires the Swift compiler; fake authorization/content providers only.",
)


def test_native_capture_waits_for_current_authorization(tmp_path):
    source = tmp_path / "CaptureChecks.swift"
    source.write_text(
        """
@main struct CaptureChecks {
  static func main() {
    var reads = 0
    var complete: ((Bool) -> Void)?
    let authorize: (@escaping (Bool) -> Void) -> Void = { complete = $0 }
    let read = { reads += 1 }
    AuthorizedCapture.perform(authorize: authorize, capture: read)
    assert(reads == 0)
    complete?(false)
    assert(reads == 0)
    AuthorizedCapture.perform(authorize: authorize, capture: read)
    let originalGeneration = 1
    let currentGeneration = 2
    complete?(originalGeneration == currentGeneration)
    assert(reads == 0)
    AuthorizedCapture.perform(authorize: authorize, capture: read)
    assert(reads == 0)
    complete?(true)
    assert(reads == 1)
    print("Authorization checked before capture; only synthetic providers used")
  }
}
""",
        encoding="utf-8",
    )
    executable = tmp_path / "capture-checks"
    subprocess.run(
        [
            "xcrun", "swiftc", "-parse-as-library",
            str(Path(__file__).resolve().parents[1] / "native" / "AuthorizedCapture.swift"),
            str(source), "-o", str(executable),
        ],
        check=True, capture_output=True, text=True, timeout=60,
    )
    result = subprocess.run(
        [str(executable)], check=True, capture_output=True, text=True, timeout=10,
    )
    assert "only synthetic providers used" in result.stdout
