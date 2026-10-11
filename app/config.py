"""Settings, read from environment variables (see .env.example)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{DATA_DIR / 'cashbook.db'}"
    # Supabase / Render give "postgres://" or "postgresql://" — use the psycopg 3 driver.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _db_url()
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
# Set COOKIE_SECURE=1 in production (HTTPS) so the login cookie is never sent over plain HTTP.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
IDLE_TIMEOUT_MIN = int(os.getenv("IDLE_TIMEOUT_MIN", "60"))
TIMEZONE = os.getenv("APP_TIMEZONE", "Africa/Nairobi")

# Photos are compressed in the browser; the server re-checks and shrinks anything bigger.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
PHOTO_TARGET_BYTES = 250 * 1024
PHOTO_MAX_SIDE = 1600

DEFAULT_PROOF_THRESHOLD_CENTS = 500_00  # KES 500
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_MIN = 15

CATEGORIES = [
    "Canisters", "Transport", "Fuel", "Data", "Rent", "Decommissioning",
    "Staff advance", "Repairs", "Loading", "M-Pesa charges", "Other",
]
