"""Authorization policy.

v0.0.2: a static connection_id -> allowed entity_id allowlist loaded from
config/policies.yaml. v0.0.3 replaces this with verifiable credential
proof requests.
"""
import logging
from fnmatch import fnmatch

import yaml

import config

logger = logging.getLogger("gateway")


def _load_policies() -> dict:
    try:
        with open(config.POLICY_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("Policy file not found at %s; denying everything", config.POLICY_FILE)
        return {}
    return data.get("connections") or {}


def is_authorised(connection_id: str, entity_id: str) -> bool:
    # Re-read on every call: policy is small and dev-oriented, no need to cache/reload.
    connections = _load_policies()
    allowed = connections.get(connection_id, {}).get("allow", [])
    return any(fnmatch(entity_id, pattern) for pattern in allowed)
