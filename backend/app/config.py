import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Load a small, non-overriding dotenv file without requiring shell-specific syntax.
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line=line.strip()
        if line and not line.startswith("#") and "=" in line:
            key,value=line.split("=",1)
            os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))
DATA_DIR = ROOT / "backend" / "data"
MANIFEST_DIR = ROOT / "backend" / "manifests"
db_url=os.getenv("DATABASE_URL", "")
db_path=db_url.removeprefix("sqlite:///") if db_url.startswith("sqlite:///") else ""
DB_PATH = Path(os.getenv("DATABASE_PATH", db_path or ROOT / "backend" / "bhashachain.db"))
if not DB_PATH.is_absolute(): DB_PATH=ROOT/DB_PATH
SIGNING_SECRET = os.getenv("ISSUER_SIGNING_SECRET", "local-demo-only-change-me")
QPIAI_OPT_API_KEY = os.getenv("QPIAI_OPT_API_KEY", "")
QCLOUD_API_KEY = os.getenv("QCLOUD_API_KEY", "")
BLOCKCHAIN_RPC_URL = os.getenv("BLOCKCHAIN_RPC_URL", "")
RIGHTS_LEDGER_ADDRESS = os.getenv("RIGHTS_LEDGER_ADDRESS", "")
BLOCKCHAIN_CHAIN_ID = os.getenv("BLOCKCHAIN_CHAIN_ID", "")
BLOCKCHAIN_PRIVATE_KEY = os.getenv("BLOCKCHAIN_PRIVATE_KEY", "")
BLOCKCHAIN_SENDER_ADDRESS = os.getenv("BLOCKCHAIN_SENDER_ADDRESS", "")
BLOCKCHAIN_MODE = os.getenv("BLOCKCHAIN_MODE", "disabled").strip().lower()
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
API_ACCESS_TOKEN = os.getenv("API_ACCESS_TOKEN", "")
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]
LOCAL_SIGNER_KEY_ID = os.getenv("ISSUER_KEY_ID", "bhashachain-local-ed25519")
TRUSTED_ISSUER_PUBLIC_KEYS_JSON = os.getenv("TRUSTED_ISSUER_PUBLIC_KEYS_JSON", "{}")
