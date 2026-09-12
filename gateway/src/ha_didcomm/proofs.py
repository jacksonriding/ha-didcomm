"""Fresh, command-bound DIF proofs using ACA-Py's private authenticated API."""

import asyncio
from contextlib import closing
import json
import hashlib
import logging
import secrets
import time
from uuid import UUID

import httpx

from . import acapy, config, credentials, rpc

logger = logging.getLogger(__name__)
PROOF_TIMEOUT = 30
MAX_PENDING = 32
COMMAND_RETENTION = 24 * 60 * 60
_SCHEMA = """
CREATE TABLE IF NOT EXISTS proof_commands (
    connection_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    pending INTEGER NOT NULL,
    PRIMARY KEY (connection_id, request_id)
);
"""


def claim_command(connection_id: str, request: rpc.Request) -> bool:
    """Reserve a command before any await; suppress redelivery across restarts."""
    credentials.initialize_store()
    now = time.time()
    with closing(credentials._connect()) as connection:
        with connection:
            connection.execute(_SCHEMA)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM proof_commands WHERE created_at < ?",
                (now - COMMAND_RETENTION,),
            )
            pending = connection.execute(
                "SELECT COUNT(*) FROM proof_commands WHERE pending = 1 AND created_at > ?",
                (now - PROOF_TIMEOUT,),
            ).fetchone()[0]
            if pending >= MAX_PENDING:
                return False
            result = connection.execute(
                "INSERT OR IGNORE INTO proof_commands VALUES (?, ?, ?, 1)",
                (connection_id, json.dumps(request.request_id), now),
            )
    return result.rowcount == 1


def finish_command(connection_id: str, request: rpc.Request) -> None:
    with closing(credentials._connect()) as connection:
        with connection:
            connection.execute(
                "UPDATE proof_commands SET pending = 0 WHERE connection_id = ? AND request_id = ?",
                (connection_id, json.dumps(request.request_id)),
            )


def build_request(connection_id: str, request: rpc.Request) -> dict:
    grants = [
        credential
        for credential in credentials._issued_for_connection(connection_id)
        if credentials.is_presented_authorised(connection_id, request.entity_id, credential)
    ]
    return {
        "connection_id": connection_id,
        "auto_verify": True,
        "auto_remove": False,
        "presentation_request": {
            "dif": {
                "options": {
                    # ACA-Py's DIF builder does not propagate domain to the
                    # signature. Bind our context into the signed challenge.
                    "challenge": str(UUID(bytes=hashlib.sha256(json.dumps([
                        config.HOME_ID, config.HOME_ISSUER_DID, rpc.proof_request_id(request)
                    ]).encode() + secrets.token_bytes(32)).digest()[:16], version=4)),
                },
                "presentation_definition": {
                    "id": rpc.proof_request_id(request),
                    "format": {"ldp_vp": {"proof_type": ["Ed25519Signature2018"]}},
                    "input_descriptors": [{
                        # The descriptor id is opaque to ACA-Py. Including exact
                        # eligible payload fingerprints lets the reference
                        # controller distinguish locally revoked/renewed grants.
                        "id": "home-access:" + ",".join(sorted({
                            credentials.credential_fingerprint(grant) for grant in grants
                        })),
                        "schema": [{
                            "uri": "https://ha-didcomm.dev/credentials#SmartHomeAccessCredential",
                        }],
                        "constraints": {"fields": [
                            {"path": ["$.issuer"], "filter": {"const": config.HOME_ISSUER_DID}},
                            {"path": ["$.credentialSubject.id"], "filter": {
                                "enum": [grant["credentialSubject"]["id"] for grant in grants]
                            }},
                            {"path": ["$.issuanceDate"], "filter": {
                                "enum": [grant["issuanceDate"] for grant in grants]
                            }},
                            {"path": ["$.credentialSubject.home"], "filter": {"const": config.HOME_ID}},
                        ]},
                    }],
                },
            },
        },
    }


def valid_presented_credential(
    record: dict, connection_id: str, pres_ex_id: str, dif_request: dict
) -> dict | None:
    """Bind ACA-Py's verified result to our request and the VC subject's key.

    This does not implement signature verification. Only records retrieved
    from the authenticated verifier Admin API may be passed here.
    """
    if not isinstance(record, dict) or (
        record.get("pres_ex_id") != pres_ex_id
        or record.get("connection_id") != connection_id
        or record.get("role") != "verifier"
        or record.get("state") != "done"
        or not (record.get("verified") is True or record.get("verified") == "true")
    ):
        return None
    try:
        formats = record["by_format"]
        if formats["pres_request"]["dif"] != dif_request:
            return None
        presentations = formats["pres"]["dif"]
        if isinstance(presentations, dict):
            presentations = [presentations]
        if not isinstance(presentations, list) or len(presentations) != 1:
            return None
        presentation = presentations[0]
        proof = presentation["proof"]
        options = dif_request["options"]
        if (
            proof["type"] != "Ed25519Signature2018"
            or proof["proofPurpose"] != "authentication"
            or proof["challenge"] != options["challenge"]
            or presentation["presentation_submission"]["definition_id"]
            != dif_request["presentation_definition"]["id"]
        ):
            return None
        vcs = presentation["verifiableCredential"]
        if not isinstance(vcs, list) or len(vcs) != 1 or not isinstance(vcs[0], dict):
            return None
        credential = vcs[0]
        subject = credential["credentialSubject"]["id"]
        if not isinstance(subject, str) or not subject.startswith("did:key:"):
            return None
        if proof["verificationMethod"] != subject + "#" + subject.removeprefix("did:key:"):
            return None
        if "holder" in presentation and presentation["holder"] != subject:
            return None
        return credential
    except (KeyError, TypeError, IndexError):
        return None


async def request_proof(connection_id: str, request: rpc.Request) -> dict | None:
    """Wait for a fresh verified exchange, denying on any error or timeout."""
    pres_ex_id = None
    body = build_request(connection_id, request)
    try:
        async with asyncio.timeout(PROOF_TIMEOUT):
            sent = await acapy.send_proof_request(body)
            pres_ex_id = sent.get("pres_ex_id") if isinstance(sent, dict) else None
            if not isinstance(pres_ex_id, str) or not pres_ex_id:
                return None
            while True:
                record = await acapy.get_proof_record(pres_ex_id)
                if not isinstance(record, dict):
                    return None
                if record.get("state") == "abandoned":
                    return None
                if record.get("state") == "done":
                    return valid_presented_credential(
                        record, connection_id, pres_ex_id, body["presentation_request"]["dif"]
                    )
                await asyncio.sleep(0.2)
    except (httpx.HTTPError, TimeoutError, ValueError):
        logger.warning("Credential possession proof failed or timed out")
        return None
    finally:
        if isinstance(pres_ex_id, str) and pres_ex_id:
            try:
                async with asyncio.timeout(3):
                    await acapy.delete_proof_record(pres_ex_id)
            except (httpx.HTTPError, TimeoutError):
                logger.warning("Could not remove presentation exchange record")
