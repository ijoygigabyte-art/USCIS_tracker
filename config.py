"""
Configuration management for the USCIS Case Status Tracker.
Settings are loaded from a .env file or environment variables, 
with sensible defaults provided.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(Path(__file__).parent / ".env")

# ─────────────────────────────────────────────────────────
# Receipt Numbers to track (comma-separated in .env)
# Example: USCIS_RECEIPT_NUMBERS=IOE0912345678,IOE0912345679
# ─────────────────────────────────────────────────────────
RECEIPT_NUMBERS = [
    r.strip()
    for r in os.getenv("USCIS_RECEIPT_NUMBERS", "").split(",")
    if r.strip()
]

# ─────────────────────────────────────────────────────────
# Polling
# ─────────────────────────────────────────────────────────
POLL_INTERVAL_HOURS = int(os.getenv("USCIS_POLL_INTERVAL_HOURS", "6"))

# ─────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

CASE_HISTORY_FILE = DATA_DIR / "case_history.json"
COOKIES_FILE = DATA_DIR / "session_cookies.enc"

# ─────────────────────────────────────────────────────────
# Notifications
# ─────────────────────────────────────────────────────────
ENABLE_DESKTOP_NOTIFICATIONS = os.getenv("USCIS_DESKTOP_NOTIFY", "true").lower() == "true"
ENABLE_EMAIL_NOTIFICATIONS = os.getenv("USCIS_EMAIL_NOTIFY", "false").lower() == "true"

# Email settings (only needed if ENABLE_EMAIL_NOTIFICATIONS is True)
SMTP_SERVER = os.getenv("USCIS_SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("USCIS_SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("USCIS_SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("USCIS_SMTP_PASSWORD", "")
EMAIL_TO = os.getenv("USCIS_EMAIL_TO", "")

# ─────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────
DASHBOARD_HOST = os.getenv("USCIS_DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.getenv("USCIS_DASHBOARD_PORT", "5000"))

# ─────────────────────────────────────────────────────────
# myUSCIS API endpoints
# ─────────────────────────────────────────────────────────
MYUSCIS_LOGIN_URL = "https://my.uscis.gov/"
MYUSCIS_CASE_API = "https://my.uscis.gov/account/case-service/api/cases/"
EGOV_CASE_STATUS_URL = "https://egov.uscis.gov/casestatus/mycasestatus.do"

# ─────────────────────────────────────────────────────────
# Cookie encryption key (auto-generated on first run)
# ─────────────────────────────────────────────────────────
ENCRYPTION_KEY_FILE = DATA_DIR / ".key"


def get_encryption_key() -> bytes:
    """Get or create the Fernet encryption key for cookie storage."""
    from cryptography.fernet import Fernet

    if ENCRYPTION_KEY_FILE.exists():
        return ENCRYPTION_KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    ENCRYPTION_KEY_FILE.write_bytes(key)
    return key


def load_case_history() -> dict:
    """Load case history from the JSON storage file."""
    if CASE_HISTORY_FILE.exists():
        with open(CASE_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_case_history(history: dict) -> None:
    """Save case history to the JSON storage file."""
    with open(CASE_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, default=str)
