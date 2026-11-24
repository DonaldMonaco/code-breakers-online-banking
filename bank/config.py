"""Settings, read from environment variables so no password is stored in the code."""
import os
import secrets

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "online_banking"),
    "autocommit": True,
}
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

SESSION_TIMEOUT = 5 * 60      # N4: sign out after 5 minutes without activity
OTP_LIFETIME = 5 * 60         # one-time code is valid for 5 minutes
MAX_FAILED = 5                # F1: lock after 5 wrong passwords ...
LOCK_MINUTES = 15             # ... for 15 minutes
