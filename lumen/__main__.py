import argparse
from pathlib import Path

import uvicorn

from lumen.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Lumen on this computer only.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".lumen")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535.")
    uvicorn.run(
        create_app(args.data_dir, args.port),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
