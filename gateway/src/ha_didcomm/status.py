"""Read-only API consumed by the Home Assistant custom integration."""
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException

from . import acapy
from . import config
from . import credentials


@asynccontextmanager
async def lifespan(_: FastAPI):
    credentials.initialize_store()
    yield


app = FastAPI(title="ha-didcomm status API", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/status")
async def status() -> dict:
    """Return sanitized connection and credential state without mutation routes."""
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
