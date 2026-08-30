"""Status and authenticated owner API consumed by Home Assistant."""

import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import acapy, config, credentials, owner


@asynccontextmanager
async def lifespan(_: FastAPI):
    credentials.initialize_store()
    yield


app = FastAPI(title="ha-didcomm status API", lifespan=lifespan)

MIN_OWNER_TOKEN_LENGTH = 32
_PLACEHOLDER_PREFIXES = ("change-me", "replace-with", "your-")


class InvitationRequest(BaseModel):
    """Owner invitation request."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str | None = Field(default=None, min_length=1, max_length=128)


class CredentialRequest(BaseModel):
    """Owner credential issuance request."""

    model_config = ConfigDict(str_strip_whitespace=True)

    connection_id: str = Field(min_length=1)
    subject_did: str = Field(pattern=r"^did:key:\S+$")
    permissions: list[str] = Field(min_length=1)
    role: str = Field(default="guest", min_length=1, max_length=128)
    duration_hours: int = Field(ge=1, le=8760)


def _configured_owner_token() -> str | None:
    token = config.OWNER_API_TOKEN.strip()
    if len(token) < MIN_OWNER_TOKEN_LENGTH or token.lower().startswith(
        _PLACEHOLDER_PREFIXES
    ):
        return None
    return token


async def require_owner(
    authorization: str | None = Header(default=None),
) -> None:
    """Require the separately configured owner bearer token."""
    configured = _configured_owner_token()
    if configured is None:
        raise HTTPException(status_code=503, detail="Owner API is not configured")
    scheme, separator, supplied = (authorization or "").partition(" ")
    if (
        not separator
        or scheme.lower() != "bearer"
        or not secrets.compare_digest(supplied, configured)
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid owner credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


async def _detailed_status() -> dict:
    try:
        raw_connections = await acapy.list_connections()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=503, detail="ACA-Py is unavailable") from error

    connections = []
    for record in raw_connections:
        connection_id = record.get("connection_id")
        if not isinstance(connection_id, str):
            continue
        connections.append(
            {
                "id": connection_id,
                "state": record.get("state")
                if isinstance(record.get("state"), str)
                else "unknown",
                "label": record.get("their_label")
                if isinstance(record.get("their_label"), str)
                else None,
                "their_did": record.get("their_did")
                if isinstance(record.get("their_did"), str)
                else None,
                "created_at": record.get("created_at")
                if isinstance(record.get("created_at"), str)
                else None,
                "updated_at": record.get("updated_at")
                if isinstance(record.get("updated_at"), str)
                else None,
            }
        )

    return {
        "instance_id": config.HOME_ISSUER_DID or config.HOME_ID,
        "home_id": config.HOME_ID,
        "connections": connections,
        "credentials": credentials.list_issued(),
    }


@app.get("/status")
async def status() -> dict:
    """Return operational state without exposing DIDComm or credential details."""
    details = await _detailed_status()
    return {
        "status": "ok",
        "instance_id": details["instance_id"],
        "home_id": details["home_id"],
        "connections": [],
        "credentials": [],
        "connection_count": len(details["connections"]),
        "credential_counts": credentials.count_issued_by_state(),
    }


@app.get("/owner/status", dependencies=[Depends(require_owner)])
async def owner_status() -> dict:
    """Return detailed owner-facing connection and credential state."""
    return await _detailed_status()


@app.get("/owner/health", dependencies=[Depends(require_owner)])
async def owner_health() -> dict:
    return {"status": "ok"}


@app.post("/owner/invitations", dependencies=[Depends(require_owner)])
async def create_invitation(request: InvitationRequest) -> dict:
    try:
        invitation = await acapy.create_oob_invitation(
            label=request.label,
            multi_use=False,
            auto_accept=True,
        )
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=503, detail="ACA-Py is unavailable") from error
    response = {"invitation_url": invitation["invitation_url"]}
    if isinstance(invitation.get("oob_id"), str):
        response["oob_id"] = invitation["oob_id"]
    return response


@app.post("/owner/credentials", dependencies=[Depends(require_owner)])
async def issue_credential(request: CredentialRequest) -> dict:
    if not all(permission.strip() for permission in request.permissions):
        raise HTTPException(
            status_code=400,
            detail="Permissions must contain only non-empty strings",
        )
    expires_at = datetime.now(timezone.utc) + timedelta(hours=request.duration_hours)
    expires = expires_at.isoformat().replace("+00:00", "Z")
    try:
        credential_exchange_id = await owner.issue_access_credential(
            connection_id=request.connection_id,
            subject_did=request.subject_did,
            role=request.role,
            permissions=request.permissions,
            expires=expires,
        )
    except owner.EquivalentActiveGrantError as error:
        raise HTTPException(
            status_code=409,
            detail="An equivalent active grant already exists",
        ) from error
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=503, detail="Credential issuance failed"
        ) from error
    return {"cred_ex_id": credential_exchange_id, "expires_at": expires}


@app.post(
    "/owner/credentials/{credential_exchange_id}/revoke",
    dependencies=[Depends(require_owner)],
)
async def revoke_credential(credential_exchange_id: str) -> dict:
    if not credentials.revoke_credential(credential_exchange_id):
        raise HTTPException(status_code=404, detail="Credential was not found")
    return {"revoked": True, "cred_ex_id": credential_exchange_id}


@app.post(
    "/owner/connections/{connection_id}/revoke",
    dependencies=[Depends(require_owner)],
)
async def revoke_connection(connection_id: str) -> dict:
    if not credentials.revoke_connection(connection_id):
        raise HTTPException(status_code=404, detail="Connection was not found")
    return {"revoked": True, "connection_id": connection_id}
