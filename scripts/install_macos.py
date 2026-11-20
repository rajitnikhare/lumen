"""Build a local menu-bar .app using Apple's installed compiler; no cloud packaging."""

import argparse
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Lumen Mac menu-bar app.")
    parser.add_argument("--install", action="store_true", help="Install in ~/Applications.")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("The native app requires macOS 13 or newer.")
    project = Path(__file__).resolve().parents[1]
    python = project / ".venv" / "bin" / "python"
    if not python.is_file():
        parser.error("Install Lumen in this project's .venv first (see README).")
    destination = (Path.home() / "Applications" if args.install else project / "dist") / "Lumen.app"
    if destination.exists():
        parser.error(f"{destination} already exists. Quit and move that specific app aside first.")
    if not shutil.which("xcrun") or not shutil.which("codesign"):
        parser.error("Install Apple's Command Line Tools with xcode-select --install first.")
    destination.mkdir(parents=True, exist_ok=False)
    executable = destination / "Contents" / "MacOS" / "Lumen"
    executable.parent.mkdir(parents=True)
    metadata = {
        "CFBundleIdentifier": "com.lumen.local",
        "CFBundleName": "Lumen",
        "CFBundleDisplayName": "Lumen",
        "CFBundleExecutable": "Lumen",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "6",
        "CFBundleShortVersionString": "0.3.3",
        "LSUIElement": True,
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "Lumen records only when you choose Speak to Lumen. Audio is transcribed on this Mac; review the transcript before sending it.",
        "NSSpeechRecognitionUsageDescription": "Lumen requires on-device speech recognition to turn your explicitly recorded voice into an editable transcript. Cloud recognition is not used.",
        "NSAppTransportSecurity": {
            "NSAllowsLocalNetworking": True,
            "NSAllowsArbitraryLoadsInWebContent": True,
        },
        "LumenPythonPath": str(python),
        "LumenProjectPath": str(project),
    }
    with (destination / "Contents" / "Info.plist").open("wb") as output:
        plistlib.dump(metadata, output)
    try:
        subprocess.run(
            [
                "xcrun",
                "swiftc",
                "-swift-version",
                "5",
                "-O",
                "-parse-as-library",
                "-target",
                f"{platform.machine()}-apple-macos13.0",
                "-framework",
                "AppKit",
                "-framework",
                "WebKit",
                "-framework",
                "ServiceManagement",
                "-framework",
                "Carbon",
                "-framework",
                "AVFoundation",
                "-framework",
                "Speech",
                str(project / "native" / "Lumen.swift"),
                str(project / "native" / "VoiceCapture.swift"),
                str(project / "native" / "LocalVoiceShortcut.swift"),
                str(project / "native" / "AuthorizedCapture.swift"),
                "-o",
                str(executable),
            ],
            check=True,
        )
        subprocess.run(
            [
                "codesign",
                "--force",
                "--sign",
                "-",
                "--entitlements",
                str(project / "native" / "Lumen.entitlements"),
                str(destination),
            ],
            check=True,
        )
    except subprocess.CalledProcessError:
        shutil.rmtree(destination)
        raise
    print(f"Built {destination}")
    print(f'Open with: open "{destination}"')
    print("Enable Start at login in Lumen's menu if you want automatic startup.")


if __name__ == "__main__":
    main()
