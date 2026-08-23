"""Reference remote controller backed by a private ACA-Py Admin API."""
import argparse
import asyncio
from collections.abc import Sequence
from contextlib import closing
from datetime import datetime, timezone
import base64
import json
import os
from pathlib import Path
import sqlite3
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import FastAPI, Request


ADMIN_URL = os.getenv("CONTROLLER_ACAPY_ADMIN_URL", "http://localhost:8031")
ADMIN_API_KEY = os.getenv("CONTROLLER_ACAPY_ADMIN_API_KEY", "")
RESPONSE_STORE_PATH = os.getenv(
    "CONTROLLER_RESPONSE_STORE_PATH", "data/controller-responses.sqlite3"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rpc_responses (
    request_id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    received_at TEXT NOT NULL
);
"""


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if ADMIN_API_KEY:
        headers["X-API-Key"] = ADMIN_API_KEY
    return headers


def _connect_store() -> sqlite3.Connection:
    path = Path(RESPONSE_STORE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute(_SCHEMA)
    return connection


def decode_invitation_url(invitation_url: str) -> dict:
    """Decode an Aries OOB invitation URL into its JSON object."""
    query = parse_qs(urlparse(invitation_url).query)
    values = query.get("_oob") or query.get("oob")
    if not values or not values[0]:
        raise ValueError("invitation URL has no _oob or oob parameter")
    encoded = values[0]
    try:
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        invitation = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invitation URL contains invalid OOB data") from error
    if not isinstance(invitation, dict):
        raise ValueError("invitation URL did not contain a JSON object")
    return invitation


async def accept_invitation(invitation_url: str) -> dict:
    invitation = decode_invitation_url(invitation_url)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{ADMIN_URL}/out-of-band/receive-invitation",
            params={"auto_accept": "true"},
            json=invitation,
            headers=_headers(),
        )
        response.raise_for_status()
        result = response.json()
    if not isinstance(result, dict):
        raise ValueError("ACA-Py returned an invalid connection record")
    return result


async def holder_did() -> str:
    """Return the first stable did:key in the wallet, creating one if needed."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{ADMIN_URL}/wallet/did", headers=_headers())
        response.raise_for_status()
        results = response.json().get("results", [])
        if isinstance(results, list):
            for record in results:
                did = record.get("did") if isinstance(record, dict) else None
                if isinstance(did, str) and did.startswith("did:key:"):
                    return did

        response = await client.post(
            f"{ADMIN_URL}/wallet/did/create",
            json={"method": "key", "options": {"key_type": "ed25519"}},
            headers=_headers(),
        )
        response.raise_for_status()
        result = response.json().get("result", {})
    did = result.get("did") if isinstance(result, dict) else None
    if not isinstance(did, str) or not did.startswith("did:key:"):
        raise ValueError("ACA-Py did not return a did:key identity")
    return did


async def list_connections() -> list[dict]:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{ADMIN_URL}/connections", headers=_headers())
        response.raise_for_status()
        records = response.json().get("results")
    if not isinstance(records, list) or not all(
        isinstance(item, dict) for item in records
    ):
        raise ValueError("ACA-Py did not return connection records")
    return records


def _store_response(content: dict) -> None:
    request_id = content.get("id")
    if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
        return
    encoded = json.dumps(content, separators=(",", ":"), sort_keys=True)
    received_at = datetime.now(timezone.utc).isoformat()
    with closing(_connect_store()) as connection:
        with connection:
            connection.execute(
                "INSERT OR REPLACE INTO rpc_responses VALUES (?, ?, ?)",
                (str(request_id), encoded, received_at),
            )


def _get_response(request_id: str) -> dict | None:
    with closing(_connect_store()) as connection:
        row = connection.execute(
            "SELECT content FROM rpc_responses WHERE request_id = ?", (request_id,)
        ).fetchone()
    return json.loads(row[0]) if row else None


async def call_service(
    connection_id: str, action: str, entity_id: str, timeout: float
) -> dict:
    request_id = str(uuid.uuid4())
    content = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "homeassistant.call_service",
            "params": {"action": action, "entity_id": entity_id},
        },
        separators=(",", ":"),
    )
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{ADMIN_URL}/connections/{connection_id}/send-message",
            json={"content": content},
            headers=_headers(),
        )
        response.raise_for_status()

    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        result = _get_response(request_id)
        if result is not None:
            return result
        await asyncio.sleep(0.2)
    raise TimeoutError(
        "no reply received; check the connection, controller-inbox, and home logs"
    )


app = FastAPI(title="ha-didcomm reference controller inbox")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/topic/{topic}/")
async def webhook(topic: str, request: Request):
    payload = await request.json()
    if topic == "basicmessages" and payload.get("state") == "received":
        try:
            content = json.loads(payload.get("content", ""))
        except (TypeError, json.JSONDecodeError):
            content = None
        if isinstance(content, dict) and content.get("jsonrpc") == "2.0":
            _store_response(content)
    return {"ok": True}


def _print_connections(records: list[dict]) -> None:
    print("CONNECTION ID\tSTATE\tLABEL\tTHEIR DID")
    for record in records:
        values = (
            record.get("connection_id", "-"),
            record.get("rfc23_state") or record.get("state", "-"),
            record.get("their_label", "-"),
            record.get("their_did", "-"),
        )
        print("\t".join(str(value or "-") for value in values))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Use the ha-didcomm reference controller"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    connect = commands.add_parser("connect", help="accept an OOB invitation URL")
    connect.add_argument("invitation_url")
    commands.add_parser("identity", help="show or create the credential holder DID")
    commands.add_parser("connections", help="list home connections")
    call = commands.add_parser("call", help="call an allowed Home Assistant service")
    call.add_argument("connection_id")
    call.add_argument("action")
    call.add_argument("entity_id")
    call.add_argument("--timeout", type=float, default=15.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "connect":
            result = asyncio.run(accept_invitation(args.invitation_url))
            record_id = result.get("connection_id") or result.get("oob_id") or "accepted"
            print(f"Connection started: {record_id}")
        elif args.command == "identity":
            print(asyncio.run(holder_did()))
        elif args.command == "connections":
            _print_connections(asyncio.run(list_connections()))
        elif args.command == "call":
            result = asyncio.run(
                call_service(args.connection_id, args.action, args.entity_id, args.timeout)
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 2 if "error" in result else 0
    except (httpx.HTTPError, ValueError, TimeoutError) as error:
        parser.exit(1, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
