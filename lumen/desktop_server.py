"""A backend owned by one native app process, on an OS-assigned loopback port."""

import argparse
import os
import socket
import threading
from pathlib import Path

import uvicorn

from lumen.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".lumen")
    args = parser.parse_args()
    parent = os.getppid()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        app = create_app(args.data_dir, port)
        server = uvicorn.Server(
            uvicorn.Config(app, access_log=False, log_level="error", timeout_graceful_shutdown=5)
        )
        done = threading.Event()

        def watch_parent() -> None:
            while not done.wait(2):
                if os.getppid() != parent:
                    server.should_exit = True
                    return

        def announce() -> None:
            while not done.wait(0.05):
                if server.started:
                    print(f"LUMEN_READY:{port}", flush=True)
                    return
                if server.should_exit:
                    return

        monitor = threading.Thread(target=watch_parent, daemon=True)
        ready = threading.Thread(target=announce, daemon=True)
        monitor.start()
        ready.start()
        try:
            server.run(sockets=[listener])
        finally:
            done.set()
            monitor.join(timeout=3)
            ready.join(timeout=1)


if __name__ == "__main__":
    main()
