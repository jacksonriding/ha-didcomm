"""Authorization policy.

v0.0.1: every connected agent is trusted. This is intentionally a stub —
v0.0.2 replaces it with a connection/DID allowlist loaded from
config/policies.yaml, and v0.0.3 replaces that with verifiable credential
proof requests.
"""


def is_authorised(connection_id: str, entity_id: str) -> bool:
    return True
