import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.common import CONTEXT_PATH, log_job, read_json, utc_now, write_json


def main() -> None:
    started = utc_now()
    job = "linkedin_scout"
    try:
        context = read_json(CONTEXT_PATH, default={})
        queue = context.setdefault("outreach_queue", [])
        # TODO: Replace with real scout logic.
        queue.append({
            "name": "Sample Prospect",
            "segment": "SLO local business owner",
            "status": "queued",
            "added_at": utc_now(),
            "confidence": 0.5
        })
        context["updated_at"] = utc_now()
        write_json(CONTEXT_PATH, context)
        log_job(job, started_at=started, status="ok", output_path=str(CONTEXT_PATH))
        print("LinkedIn scout updated queue")
    except Exception as e:
        log_job(job, started_at=started, status="error", error=str(e))
        raise


if __name__ == "__main__":
    main()
