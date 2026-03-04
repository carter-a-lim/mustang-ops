import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
APPLICATIONS_PATH = DATA_DIR / "applications.json"


def _load_applications() -> dict:
    if not APPLICATIONS_PATH.exists():
        return {"updated_at": None, "applications": []}
    try:
        return json.loads(APPLICATIONS_PATH.read_text())
    except Exception:
        return {"updated_at": None, "applications": []}


def _save_applications(data: dict) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    APPLICATIONS_PATH.write_text(json.dumps(data, indent=2) + "\n")


def _classify_email(subject: str, snippet: str) -> str:
    text = f"{subject} {snippet}".lower()

    if any(k in text for k in ["interview", "schedule", "recruiter chat"]):
        return "interview"
    if any(k in text for k in ["assessment", "hackerrank", "codesignal", "online test", "oa"]):
        return "oa"
    if any(k in text for k in ["unfortunately", "not moving forward", "other candidates", "regret"]):
        return "reject"
    return "other"


def main() -> None:
    account = os.getenv("GOG_ACCOUNT")
    if not account:
        print("sync_gmail skipped: GOG_ACCOUNT not set")
        return

    search = subprocess.run(
        ["gog", "gmail", "search", "newer_than:14d", "--max", "50", "--json", "--no-input"],
        capture_output=True,
        text=True,
        env={**os.environ, "GOG_ACCOUNT": account},
        check=False,
    )

    if search.returncode != 0:
        print(f"sync_gmail failed: {search.stderr.strip()}")
        return

    try:
        emails = json.loads(search.stdout)
    except Exception as exc:
        print(f"sync_gmail parse error: {exc}")
        return

    apps_data = _load_applications()
    apps = apps_data.get("applications", [])
    updated = 0

    for email in emails:
        subject = email.get("subject", "")
        snippet = email.get("snippet", "")
        sender = email.get("from", "")

        classification = _classify_email(subject, snippet)
        if classification == "other":
            continue

        for app_item in apps:
            company = app_item.get("company", "").lower()
            if not company or len(company) < 3:
                continue

            haystack = f"{subject} {snippet} {sender}".lower()
            if company not in haystack:
                continue

            current_status = app_item.get("status", "")
            new_status = current_status
            if classification == "reject":
                new_status = "reject"
            elif classification == "interview" and current_status not in ("reject", "interview"):
                new_status = "interview"
            elif classification == "oa" and current_status not in ("reject", "interview", "oa"):
                new_status = "oa"

            if new_status != current_status:
                app_item["status"] = new_status
                updated += 1

    if updated:
        _save_applications(apps_data)

    print(f"sync_gmail done | updated={updated}")


if __name__ == "__main__":
    main()
