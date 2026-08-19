"""Run the internal gateway API and external read-only status API."""
import signal
import subprocess
import sys
import time

from . import config


def main() -> int:
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "ha_didcomm.main:app",
                "--host",
                config.GATEWAY_HOST,
                "--port",
                str(config.GATEWAY_PORT),
            ]
        ),
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "ha_didcomm.status:app",
                "--host",
                config.STATUS_HOST,
                "--port",
                str(config.STATUS_PORT),
            ]
        ),
    ]

    def stop_processes(*_):
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop_processes)
    signal.signal(signal.SIGINT, stop_processes)
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        return next(
            (process.returncode for process in processes if process.returncode),
            0,
        )
    finally:
        stop_processes()


if __name__ == "__main__":
    raise SystemExit(main())
