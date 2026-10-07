"""Explicit local development tool. Never runs in SMTP/production mode."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import Settings

s = Settings()
if s.environment == "production" or s.mail_backend != "file":
    raise SystemExit("Only development file mailbox is supported")
email = input("Your registered email: ").strip().lower()
files = sorted(s.mail_directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
for path in files:
    data = json.loads(path.read_text())
    if data["to"] == email:
        print("Code:", data["code"], "(development only)")
        break
else:
    print("No message found. Register or log in first.")
