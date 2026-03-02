import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.common import CONTEXT_PATH, log_job, read_json, utc_now


def main() -> None:
    started = utc_now()
    job = "morning_brief"
    try:
        context = read_json(CONTEXT_PATH, default={})
        priorities = context.get("priorities", [])[:3]
        print("Morning Brief")
        print("Top 3 priorities:")
        for p in priorities:
            print(f"- {p}")
        print("Deadlines:", len(context.get("deadlines", [])))
        print("Experiments:", len(context.get("experiments", [])))
        log_job(job, started_at=started, status="ok")
    except Exception as e:
        log_job(job, started_at=started, status="error", error=str(e))
        raise


if __name__ == "__main__":
    main()
