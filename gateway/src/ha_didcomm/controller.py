"""Reference remote controller backed by a private ACA-Py Admin API."""
import argparse
import asyncio
import html
from fnmatch import fnmatch
from collections.abc import Sequence
from contextlib import closing
from datetime import datetime, timezone
import base64
import json
import os
import re
from pathlib import Path
import sqlite3
import sys
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import FastAPI, Request

from . import credentials, rpc


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

_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS controller_settings (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_HOLDER_DID_SETTING = "holder_did"
_MAX_INVITATION_INPUT_BYTES = 128 * 1024


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if ADMIN_API_KEY:
        headers["X-API-Key"] = ADMIN_API_KEY
    return headers


def _connect_store() -> sqlite3.Connection:
    path = Path(RESPONSE_STORE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    path.chmod(0o600)
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute(_SCHEMA)
    connection.execute(_SETTINGS_SCHEMA)
    return connection


def _oob_values(candidate: str) -> list[str]:
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return []
    query = parse_qs(parsed.query, keep_blank_values=True)
    return [value for name in ("_oob", "oob") for value in query.get(name, [])]


def _has_one_oob_parameter(candidate: str) -> bool:
    values = _oob_values(candidate)
    return len(values) == 1 and bool(values[0])


def extract_invitation_url(value: str) -> str:
    """Extract a raw OOB URL from CLI input, JSON, or HA action response text."""
    text = html.unescape(value.strip()).replace("\\/", "/")
    if not text:
        raise ValueError("invitation input is empty")
    if not re.search(r"\s", text) and _has_one_oob_parameter(text):
        return text

    candidates: set[str] = set()
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict):
        url = decoded.get("invitation_url")
        if isinstance(url, str) and _has_one_oob_parameter(url):
            candidates.add(url)

    for match in re.finditer(r'"invitation_url"\s*:\s*"((?:\\.|[^"\\])*)"', text):
        try:
            candidate = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, str) and _has_one_oob_parameter(candidate):
            candidates.add(candidate)

    for match in re.finditer(r"https?://[^\s\"'<>]+", text):
        candidate = match.group(0).rstrip(")}],.;")
        if _has_one_oob_parameter(candidate):
            candidates.add(candidate)

    if len(candidates) > 1:
        raise ValueError("invitation input is ambiguous")
    if candidates:
        return candidates.pop()
    raise ValueError("invitation URL has no _oob or oob parameter")


def decode_invitation_url(invitation_url: str) -> dict:
    """Decode an Aries OOB invitation URL into its JSON object."""
    invitation_url = extract_invitation_url(invitation_url)
    values = _oob_values(invitation_url)
    if len(values) != 1 or not values[0]:
        raise ValueError("invitation URL must contain exactly one _oob or oob parameter")
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


def _get_setting(name: str) -> str | None:
    with closing(_connect_store()) as connection:
        row = connection.execute(
            "SELECT value FROM controller_settings WHERE name = ?", (name,)
        ).fetchone()
    return str(row[0]) if row else None


def _set_setting(name: str, value: str) -> None:
    with closing(_connect_store()) as connection:
        with connection:
            connection.execute(
                "INSERT OR REPLACE INTO controller_settings VALUES (?, ?)",
                (name, value),
            )


async def holder_did(selected_did: str | None = None) -> str:
    """Return the persisted did:key identity, creating one only for an empty wallet."""
    selected_did = selected_did or os.getenv("CONTROLLER_HOLDER_DID", "")
    selected_did = selected_did.strip() or None
    if selected_did is not None and not selected_did.startswith("did:key:"):
        raise ValueError("controller identity selector must be a did:key")

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{ADMIN_URL}/wallet/did", headers=_headers())
        response.raise_for_status()
        results = response.json().get("results", [])
        if not isinstance(results, list):
            raise ValueError("ACA-Py did not return wallet DID records")
        key_dids = sorted(
            {
                did
                for record in results
                if isinstance(record, dict)
                if isinstance((did := record.get("did")), str)
                if did.startswith("did:key:")
            }
        )

        if selected_did is not None:
            if selected_did not in key_dids:
                raise ValueError("selected controller identity is not present in the wallet")
            _set_setting(_HOLDER_DID_SETTING, selected_did)
            return selected_did

        saved_did = _get_setting(_HOLDER_DID_SETTING)
        if saved_did is not None:
            if saved_did not in key_dids:
                raise ValueError(
                    "saved controller identity is not present in the wallet; "
                    "restore the wallet or select an existing did:key explicitly"
                )
            return saved_did

        if len(key_dids) == 1:
            _set_setting(_HOLDER_DID_SETTING, key_dids[0])
            return key_dids[0]
        if len(key_dids) > 1:
            raise ValueError(
                "wallet contains multiple did:key identities; select one explicitly"
            )

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
    _set_setting(_HOLDER_DID_SETTING, did)
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
        await _respond_to_command_proof(
            connection_id, rpc.Request(request_id, action, entity_id)
        )
        await asyncio.sleep(0.2)
    raise TimeoutError(
        "no reply received; check the connection, controller-inbox, and home logs"
    )


async def _respond_to_command_proof(connection_id: str, command: rpc.Request) -> None:
    """Answer only a proof request bound to this connection and outstanding call."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{ADMIN_URL}/present-proof-2.0/records",
            params={"connection_id": connection_id, "role": "prover", "state": "request-received"},
            headers=_headers(),
        )
        response.raise_for_status()
        records = response.json().get("results")
        if not isinstance(records, list):
            raise ValueError("ACA-Py did not return presentation records")
        for record in records:
            if not isinstance(record, dict) or (
                record.get("connection_id") != connection_id
                or record.get("role") != "prover"
                or record.get("state") != "request-received"
            ):
                continue
            try:
                definition = record["by_format"]["pres_request"]["dif"]["presentation_definition"]
                if definition["id"] != rpc.proof_request_id(command):
                    continue
                pres_ex_id = record["pres_ex_id"]
            except (KeyError, TypeError):
                continue
            if not isinstance(pres_ex_id, str) or not pres_ex_id:
                continue
            signer = await holder_did()
            response = await client.get(
                f"{ADMIN_URL}/present-proof-2.0/records/{pres_ex_id}/credentials",
                params={"count": 1000},
                headers=_headers(),
            )
            response.raise_for_status()
            record_id = _select_proof_credential(response.json(), definition, signer, command.entity_id)
            if record_id is None:
                continue
            response = await client.post(
                f"{ADMIN_URL}/present-proof-2.0/records/{pres_ex_id}/send-presentation",
                json={"dif": {
                    "issuer_id": signer,
                    "record_ids": {definition["input_descriptors"][0]["id"]: [record_id]},
                }},
                headers=_headers(),
            )
            response.raise_for_status()


def _select_proof_credential(
    candidates: list, definition: dict, signer: str, entity_id: str
) -> str | None:
    """Choose one requested home grant belonging to this wallet identity."""
    try:
        descriptors = definition["input_descriptors"]
        if len(descriptors) != 1 or not descriptors[0]["id"].startswith("home-access:"):
            return None
        fingerprints = descriptors[0]["id"].removeprefix("home-access:").split(",")
        fields = descriptors[0]["constraints"]["fields"]
        if not isinstance(fields, list) or len(fields) != 4:
            return None
        if not isinstance(candidates, list):
            return None
        for candidate in candidates:
            if not isinstance(candidate, dict) or not isinstance(candidate.get("record_id"), str):
                continue
            presented = {key: value for key, value in candidate.items() if key != "record_id"}
            if credentials.credential_fingerprint(presented) not in fingerprints:
                continue
            subject = candidate.get("credentialSubject")
            if not isinstance(subject, dict) or subject.get("id") != signer:
                continue
            permissions = subject.get("permissions")
            if not isinstance(permissions, list) or not any(
                isinstance(pattern, str) and fnmatch(entity_id, pattern) for pattern in permissions
            ):
                continue
            values = {
                "$.issuer": candidate.get("issuer"),
                "$.credentialSubject.id": subject["id"],
                "$.issuanceDate": candidate.get("issuanceDate"),
                "$.credentialSubject.home": subject.get("home"),
            }
            if all(
                field["path"] == [path]
                and (field["filter"].get("const") == values[path]
                     if "const" in field["filter"]
                     else values[path] in field["filter"]["enum"])
                for field, path in zip(fields, values)
            ):
                return candidate["record_id"]
    except (KeyError, TypeError, AttributeError):
        return None
    return None


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
    connect.add_argument("invitation_url", nargs="*")
    connect.add_argument(
        "--stdin", action="store_true", help="read the invitation from standard input"
    )
    identity = commands.add_parser(
        "identity", help="show or create the credential holder DID"
    )
    identity.add_argument(
        "--did", help="select an existing did:key when the wallet contains more than one"
    )
    commands.add_parser("connections", help="list home connections")
    call = commands.add_parser("call", help="call an allowed Home Assistant service")
    call.add_argument("connection_id")
    call.add_argument("action")
    call.add_argument("entity_id")
    call.add_argument("--timeout", type=float, default=45.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "connect":
            if args.stdin and args.invitation_url:
                raise ValueError("use either positional invitation input or --stdin, not both")
            if args.stdin:
                invitation_input = sys.stdin.read(_MAX_INVITATION_INPUT_BYTES + 1)
                if len(invitation_input.encode()) > _MAX_INVITATION_INPUT_BYTES:
                    raise ValueError("invitation input is too large")
            else:
                invitation_input = " ".join(args.invitation_url)
            result = asyncio.run(accept_invitation(invitation_input))
            record_id = result.get("connection_id") or result.get("oob_id") or "accepted"
            print(f"Connection started: {record_id}")
        elif args.command == "identity":
            print(asyncio.run(holder_did(args.did)))
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
