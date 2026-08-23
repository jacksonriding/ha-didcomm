#!/usr/bin/env python3
"""Run the complete gateway/controller workflow against real Docker services."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import uuid


ROOT = Path(__file__).resolve().parents[1]
HOME_COMPOSE = ROOT / "compose.yml"
CONTROLLER_COMPOSE = ROOT / "compose.controller.yml"
PERMITTED_ENTITY = "light.guest_room"
DENIED_ENTITY = "light.private_room"


class SmokeFailure(RuntimeError):
    """A smoke-test step did not produce the expected result."""


def run(
    command: list[str], *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = "\n".join(part for part in (result.stdout, result.stderr) if part)
        raise SmokeFailure(
            f"command failed ({result.returncode}): {' '.join(command)}\n{detail}"
        )
    return result


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    api_key: str | None = None,
) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    payload = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=payload, headers=headers, method=method)
    with urlopen(request, timeout=15) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise SmokeFailure(f"expected JSON object from {url}")
    return result


def wait_for_json(
    url: str, *, api_key: str | None = None, timeout: float = 60
) -> dict:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return request_json(url, api_key=api_key)
        except (OSError, URLError, ValueError) as error:
            last_error = error
            time.sleep(1)
    raise SmokeFailure(f"timed out waiting for {url}: {last_error}")


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def write_environment(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def parse_rpc(output: str) -> dict:
    start = output.find("{")
    if start < 0:
        raise SmokeFailure(f"controller did not print a JSON-RPC response: {output}")
    try:
        response = json.loads(output[start:])
    except json.JSONDecodeError as error:
        raise SmokeFailure(f"controller printed invalid JSON-RPC: {output}") from error
    if not isinstance(response, dict):
        raise SmokeFailure("controller JSON-RPC response was not an object")
    return response


def main() -> int:
    run(["docker", "info", "--format", "{{.ServerVersion}}"])
    suffix = uuid.uuid4().hex[:8]
    home_project = f"ha-didcomm-smoke-home-{suffix}"
    controller_project = f"ha-didcomm-smoke-controller-{suffix}"

    with tempfile.TemporaryDirectory(prefix="ha-didcomm-smoke-") as directory:
        temporary = Path(directory)
        home_override = temporary / "home.override.json"
        controller_override = temporary / "controller.override.json"
        gateway_env_file = temporary / "gateway.env"
        controller_env_file = temporary / "controller.env"

        write_json(
            home_override,
            {
                "services": {
                    "fake-ha": {
                        "image": "python:3.14-slim",
                        "command": [
                            "python",
                            "-c",
                            "from http.server import BaseHTTPRequestHandler,HTTPServer\n"
                            "class H(BaseHTTPRequestHandler):\n"
                            " def do_POST(self):\n"
                            "  n=int(self.headers.get('Content-Length','0')); "
                            "b=self.rfile.read(n).decode(); "
                            "print('HA_CALL',self.path,b,flush=True); "
                            "self.send_response(200); "
                            "self.send_header('Content-Type','application/json'); "
                            "self.end_headers(); self.wfile.write(b'[]')\n"
                            " def log_message(self,*args): pass\n"
                            "HTTPServer(('0.0.0.0',8123),H).serve_forever()",
                        ],
                    }
                }
            },
        )
        write_json(
            controller_override,
            {
                "services": {
                    "controller-agent": {"networks": ["default", "home-test"]}
                },
                "networks": {
                    "home-test": {
                        "external": True,
                        "name": f"{home_project}_default",
                    }
                },
            },
        )
        write_environment(
            controller_env_file,
            {
                "CONTROLLER_PUBLIC_ENDPOINT": "http://controller-agent:8010",
                "CONTROLLER_PORT": "8010",
                "CONTROLLER_LABEL": "docker-smoke-controller",
                "CONTROLLER_WALLET_KEY": "smoke-controller-wallet-key",
                "CONTROLLER_ADMIN_API_KEY": "smoke-controller-admin-key",
                "LOG_LEVEL": "warning",
            },
        )
        # Compose resolves env_file entries before selecting target services,
        # so provide a harmless placeholder before ACA-Py creates the real DID.
        write_environment(
            gateway_env_file,
            {
                "ACAPY_ADMIN_URL": "http://acapy-home:8021",
                "ACAPY_ADMIN_API_KEY": "change-me-home-admin",
                "HA_BASE_URL": "http://fake-ha:8123",
                "HA_TOKEN": "smoke-ha-token",
                "HOME_ID": "docker-smoke-home",
                "HOME_ISSUER_DID": "did:key:pending",
            },
        )

        home = [
            "docker",
            "compose",
            "--project-name",
            home_project,
            "--project-directory",
            str(ROOT),
            "-f",
            str(HOME_COMPOSE),
            "-f",
            str(home_override),
        ]
        controller = [
            "docker",
            "compose",
            "--project-name",
            controller_project,
            "--project-directory",
            str(ROOT),
            "--env-file",
            str(controller_env_file),
            "-f",
            str(CONTROLLER_COMPOSE),
            "-f",
            str(controller_override),
        ]
        compose_env = os.environ.copy()
        compose_env["ACAPY_HOME_ENDPOINT"] = "http://acapy-home:8000"
        compose_env["GATEWAY_ENV_FILE"] = str(gateway_env_file)

        succeeded = False
        try:
            print("Starting home ACA-Py and fake Home Assistant...")
            run([*home, "up", "-d", "acapy-home", "fake-ha"], env=compose_env)
            wait_for_json(
                "http://127.0.0.1:8021/status/live",
                api_key="change-me-home-admin",
            )
            issuer = request_json(
                "http://127.0.0.1:8021/wallet/did/create",
                method="POST",
                api_key="change-me-home-admin",
                body={"method": "key", "options": {"key_type": "ed25519"}},
            )["result"]["did"]
            write_environment(
                gateway_env_file,
                {
                    "ACAPY_ADMIN_URL": "http://acapy-home:8021",
                    "ACAPY_ADMIN_API_KEY": "change-me-home-admin",
                    "HA_BASE_URL": "http://fake-ha:8123",
                    "HA_TOKEN": "smoke-ha-token",
                    "HOME_ID": "docker-smoke-home",
                    "HOME_ISSUER_DID": issuer,
                },
            )
            run([*home, "up", "-d", "--build", "gateway"], env=compose_env)
            wait_for_json("http://127.0.0.1:8080/health")

            print("Starting reference controller...")
            run([*controller, "build", "controller", "controller-inbox"])
            run(
                [
                    *controller,
                    "up",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "60",
                    "controller-agent",
                    "controller-inbox",
                ]
            )

            def controller_cli(
                *arguments: str, allow_error: bool = False
            ) -> subprocess.CompletedProcess:
                result = subprocess.run(
                    [
                        *controller,
                        "run",
                        "--rm",
                        "--no-deps",
                        "controller",
                        *arguments,
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if result.returncode and not allow_error:
                    raise SmokeFailure(result.stderr or result.stdout)
                return result

            invitation = request_json(
                "http://127.0.0.1:8021/out-of-band/create-invitation"
                "?auto_accept=true&multi_use=false",
                method="POST",
                api_key="change-me-home-admin",
                body={
                    "handshake_protocols": ["https://didcomm.org/didexchange/1.1"],
                    "protocol_version": "1.1",
                    "use_did_method": "did:peer:4",
                    "my_label": "Docker smoke home",
                },
            )
            controller_cli("connect", invitation["invitation_url"])

            print("Waiting for DID Exchange...")
            home_connection_id = None
            controller_connection_id = None
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                home_records = request_json(
                    "http://127.0.0.1:8021/connections",
                    api_key="change-me-home-admin",
                ).get("results", [])
                completed = [
                    record
                    for record in home_records
                    if record.get("their_label") == "docker-smoke-controller"
                    and (
                        record.get("rfc23_state") == "completed"
                        or record.get("state") == "active"
                    )
                ]
                lines = controller_cli("connections").stdout.splitlines()[1:]
                controller_ids = [
                    line.split("\t", 1)[0]
                    for line in lines
                    if "\tcompleted\t" in line or "\tactive\t" in line
                ]
                if completed and controller_ids:
                    home_connection_id = completed[-1]["connection_id"]
                    controller_connection_id = controller_ids[-1]
                    break
                time.sleep(1)
            if not home_connection_id or not controller_connection_id:
                raise SmokeFailure("DID Exchange did not reach completed state")

            holder_did = controller_cli("identity").stdout.strip().splitlines()[-1]
            if not holder_did.startswith("did:key:"):
                raise SmokeFailure(
                    f"controller returned invalid holder DID: {holder_did}"
                )
            issued = request_json(
                "http://127.0.0.1:8080/admin/issue-credential",
                method="POST",
                body={
                    "connection_id": home_connection_id,
                    "subject_did": holder_did,
                    "role": "guest",
                    "permissions": [PERMITTED_ENTITY],
                },
            )
            if not issued.get("cred_ex_id"):
                raise SmokeFailure("gateway did not return a credential exchange id")

            print("Checking authorized and unauthorized commands...")
            allowed = parse_rpc(
                controller_cli(
                    "call", controller_connection_id, "turn_on", PERMITTED_ENTITY
                ).stdout
            )
            if allowed.get("result") != {"executed": True}:
                raise SmokeFailure(f"authorized command failed: {allowed}")

            denied_result = controller_cli(
                "call",
                controller_connection_id,
                "turn_on",
                DENIED_ENTITY,
                allow_error=True,
            )
            denied = parse_rpc(denied_result.stdout)
            if (
                denied_result.returncode != 2
                or denied.get("error", {}).get("code") != -32001
            ):
                raise SmokeFailure(f"unauthorized command was not denied: {denied}")

            print("Revoking access and checking immediate enforcement...")
            request_json(
                f"http://127.0.0.1:8080/admin/revoke-connection/{home_connection_id}",
                method="POST",
                body={},
            )
            revoked_result = controller_cli(
                "call",
                controller_connection_id,
                "turn_on",
                PERMITTED_ENTITY,
                allow_error=True,
            )
            revoked = parse_rpc(revoked_result.stdout)
            if (
                revoked_result.returncode != 2
                or revoked.get("error", {}).get("code") != -32001
            ):
                raise SmokeFailure(f"revoked command was not denied: {revoked}")

            ha_logs = run(
                [*home, "logs", "--no-color", "fake-ha"], env=compose_env
            ).stdout
            calls = [line for line in ha_logs.splitlines() if "HA_CALL" in line]
            if len(calls) != 1 or PERMITTED_ENTITY not in calls[0]:
                raise SmokeFailure(
                    f"expected exactly one permitted Home Assistant call: {calls}"
                )

            succeeded = True
            print("Docker smoke test passed.")
            return 0
        finally:
            if not succeeded:
                for command, environment in (
                    ([*home, "logs", "--no-color", "--tail", "100"], compose_env),
                    ([*controller, "logs", "--no-color", "--tail", "100"], None),
                ):
                    result = subprocess.run(
                        command,
                        cwd=ROOT,
                        env=environment,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    print(result.stdout, file=sys.stderr)
                    print(result.stderr, file=sys.stderr)
            subprocess.run(
                [*controller, "down", "--volumes", "--remove-orphans"],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            subprocess.run(
                [*home, "down", "--volumes", "--remove-orphans"],
                cwd=ROOT,
                env=compose_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, SmokeFailure, URLError) as error:
        print(f"smoke test failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
