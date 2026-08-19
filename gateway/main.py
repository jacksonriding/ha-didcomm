"""ACA-Py webhook receiver -> verifiable-credential check -> Home Assistant service call.

v0.0.3: replaces the v0.0.2 static config/policies.yaml allowlist with real
verifiable credentials issued to a connection (see credentials.py). A
message body is expected to use the JSON-RPC schema documented in README.md.
"""
from contextlib import asynccontextmanager
import logging

import httpx

from fastapi import FastAPI, HTTPException, Request

import acapy
import config
import credentials
import home_assistant
import owner
import rpc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")


@asynccontextmanager
async def lifespan(_: FastAPI):
    credentials.initialize_store()
    yield


app = FastAPI(title="ha-didcomm gateway", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/admin/issue-credential")
async def admin_issue_credential(request: Request):
    """Dev-only: owner issues a SmartHomeAccessCredential to a connection.

    subject_did must be a did:key the recipient's agent controls (e.g.
    created via POST /wallet/did/create {"method": "key"} on their agent) --
    connection-scoped sov/peer DIDs aren't resolvable for JSON-LD signing
    without a ledger. Not authenticated -- do not expose this beyond
    localhost/dev.
    """
    body = await request.json()
    connection_id = body["connection_id"]
    credential_exchange_id = await owner.issue_access_credential(
        connection_id=connection_id,
        subject_did=body["subject_did"],
        role=body.get("role", "guest"),
        permissions=body["permissions"],
        expires=body.get("expires"),
    )
    return {"cred_ex_id": credential_exchange_id}


@app.post("/admin/revoke-credential/{credential_exchange_id}")
async def admin_revoke_credential(credential_exchange_id: str):
    """Dev-only: revoke one locally issued credential."""
    if not credentials.revoke_credential(credential_exchange_id):
        raise HTTPException(status_code=404, detail="Credential not found")
    logger.info("Revoked credential %s", credential_exchange_id)
    return {"revoked": True, "cred_ex_id": credential_exchange_id}


@app.post("/admin/revoke-connection/{connection_id}")
async def admin_revoke_connection(connection_id: str):
    """Dev-only: revoke every locally issued credential for a connection."""
    if not credentials.revoke_connection(connection_id):
        raise HTTPException(status_code=404, detail="Connection credentials not found")
    logger.info("Revoked all credentials for connection %s", connection_id)
    return {"revoked": True, "connection_id": connection_id}


@app.post("/topic/{topic}/")
async def acapy_webhook(topic: str, request: Request):
    payload = await request.json()

    if topic == "basicmessages":
        await _handle_basic_message(payload)

    return {"ok": True}


async def _handle_basic_message(payload: dict) -> None:
    if payload.get("state") != "received":
        return

    connection_id = payload.get("connection_id")
    if not isinstance(connection_id, str):
        logger.warning("Ignoring Basic Message without a connection id")
        return
    try:
        request = rpc.parse_request(payload.get("content"))
    except rpc.RpcError as error:
        logger.warning("Rejected RPC request from %s: %s", connection_id, error)
        await _send_rpc_response(connection_id, rpc.failure(error))
        return

    if not credentials.is_authorised(connection_id, request.entity_id):
        logger.info(
            "Denied %s -> %s for connection %s",
            request.action,
            request.entity_id,
            connection_id,
        )
        error = rpc.RpcError(-32001, "Not authorised", request.request_id)
        await _send_rpc_response(connection_id, rpc.failure(error))
        return

    domain = request.entity_id.split(".", 1)[0]
    try:
        await home_assistant.call_service(domain, request.action, request.entity_id)
    except httpx.HTTPError:
        logger.exception("Home Assistant call failed for RPC request %s", request.request_id)
        error = rpc.RpcError(-32603, "Home Assistant call failed", request.request_id)
        await _send_rpc_response(connection_id, rpc.failure(error))
        return
    logger.info(
        "Executed %s -> %s for connection %s",
        request.action,
        request.entity_id,
        connection_id,
    )
    await _send_rpc_response(connection_id, rpc.success(request.request_id))


async def _send_rpc_response(connection_id: str, content: str) -> None:
    try:
        await acapy.send_basic_message(connection_id, content)
    except httpx.HTTPError:
        logger.exception("Could not send RPC response to connection %s", connection_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.GATEWAY_HOST, port=config.GATEWAY_PORT)
