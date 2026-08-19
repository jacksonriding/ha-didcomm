"""Process supervisor for the Home Assistant app image."""
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

DATA_DIR = Path("/data")
ADMIN_URL = "http://127.0.0.1:8021"


def load_options(path: Path = DATA_DIR / "options.json") -> dict:
    with path.open(encoding="utf-8-sig") as options_file:
        return json.load(options_file)


def persistent_secret(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(32)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return value


def wait_for_admin(process: subprocess.Popen, attempts: int = 60) -> None:
    for _ in range(attempts):
        if process.poll() is not None:
            raise RuntimeError("ACA-Py exited before its Admin API became ready")
        try:
            with urlopen(f"{ADMIN_URL}/status/live", timeout=1):
                return
        except URLError:
            time.sleep(0.5)
    raise RuntimeError("ACA-Py Admin API did not become ready")


def issuer_did(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    body = json.dumps(
        {"method": "key", "options": {"key_type": "ed25519"}}
    ).encode()
    request = Request(
        f"{ADMIN_URL}/wallet/did/create",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        did = json.load(response)["result"]["did"]
    path.write_text(did, encoding="utf-8")
    return did


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    options = load_options()
    log_level = options.get("log_level", "info")
    wallet_key = persistent_secret(DATA_DIR / "wallet-key")
    acapy_command = [
        "aca-py", "start", "--label", "ha-didcomm", "--inbound-transport",
        "http", "0.0.0.0", "8000", "--outbound-transport", "http", "--admin",
        "127.0.0.1", "8021", "--admin-insecure-mode", "--webhook-url",
        "http://127.0.0.1:8080", "--endpoint", options["public_endpoint"],
        "--no-ledger", "--wallet-type", "askar", "--wallet-name", "home",
        "--wallet-key", wallet_key, "--auto-provision", "--log-level", log_level,
    ]
    acapy_environment = os.environ.copy()
    acapy_environment["ACAPY_HOME"] = str(DATA_DIR / "acapy")
    acapy_process = subprocess.Popen(acapy_command, env=acapy_environment)
    gateway_process = None

    def stop_processes(*_):
        for process in (gateway_process, acapy_process):
            if process and process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop_processes)
    signal.signal(signal.SIGINT, stop_processes)
    try:
        wait_for_admin(acapy_process)
        environment = os.environ.copy()
        environment.update(
            {
                "ACAPY_ADMIN_URL": ADMIN_URL,
                "CREDENTIAL_STORE_PATH": str(DATA_DIR / "credentials.sqlite3"),
                "HOME_ID": options.get("home_id", "home"),
                "HOME_ISSUER_DID": issuer_did(DATA_DIR / "issuer-did"),
            }
        )
        gateway_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "ha_didcomm.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8080",
            ],
            env=environment,
        )
        while acapy_process.poll() is None and gateway_process.poll() is None:
            time.sleep(0.5)
        return acapy_process.returncode or gateway_process.returncode or 0
    finally:
        stop_processes()


if __name__ == "__main__":
    raise SystemExit(main())
