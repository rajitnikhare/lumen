import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("LUMEN_NATIVE_TESTS") != "1", reason="Opt-in native Mac app smoke check."
)


def test_native_window_bridge_shortcut_and_owned_backend():
    bundle = Path(os.getenv("LUMEN_NATIVE_APP", str(Path.home() / "Applications" / "Lumen.app")))
    executable = bundle / "Contents" / "MacOS" / "Lumen"
    assert executable.exists(), "Build/install the native app first."
    with tempfile.TemporaryDirectory(prefix="lumen-native-test-") as directory:
        report_path = Path(directory) / "report.json"
        env = {
            **os.environ,
            "LUMEN_SELF_TEST_REPORT": str(report_path),
            "LUMEN_SELF_TEST_DATA_DIR": str(Path(directory) / "vault"),
        }
        result = subprocess.run(
            [str(executable), "--self-test"],
            env=env,
            capture_output=True,
            timeout=40,
        )
        assert result.returncode == 0, result.stderr.decode()
        assert report_path.exists(), result.stderr.decode()
        report = json.loads(report_path.read_text())
        assert "error" not in report, report
        assert report["compact_chat"] is True
        assert report["mac_bridge"] is True
        assert report["session_locked"] is True
        assert report["close_keeps_running"] is True
        assert report["hotkey_registered"] is True
        assert report["voice_local_chord_registered"] is True
        assert report["voice_shortcut_enabled_while_locked"] is False
        assert report["voice_menu_available"] is True
        assert report["on_device_only"] is True
        assert report["microphone_off_on_startup"] is True
        assert 1024 <= report["loopback_port"] <= 65535
        with httpx.Client(trust_env=False, timeout=1) as client:
            for _ in range(50):
                try:
                    client.get(f"http://127.0.0.1:{report['loopback_port']}/api/health")
                except httpx.ConnectError:
                    break
                time.sleep(0.1)
            else:
                pytest.fail("The native app left its owned backend running after quitting.")
