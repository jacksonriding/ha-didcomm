"""ACA-Py webhook receiver -> policy check -> Home Assistant service call.

v0.0.1: handles the `basicmessages` webhook topic only. A message body is
expected to be JSON: {"action": "turn_on", "entity_id": "input_boolean.ssi_test"}.
The Home Assistant domain is derived from the entity_id prefix.
"""
import json
import logging

from fastapi import FastAPI, Request

import config
import home_assistant
import policy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")

app = FastAPI(title="ha-didcomm gateway")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/topic/{topic}/")
async def acapy_webhook(topic: str, request: Request):
    payload = await request.json()

    if topic != "basicmessages" or payload.get("state") != "received":
        return {"ignored": True}

    connection_id = payload["connection_id"]
    try:
        command = json.loads(payload["content"])
        entity_id = command["entity_id"]
        action = command["action"]
        domain = entity_id.split(".", 1)[0]
    except (KeyError, ValueError, json.JSONDecodeError):
        logger.warning("Ignoring malformed command from %s: %r", connection_id, payload.get("content"))
        return {"ignored": True}

    if not policy.is_authorised(connection_id, entity_id):
        logger.info("Denied %s -> %s for connection %s", action, entity_id, connection_id)
        return {"authorised": False}

    await home_assistant.call_service(domain, action, entity_id)
    logger.info("Executed %s -> %s for connection %s", action, entity_id, connection_id)
    return {"authorised": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.GATEWAY_HOST, port=config.GATEWAY_PORT)
