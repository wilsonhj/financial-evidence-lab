"""Control only an owned local acceptance API for real outage/recovery tests.

No platform service identifiers or external commands are accepted. Hosted mode
requires explicit opt-in and keeps the supervisor alive for SSH restoration.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess  # nosec B404 — bounded acceptance subprocesses, no shell
import sys
import tempfile
import time
from pathlib import Path


def write_control(path: Path, action: str) -> None:
    """Readers see the previous or next complete command, never truncation."""
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(action)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("serve", "stop", "start"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dedicated-target", required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if (
        not args.dedicated_target
        or os.environ.get("FEL_READER_SMOKE_TARGET") != args.dedicated_target
        or manifest["target"] != args.dedicated_target
    ):
        raise ValueError("Local service control requires the matching dedicated local target")
    hosted = os.environ.get("FEL_READER_SMOKE_SERVICE_HOSTED") == "1"
    host = "0.0.0.0" if hosted else "127.0.0.1"  # nosec B104 — explicit hosted API binding
    port = os.environ.get("PORT", "8218") if hosted else "8218"
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("Invalid dedicated API port")
    control = args.manifest.with_suffix(".api-control")
    if args.action != "serve":
        if not control.is_file():
            raise ValueError("Owned local service controller is not running")
        write_control(control, args.action)
        return

    def terminate(_signum: int, _frame: object) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    if control.exists():
        raise ValueError("Refusing an existing service control file")
    write_control(control, "start")
    child: subprocess.Popen[bytes] | None = None
    stopped_at: float | None = None
    try:
        while True:
            action = control.read_text()
            if stopped_at is not None and time.monotonic() - stopped_at >= 60:
                write_control(control, "start")
                action = "start"
            if action not in {"start", "stop"}:
                raise ValueError("Invalid service control action")
            if action == "stop" and child is not None:
                child.terminate()
                child.wait(timeout=20)
                child = None
                stopped_at = time.monotonic()
            elif action == "start" and child is None:
                stopped_at = None
                child = (
                    subprocess.Popen(  # nosec B603 — fixed Uvicorn module, validated port, no shell
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "app.main:app",
                            "--host",
                            host,
                            "--port",
                            port,
                        ]
                    )
                )
            elif child is not None and child.poll() is not None:
                raise RuntimeError("Owned API exited unexpectedly")
            time.sleep(0.1)
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=20)
        control.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
