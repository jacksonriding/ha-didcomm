"""Process supervisor for the Home Assistant app image."""
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DATA_DIR = Path("/data")
ADMIN_URL = "http://127.0.0.1:8021"
NGINX_CONFIG_PATH = DATA_DIR / "nginx.conf"


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


def tls_file(filename: str, directory: Path = Path("/ssl")) -> Path:
    """Resolve a Supervisor SSL filename without allowing path traversal."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", filename):
        raise ValueError("TLS certificate and key options must be filenames")
    path = directory / filename
    if not path.is_file():
        raise FileNotFoundError(f"TLS file does not exist: {path}")
    return path


def write_nginx_config(certfile: Path, keyfile: Path, path: Path) -> None:
    """Write the TLS proxy configuration used by the bundled app."""
    path.write_text(
        f"""pid /data/nginx.pid;
error_log /dev/stderr warn;
events {{}}
http {{
    access_log /dev/stdout;
    server_tokens off;
    server {{
        listen 8443 ssl;
        ssl_certificate {certfile};
        ssl_certificate_key {keyfile};
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_session_cache shared:TLS:10m;
        client_max_body_size 10m;
        location = /health {{ proxy_pass http://127.0.0.1:8090/health; }}
        location = /status {{ proxy_pass http://127.0.0.1:8090/status; }}
        location / {{
            proxy_pass http://127.0.0.1:8000;
            proxy_http_version 1.1;
            proxy_request_buffering off;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto https;
        }}
    }}
}}
""",
        encoding="utf-8",
    )


def admin_request(url: str, api_key: str, **kwargs) -> Request:
    """Build an authenticated ACA-Py Admin API request."""
    headers = dict(kwargs.pop("headers", {}))
    headers["X-API-Key"] = api_key
    return Request(url, headers=headers, **kwargs)


def wait_for_admin(
    process: subprocess.Popen,
    api_key: str,
    attempts: int = 60,
) -> None:
    for _ in range(attempts):
        if process.poll() is not None:
            raise RuntimeError("ACA-Py exited before its Admin API became ready")
        try:
            request = admin_request(f"{ADMIN_URL}/status/live", api_key)
            with urlopen(request, timeout=1):
                return
        except URLError:
            time.sleep(0.5)
    raise RuntimeError("ACA-Py Admin API did not become ready")


def issuer_did(path: Path, api_key: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    body = json.dumps(
        {"method": "key", "options": {"key_type": "ed25519"}}
    ).encode()
    request = admin_request(
        f"{ADMIN_URL}/wallet/did/create",
        api_key,
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
    if urlparse(options["public_endpoint"]).scheme != "https":
        raise ValueError("public_endpoint must use HTTPS")
    log_level = options.get("log_level", "info")
    write_nginx_config(
        tls_file(options["certfile"]),
        tls_file(options["keyfile"]),
        NGINX_CONFIG_PATH,
    )
    wallet_key = persistent_secret(DATA_DIR / "wallet-key")
    admin_api_key = persistent_secret(DATA_DIR / "admin-api-key")
    acapy_command = [
        "aca-py", "start", "--label", "ha-didcomm", "--inbound-transport",
        "http", "127.0.0.1", "8000", "--outbound-transport", "http", "--admin",
        "127.0.0.1", "8021", "--webhook-url",
        "http://127.0.0.1:8080", "--endpoint", options["public_endpoint"],
        "--no-ledger", "--wallet-type", "askar", "--wallet-name", "home",
        "--wallet-key", wallet_key, "--auto-provision", "--log-level", log_level,
    ]
    acapy_environment = os.environ.copy()
    acapy_environment["ACAPY_HOME"] = str(DATA_DIR / "acapy")
    acapy_environment["ACAPY_ADMIN_API_KEY"] = admin_api_key
    acapy_process = subprocess.Popen(acapy_command, env=acapy_environment)
    gateway_process = None
    status_process = None
    nginx_process = None

    def stop_processes(*_):
        for process in (
            nginx_process,
            status_process,
            gateway_process,
            acapy_process,
        ):
            if process and process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop_processes)
    signal.signal(signal.SIGINT, stop_processes)
    try:
        wait_for_admin(acapy_process, admin_api_key)
        environment = os.environ.copy()
        environment.update(
            {
                "ACAPY_ADMIN_URL": ADMIN_URL,
                "ACAPY_ADMIN_API_KEY": admin_api_key,
                "CREDENTIAL_STORE_PATH": str(DATA_DIR / "credentials.sqlite3"),
                "HOME_ID": options.get("home_id", "home"),
                "HOME_ISSUER_DID": issuer_did(
                    DATA_DIR / "issuer-did", admin_api_key
                ),
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
        status_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "ha_didcomm.status:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8090",
            ],
            env=environment,
        )
        nginx_process = subprocess.Popen(
            ["nginx", "-c", str(NGINX_CONFIG_PATH), "-g", "daemon off;"]
        )
        while all(
            process.poll() is None
            for process in (
                acapy_process,
                gateway_process,
                status_process,
                nginx_process,
            )
        ):
            time.sleep(0.5)
        return (
            acapy_process.returncode
            or gateway_process.returncode
            or status_process.returncode
            or nginx_process.returncode
            or 0
        )
    finally:
        stop_processes()


if __name__ == "__main__":
    raise SystemExit(main())
