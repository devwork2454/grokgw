from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "xpage.db"
PROFILES = DATA / "profiles"
SECRETS = DATA / "secrets"
LOGS = DATA / "logs"
AUDIT_LOG = LOGS / "audit.jsonl"
SCHEMA_SQL = Path(__file__).resolve().parent / "schema.sql"
STEALTH_MIN_JS = ROOT / "antibot" / "stealth_min.js"

def ensure_data_dirs() -> None:
    for p in (DATA, PROFILES, SECRETS, LOGS):
        p.mkdir(parents=True, exist_ok=True)
