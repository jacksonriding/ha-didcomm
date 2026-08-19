"""Configuration loaded from environment variables (see .env.example)."""
import os

from dotenv import load_dotenv

load_dotenv()

ACAPY_ADMIN_URL = os.getenv("ACAPY_ADMIN_URL", "http://localhost:8021")
ACAPY_ADMIN_API_KEY = os.getenv("ACAPY_ADMIN_API_KEY")

SUPERVISOR_TOKEN = os.getenv("SUPERVISOR_TOKEN")
HA_BASE_URL = (
    "http://supervisor/core"
    if SUPERVISOR_TOKEN
    else os.getenv("HA_BASE_URL", "http://localhost:8123")
)
HA_TOKEN = SUPERVISOR_TOKEN or os.getenv("HA_TOKEN", "")

GATEWAY_HOST = os.getenv("GATEWAY_HOST", "0.0.0.0")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8080"))
STATUS_HOST = os.getenv("STATUS_HOST", "0.0.0.0")
STATUS_PORT = int(os.getenv("STATUS_PORT", "8090"))

# SQLite keeps issued credentials durable without adding another service. The
# parent directory is created by the credential store during startup.
CREDENTIAL_STORE_PATH = os.getenv("CREDENTIAL_STORE_PATH", "data/credentials.sqlite3")

HOME_ID = os.getenv("HOME_ID", "jackson-home")

# did:key created via POST /wallet/did/create on the home ACA-Py agent; used
# as the issuer for SmartHomeAccessCredentials (sov/peer connection DIDs
# aren't resolvable without a ledger, so JSON-LD signing needs a did:key).
HOME_ISSUER_DID = os.getenv("HOME_ISSUER_DID", "")


