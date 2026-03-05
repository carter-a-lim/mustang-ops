import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
JOB_PIPELINE_PATH = DATA_DIR / "job_pipeline.json"
AUTO_STATE_PATH = DATA_DIR / "auto_apply_state.json"


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json(path: Path, data: dict) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2) + "\n")


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

    pipeline_data = _load_json(JOB_PIPELINE_PATH, {"applications": []})
    auto_state = _load_json(AUTO_STATE_PATH, {"applications": []})

    updated_pipeline = 0
    updated_auto = 0

    for email in emails:
        subject = email.get("subject", "")
        snippet = email.get("snippet", "")
        sender = email.get("from", "")

        classification = _classify_email(subject, snippet)
        if classification == "other":
            continue

        haystack = f"{subject} {snippet} {sender}".lower()

        # Update Job Pipeline
        for app_item in pipeline_data.get("applications", []):
            company = app_item.get("company", "").lower()
            if not company or len(company) < 3:
                continue

            if company in haystack:
                current_status = app_item.get("status", app_item.get("stage", ""))
                new_status = current_status
                if classification == "reject":
                    new_status = "Rejected"
                elif classification == "interview" and "interview" not in current_status.lower():
                    new_status = "Interview"
                elif classification == "oa" and not any(x in current_status.lower() for x in ["interview", "oa"]):
                    new_status = "OA"

                if new_status != current_status:
                    app_item["status"] = new_status
                    app_item["stage"] = new_status
                    updated_pipeline += 1

        # Update Auto Apply State
        for app_item in auto_state.get("applications", []):
            company = app_item.get("company", "").lower()
            if not company or len(company) < 3:
                continue

            if company in haystack:
                current_status = app_item.get("status", "")
                new_status = current_status
                if classification == "reject":
                    new_status = "rejected"
                elif classification == "interview" and current_status not in ("rejected", "interview"):
                    new_status = "interview"
                elif classification == "oa" and current_status not in ("rejected", "interview", "oa"):
                    new_status = "oa"

                if new_status != current_status:
                    app_item["status"] = new_status
                    updated_auto += 1

    if updated_pipeline:
        _save_json(JOB_PIPELINE_PATH, pipeline_data)
    if updated_auto:
        _save_json(AUTO_STATE_PATH, auto_state)

    print(f"sync_gmail done | updated_pipeline={updated_pipeline} updated_auto={updated_auto}")


if __name__ == "__main__":
    main()
