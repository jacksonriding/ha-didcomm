"""Configuration loaded from environment variables (see .env.example)."""
import os

from dotenv import load_dotenv

load_dotenv()

ACAPY_ADMIN_URL = os.getenv("ACAPY_ADMIN_URL", "http://localhost:8021")
ACAPY_ADMIN_API_KEY = os.getenv("ACAPY_ADMIN_API_KEY")  # None => insecure dev mode

HA_BASE_URL = os.getenv("HA_BASE_URL", "http://localhost:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")

GATEWAY_HOST = os.getenv("GATEWAY_HOST", "0.0.0.0")
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8080"))

HOME_ID = os.getenv("HOME_ID", "jackson-home")

# did:key created via POST /wallet/did/create on the home ACA-Py agent; used
# as the issuer for SmartHomeAccessCredentials (sov/peer connection DIDs
# aren't resolvable without a ledger, so JSON-LD signing needs a did:key).
HOME_ISSUER_DID = os.getenv("HOME_ISSUER_DID", "")


