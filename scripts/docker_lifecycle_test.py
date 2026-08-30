#!/usr/bin/env python3
"""Validate standalone fresh install, replacement, backup, and restore."""

from __future__ import annotations

import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "compose.standalone.yml"
HELPER_IMAGE = "python:3.14-slim"
CREDENTIAL_EXCHANGE_ID = "lifecycle-exchange"


class LifecycleFailure(RuntimeError):
    """A deployment lifecycle assertion failed."""


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    allow_error: bool = False,
) -> subprocess.CompletedProcess:
    """Run a command and surface useful failure output."""
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode and not allow_error:
        detail = "\n".join(part for part in (result.stdout, result.stderr) if part)
        raise LifecycleFailure(
            f"command failed ({result.returncode}): {' '.join(command)}\n{detail}"
        )
    return result


def free_port() -> int:
    """Reserve an available loopback port for the TLS proxy."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def write_environment(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    bearer_token: str | None = None,
) -> dict:
    headers = {"Content-Type": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    payload = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=payload, headers=headers, method=method)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with urlopen(request, timeout=15, context=context) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise LifecycleFailure(f"expected a JSON object from {url}")
    return result


def wait_for_json(
    url: str, *, bearer_token: str | None = None, timeout: float = 90
) -> dict:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return request_json(url, bearer_token=bearer_token)
        except (OSError, URLError, ValueError) as error:
            last_error = error
            time.sleep(1)
    raise LifecycleFailure(f"timed out waiting for {url}: {last_error}")


def generate_certificate(directory: Path) -> tuple[Path, Path]:
    certificate = directory / "certificate.pem"
    private_key = directory / "private-key.pem"
    run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=localhost",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
        ]
    )
    return certificate, private_key


def create_issuer(compose: list[str], environment: dict[str, str]) -> str:
    code = (
        "import json,os; from urllib.request import Request,urlopen; "
        "payload=json.dumps({'method':'key','options':"
        "{'key_type':'ed25519'}}).encode(); "
        "request=Request('http://127.0.0.1:8021/wallet/did/create',"
        "data=payload,headers={'Content-Type':'application/json',"
        "'X-API-Key':os.environ['ACAPY_ADMIN_API_KEY']},method='POST'); "
        "print(json.load(urlopen(request))['result']['did'])"
    )
    result = run(
        [*compose, "exec", "-T", "acapy", "python", "-c", code],
        env=environment,
    )
    issuer = result.stdout.strip().splitlines()[-1]
    if not issuer.startswith("did:key:"):
        raise LifecycleFailure(f"ACA-Py returned an invalid issuer DID: {issuer}")
    return issuer


def wallet_dids(compose: list[str], environment: dict[str, str]) -> set[str]:
    code = (
        "import json,os; from urllib.request import Request,urlopen; "
        "request=Request('http://127.0.0.1:8021/wallet/did',"
        "headers={'X-API-Key':os.environ['ACAPY_ADMIN_API_KEY']}); "
        "print(json.dumps(json.load(urlopen(request))))"
    )
    result = run(
        [*compose, "exec", "-T", "acapy", "python", "-c", code],
        env=environment,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    return {
        record["did"]
        for record in payload.get("results", [])
        if isinstance(record, dict) and isinstance(record.get("did"), str)
    }


def seed_credential(compose: list[str], environment: dict[str, str]) -> None:
    code = (
        "from ha_didcomm import config,credentials; "
        "credential=credentials.build_credential("
        "'did:key:lifecycle-subject',config.HOME_ISSUER_DID,'guest',"
        "['light.lifecycle']); "
        f"credentials.remember_issued('lifecycle-connection',credential,"
        f"'{CREDENTIAL_EXCHANGE_ID}')"
    )
    run(
        [*compose, "exec", "-T", "gateway", "python", "-c", code],
        env=environment,
    )


def credential_state(status: dict) -> str | None:
    for record in status.get("credentials", []):
        if record.get("credential_exchange_id") == CREDENTIAL_EXCHANGE_ID:
            return record.get("state")
    return None


def archive_volume(volume: str, archive_directory: Path, filename: str) -> Path:
    archive = archive_directory / filename
    run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{volume}:/source:ro",
            "-v",
            f"{archive_directory}:/backup",
            HELPER_IMAGE,
            "tar",
            "-C",
            "/source",
            "-czf",
            f"/backup/{filename}",
            ".",
        ]
    )
    if not archive.is_file() or archive.stat().st_size == 0:
        raise LifecycleFailure(f"backup archive was not created: {archive}")
    return archive


def restore_volume(volume: str, archive_directory: Path, filename: str) -> None:
    run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{volume}:/restore",
            "-v",
            f"{archive_directory}:/backup:ro",
            HELPER_IMAGE,
            "tar",
            "-C",
            "/restore",
            "-xzf",
            f"/backup/{filename}",
        ]
    )


def assert_compose_volume(volume: str, project: str, logical_name: str) -> None:
    """Fail unless Compose created the restore target with expected labels."""
    result = run(
        [
            "docker",
            "volume",
            "inspect",
            "--format",
            "{{json .Labels}}",
            volume,
        ]
    )
    labels = json.loads(result.stdout)
    expected = {
        "com.docker.compose.project": project,
        "com.docker.compose.volume": logical_name,
    }
    if not isinstance(labels, dict) or any(
        labels.get(key) != value for key, value in expected.items()
    ):
        raise LifecycleFailure(
            f"restore target is not the expected Compose-managed volume: {volume}"
        )


def assert_persisted(
    compose: list[str],
    environment: dict[str, str],
    public_url: str,
    owner_token: str,
    issuer: str,
) -> None:
    wait_for_json(f"{public_url}/owner/health", bearer_token=owner_token)
    if issuer not in wallet_dids(compose, environment):
        raise LifecycleFailure("issuer DID did not survive the lifecycle operation")
    status = request_json(f"{public_url}/owner/status", bearer_token=owner_token)
    if status.get("instance_id") != issuer:
        raise LifecycleFailure("gateway instance ID changed after lifecycle operation")
    if credential_state(status) != "active":
        raise LifecycleFailure("credential record did not survive lifecycle operation")


def main() -> int:
    run(["docker", "info", "--format", "{{.ServerVersion}}"])
    suffix = uuid.uuid4().hex[:8]
    project = f"ha-didcomm-lifecycle-{suffix}"
    wallet_volume = f"{project}-acapy-wallet"
    gateway_volume = f"{project}-gateway-data"
    owner_token = f"lifecycle-owner-{uuid.uuid4().hex}"
    tls_port = free_port()
    public_url = f"https://127.0.0.1:{tls_port}"

    with tempfile.TemporaryDirectory(prefix="ha-didcomm-lifecycle-") as directory:
        temporary = Path(directory)
        certificate, private_key = generate_certificate(temporary)
        environment_file = temporary / "standalone.env"
        override_file = temporary / "lifecycle.override.json"
        backup_directory = temporary / "backup"
        backup_directory.mkdir()
        write_json(
            override_file,
            {
                "services": {
                    "fake-ha": {
                        "image": HELPER_IMAGE,
                        "command": [
                            "python",
                            "-c",
                            (
                                "from http.server import BaseHTTPRequestHandler,"
                                "HTTPServer; HTTPServer(('0.0.0.0',8123),"
                                "BaseHTTPRequestHandler).serve_forever()"
                            ),
                        ],
                    }
                },
                "volumes": {
                    "acapy-wallet": {"name": wallet_volume},
                    "gateway-data": {"name": gateway_volume},
                },
            },
        )
        values = {
            "ACAPY_PUBLIC_ENDPOINT": public_url,
            "TLS_PORT": str(tls_port),
            "TLS_CERT_PATH": str(certificate),
            "TLS_KEY_PATH": str(private_key),
            "ACAPY_LABEL": "lifecycle-home",
            "ACAPY_WALLET_KEY": f"lifecycle-wallet-{uuid.uuid4().hex}",
            "ACAPY_ADMIN_API_KEY": f"lifecycle-admin-{uuid.uuid4().hex}",
            "OWNER_API_TOKEN": owner_token,
            "HA_BASE_URL": "http://fake-ha:8123",
            "HA_TOKEN": "lifecycle-ha-token",
            "HOME_ID": "lifecycle-home",
            "HOME_ISSUER_DID": "did:key:pending",
            "LOG_LEVEL": "warning",
        }
        write_environment(environment_file, values)
        compose = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--project-directory",
            str(ROOT),
            "--env-file",
            str(environment_file),
            "-f",
            str(COMPOSE_FILE),
            "-f",
            str(override_file),
        ]
        environment = os.environ.copy()
        succeeded = False
        try:
            print("Validating a fresh standalone installation...")
            run(
                [
                    *compose,
                    "up",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "90",
                    "acapy",
                    "fake-ha",
                ],
                env=environment,
            )
            issuer = create_issuer(compose, environment)
            values["HOME_ISSUER_DID"] = issuer
            write_environment(environment_file, values)
            run(
                [
                    *compose,
                    "up",
                    "-d",
                    "--build",
                    "--wait",
                    "--wait-timeout",
                    "120",
                ],
                env=environment,
            )
            wait_for_json(f"{public_url}/owner/health", bearer_token=owner_token)
            seed_credential(compose, environment)
            assert_persisted(compose, environment, public_url, owner_token, issuer)

            print("Validating container replacement as an upgrade rehearsal...")
            before = {
                service: run(
                    [*compose, "ps", "-q", service], env=environment
                ).stdout.strip()
                for service in ("acapy", "gateway", "tls-proxy")
            }
            run(
                [
                    *compose,
                    "up",
                    "-d",
                    "--build",
                    "--force-recreate",
                    "--wait",
                    "--wait-timeout",
                    "120",
                    "acapy",
                    "gateway",
                    "tls-proxy",
                ],
                env=environment,
            )
            after = {
                service: run(
                    [*compose, "ps", "-q", service], env=environment
                ).stdout.strip()
                for service in before
            }
            if any(not before[name] or before[name] == after[name] for name in before):
                raise LifecycleFailure(
                    "upgrade rehearsal did not replace every container"
                )
            assert_persisted(compose, environment, public_url, owner_token, issuer)

            print("Creating a cold backup of both persistent volumes...")
            run(
                [*compose, "stop", "tls-proxy", "gateway", "acapy"],
                env=environment,
            )
            archive_volume(wallet_volume, backup_directory, "acapy-wallet.tar.gz")
            archive_volume(gateway_volume, backup_directory, "gateway-data.tar.gz")

            print("Deleting and restoring the deployment volumes...")
            run([*compose, "down", "--volumes", "--remove-orphans"], env=environment)
            run([*compose, "create"], env=environment)
            assert_compose_volume(wallet_volume, project, "acapy-wallet")
            assert_compose_volume(gateway_volume, project, "gateway-data")
            restore_volume(wallet_volume, backup_directory, "acapy-wallet.tar.gz")
            restore_volume(gateway_volume, backup_directory, "gateway-data.tar.gz")
            run(
                [
                    *compose,
                    "up",
                    "-d",
                    "--build",
                    "--wait",
                    "--wait-timeout",
                    "120",
                ],
                env=environment,
            )
            assert_persisted(compose, environment, public_url, owner_token, issuer)

            print("Checking post-restore owner mutation...")
            request_json(
                f"{public_url}/owner/credentials/{CREDENTIAL_EXCHANGE_ID}/revoke",
                method="POST",
                body={},
                bearer_token=owner_token,
            )
            restored_status = request_json(
                f"{public_url}/owner/status", bearer_token=owner_token
            )
            if credential_state(restored_status) != "revoked":
                raise LifecycleFailure("post-restore credential revocation failed")

            succeeded = True
            print("Standalone lifecycle test passed.")
            return 0
        finally:
            if not succeeded:
                logs = run(
                    [*compose, "logs", "--no-color", "--tail", "150"],
                    env=environment,
                    allow_error=True,
                )
                print(logs.stdout, file=sys.stderr)
                print(logs.stderr, file=sys.stderr)
            run(
                [*compose, "down", "--volumes", "--remove-orphans"],
                env=environment,
                allow_error=True,
            )
            for volume in (wallet_volume, gateway_volume):
                run(["docker", "volume", "rm", volume], allow_error=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (json.JSONDecodeError, OSError, URLError, LifecycleFailure) as error:
        print(f"lifecycle test failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
