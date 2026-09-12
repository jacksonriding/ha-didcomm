"""Minimal JSON-RPC 2.0 command envelope for DIDComm Basic Messages."""
import json
import hashlib
from uuid import UUID
from dataclasses import dataclass


@dataclass(frozen=True)
class Request:
    request_id: str | int
    action: str
    entity_id: str


def proof_request_id(request: Request) -> str:
    """Bind the presentation definition to the typed RPC id and exact command."""
    encoded = json.dumps(
        [request.request_id, request.action, request.entity_id],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode()
    # ACA-Py's DIF schema requires the UUID4 wire format, including for PD ids.
    return str(UUID(bytes=hashlib.sha256(encoded).digest()[:16], version=4))


class RpcError(ValueError):
    def __init__(self, code: int, message: str, request_id=None):
        super().__init__(message)
        self.code = code
        self.request_id = request_id


def parse_request(content: str) -> Request:
    try:
        body = json.loads(content)
    except (TypeError, json.JSONDecodeError) as error:
        raise RpcError(-32700, "Parse error") from error
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        raise RpcError(-32600, "Invalid Request")
    request_id = body.get("id")
    if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
        raise RpcError(-32600, "A string or integer id is required")
    if body.get("method") != "homeassistant.call_service":
        raise RpcError(-32601, "Method not found", request_id)
    params = body.get("params")
    if not isinstance(params, dict):
        raise RpcError(-32602, "Invalid params", request_id)
    action = params.get("action")
    entity_id = params.get("entity_id")
    if not isinstance(action, str) or not action or not isinstance(entity_id, str):
        raise RpcError(-32602, "action and entity_id are required", request_id)
    if "." not in entity_id:
        raise RpcError(-32602, "entity_id must include a domain", request_id)
    return Request(request_id, action, entity_id)


def success(request_id: str | int) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {"executed": True}})


def failure(error: RpcError) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": error.request_id,
            "error": {"code": error.code, "message": str(error)},
        }
    )
