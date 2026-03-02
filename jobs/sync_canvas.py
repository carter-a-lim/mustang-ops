import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.common import CONTEXT_PATH, log_job, read_json, utc_now, write_json


def main() -> None:
    started = utc_now()
    job = "sync_canvas"
    try:
        context = read_json(CONTEXT_PATH, default={})
        context.setdefault("deadlines", [])
        context["updated_at"] = utc_now()
        # TODO: Pull live deadlines from Canvas API and normalize.
        write_json(CONTEXT_PATH, context)
        log_job(job, started_at=started, status="ok", output_path=str(CONTEXT_PATH))
        print("Canvas sync complete")
    except Exception as e:
        log_job(job, started_at=started, status="error", error=str(e))
        raise


if __name__ == "__main__":
    main()
